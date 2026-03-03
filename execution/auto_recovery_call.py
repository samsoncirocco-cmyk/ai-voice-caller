#!/usr/bin/env python3
"""
Auto-Recovery Caller — runs via cron, checks number health, calls if clear.

Add to crontab (every 30 min from 7am-6pm MST):
  */30 7-18 * * * cd ~/.openclaw/workspace/projects/ai-voice-caller && python3 execution/auto_recovery_call.py >> logs/auto_recovery.log 2>&1

Logic:
  1. Check last 10 calls for platform-block ratio
  2. If failures < 3/10 → make the call to Samson's cell
  3. If call succeeds → write success marker, stop future runs
  4. If still blocked → log and exit quietly
"""
import json
import sys
import os
import time
from datetime import datetime

import requests
from google.cloud import firestore

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config", "signalwire.json")
MARKER_FILE = os.path.join(BASE_DIR, "logs", "recovery_success.marker")
TARGET_NUMBER = "+16022950104"  # Samson's cell

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def check_health(config):
    """Check recent call history. Returns (block_count, total, last_success)."""
    r = requests.get(
        f"https://{config['space_url']}/api/laml/2010-04-01/Accounts/{config['project_id']}/Calls.json?PageSize=10",
        auth=(config['project_id'], config['auth_token']),
        timeout=10,
    )
    calls = r.json().get("calls", [])
    blocks = 0
    last_success = None
    for c in calls:
        if c["status"] == "failed" and c["duration"] == 0 and c.get("sip_result_code") is None:
            blocks += 1
        elif c["status"] == "completed" and c["duration"] > 0:
            if not last_success:
                last_success = c["date_created"]
    return blocks, len(calls), last_success

def make_call(config):
    """Make the recovery call to Samson's cell."""
    agent_id = config["ai_agent"]["agent_id"]
    api_url = f"https://{config['space_url']}/api/laml/2010-04-01/Accounts/{config['project_id']}/Calls.json"
    agent_url = f"https://{config['space_url']}/api/ai/agent/{agent_id}"

    resp = requests.post(api_url, auth=(config['project_id'], config['auth_token']), data={
        "From": config["phone_number"],
        "To": TARGET_NUMBER,
        "Url": agent_url,
    }, timeout=15)

    if resp.status_code not in [200, 201]:
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"

    data = resp.json()
    sid = data.get("sid")

    # Wait and verify
    time.sleep(25)
    check = requests.get(
        f"https://{config['space_url']}/api/laml/2010-04-01/Accounts/{config['project_id']}/Calls/{sid}.json",
        auth=(config['project_id'], config['auth_token']),
        timeout=10,
    )
    cd = check.json()
    return cd, None

def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Check if already succeeded
    if os.path.exists(MARKER_FILE):
        print(f"[{now}] Recovery already succeeded. Remove {MARKER_FILE} to re-enable.")
        return

    config = load_config()
    blocks, total, last_success = check_health(config)

    print(f"[{now}] Health check: {blocks}/{total} platform blocks, last success: {last_success or 'none'}")

    if blocks >= 3:
        print(f"[{now}] Still blocked ({blocks}/{total}). Waiting.")
        return

    print(f"[{now}] Number looks healthy! Attempting call to {TARGET_NUMBER}...")
    result, error = make_call(config)

    if error:
        print(f"[{now}] Call failed: {error}")
        return

    status = result.get("status", "unknown")
    duration = result.get("duration", 0)
    sip = result.get("sip_result_code")
    sid = result.get("sid", "unknown")

    print(f"[{now}] Result: status={status}, duration={duration}s, sip={sip}, sid={sid}")

    if status in ("completed", "in-progress") and duration > 0:
        print(f"[{now}] SUCCESS! Call connected for {duration}s.")
        os.makedirs(os.path.dirname(MARKER_FILE), exist_ok=True)
        with open(MARKER_FILE, "w") as f:
            f.write(json.dumps({"timestamp": now, "sid": sid, "duration": duration, "status": status}))
        print(f"[{now}] Marker written. Auto-recovery complete.")
    elif status == "failed" and duration == 0 and sip is None:
        print(f"[{now}] Still platform-blocked. Will retry next cron run.")
    else:
        print(f"[{now}] Unexpected result. Will retry next cron run.")

if __name__ == "__main__":
    main()
