#!/usr/bin/env python3
"""
Make outbound calls with rate-limit protection and SWAIG functions.

Usage:
  python3 make_call_v4.py <phone-number>
  python3 make_call_v4.py --check       # Check if number is unblocked
  python3 make_call_v4.py --status      # Show call stats and rate limit status

Rate-limit protection:
  - Minimum 30s between calls
  - Max 20 calls/hour, 100 calls/day
  - 5-minute cooldown after 3 consecutive failures
  - Tracks state in Firestore call_rate collection
"""
import sys
import os
import json
import time
from datetime import datetime, timedelta

import requests
from google.cloud import firestore

# ─── Configuration ──────────────────────────────────────────

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "signalwire.json")

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

CONFIG = load_config()

PROJECT_ID = CONFIG["project_id"]
AUTH_TOKEN = CONFIG["auth_token"]
SPACE_URL = CONFIG["space_url"]
FROM_NUMBER = CONFIG["phone_number"]
AGENT_ID = CONFIG["ai_agent"]["agent_id"]

RATE_LIMITS = CONFIG.get("rate_limits", {})
MIN_INTERVAL = RATE_LIMITS.get("min_interval_seconds", 30)
MAX_PER_HOUR = RATE_LIMITS.get("max_calls_per_hour", 20)
MAX_PER_DAY = RATE_LIMITS.get("max_calls_per_day", 100)
COOLDOWN_ON_FAILURE = RATE_LIMITS.get("cooldown_on_failure_seconds", 300)
MAX_CONSECUTIVE_FAILURES = RATE_LIMITS.get("max_consecutive_failures", 3)

db = firestore.Client(project="tatt-pro")


# ─── Rate Limit Tracking ──────────────────────────────────────

def get_rate_state():
    """Get current rate limit state from Firestore."""
    doc = db.collection("call_rate").document("state").get()
    if doc.exists:
        return doc.to_dict()
    return {
        "last_call_time": None,
        "consecutive_failures": 0,
        "cooldown_until": None,
        "calls_today": 0,
        "calls_this_hour": 0,
        "today_date": None,
        "hour_start": None,
    }


def update_rate_state(updates):
    """Update rate limit state in Firestore."""
    db.collection("call_rate").document("state").set(updates, merge=True)


def check_rate_limits():
    """Check if we're allowed to make a call. Returns (allowed, reason)."""
    state = get_rate_state()
    now = datetime.utcnow()

    # Check cooldown
    cooldown_until = state.get("cooldown_until")
    if cooldown_until:
        if isinstance(cooldown_until, str):
            cooldown_until = datetime.fromisoformat(cooldown_until)
        if now < cooldown_until:
            remaining = (cooldown_until - now).seconds
            return False, f"In cooldown after {MAX_CONSECUTIVE_FAILURES} failures. {remaining}s remaining."

    # Check minimum interval
    last_call = state.get("last_call_time")
    if last_call:
        if isinstance(last_call, str):
            last_call = datetime.fromisoformat(last_call)
        elapsed = (now - last_call).total_seconds()
        if elapsed < MIN_INTERVAL:
            wait = int(MIN_INTERVAL - elapsed)
            return False, f"Too soon. Wait {wait}s (min interval: {MIN_INTERVAL}s)."

    # Check hourly limit
    hour_start = state.get("hour_start")
    calls_this_hour = state.get("calls_this_hour", 0)
    if hour_start:
        if isinstance(hour_start, str):
            hour_start = datetime.fromisoformat(hour_start)
        if (now - hour_start).total_seconds() < 3600:
            if calls_this_hour >= MAX_PER_HOUR:
                return False, f"Hourly limit reached ({MAX_PER_HOUR}/hr). Wait for next hour."
        else:
            calls_this_hour = 0  # Reset hour counter

    # Check daily limit
    today = now.strftime("%Y-%m-%d")
    calls_today = state.get("calls_today", 0)
    if state.get("today_date") != today:
        calls_today = 0  # New day, reset counter

    if calls_today >= MAX_PER_DAY:
        return False, f"Daily limit reached ({MAX_PER_DAY}/day). Try tomorrow."

    return True, "OK"


def record_call_attempt(success):
    """Record a call attempt for rate limiting."""
    now = datetime.utcnow()
    state = get_rate_state()
    today = now.strftime("%Y-%m-%d")

    # Reset counters if new day/hour
    if state.get("today_date") != today:
        calls_today = 1
    else:
        calls_today = state.get("calls_today", 0) + 1

    hour_start = state.get("hour_start")
    if hour_start:
        if isinstance(hour_start, str):
            hour_start = datetime.fromisoformat(hour_start)
        if (now - hour_start).total_seconds() >= 3600:
            calls_this_hour = 1
            hour_start = now
        else:
            calls_this_hour = state.get("calls_this_hour", 0) + 1
    else:
        calls_this_hour = 1
        hour_start = now

    updates = {
        "last_call_time": now.isoformat(),
        "calls_today": calls_today,
        "today_date": today,
        "calls_this_hour": calls_this_hour,
        "hour_start": hour_start.isoformat() if isinstance(hour_start, datetime) else hour_start,
    }

    if success:
        updates["consecutive_failures"] = 0
        updates["cooldown_until"] = None
    else:
        failures = state.get("consecutive_failures", 0) + 1
        updates["consecutive_failures"] = failures
        if failures >= MAX_CONSECUTIVE_FAILURES:
            cooldown_end = now + timedelta(seconds=COOLDOWN_ON_FAILURE)
            updates["cooldown_until"] = cooldown_end.isoformat()
            print(f"  [RATE LIMIT] {failures} consecutive failures. Cooldown until {cooldown_end.strftime('%H:%M:%S')} UTC")

    update_rate_state(updates)


# ─── Call Functions ────────────────────────────────────────────

def make_call(to_number):
    """Make outbound call with rate-limit protection."""

    # Check rate limits first
    allowed, reason = check_rate_limits()
    if not allowed:
        print(f"  [BLOCKED] {reason}")
        return None

    api_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"
    agent_url = f"https://{SPACE_URL}/api/ai/agent/{AGENT_ID}"

    payload = {
        "From": FROM_NUMBER,
        "To": to_number,
        "Url": agent_url,
    }

    print(f"  Calling {to_number} via agent {AGENT_ID[:12]}...")
    print(f"  Agent URL: {agent_url}")

    try:
        resp = requests.post(api_url, auth=(PROJECT_ID, AUTH_TOKEN), data=payload, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Request failed: {e}")
        record_call_attempt(success=False)
        return None

    if resp.status_code not in [200, 201]:
        print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
        record_call_attempt(success=False)
        return None

    data = resp.json()
    sid = data.get("sid")
    print(f"  SID: {sid}")
    print(f"  Status: {data.get('status')}")

    # Wait and check result
    print(f"  Waiting 20s to verify call connected...")
    time.sleep(20)

    check = requests.get(
        f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls/{sid}.json",
        auth=(PROJECT_ID, AUTH_TOKEN),
        timeout=10,
    )
    cd = check.json()
    status = cd.get("status", "unknown")
    duration = cd.get("duration", 0)
    sip = cd.get("sip_result_code")

    print(f"  Result: status={status}, duration={duration}s, sip={sip}")

    if status == "failed" and duration == 0 and sip is None:
        print(f"  [RATE LIMITED] Platform-level block detected (0 dur, no SIP)")
        record_call_attempt(success=False)
        return None
    elif status == "failed" and sip == 500:
        print(f"  [CARRIER BLOCK] SIP 500 - carrier rejected call")
        record_call_attempt(success=False)
        return None
    elif status in ("completed", "in-progress", "ringing", "queued"):
        record_call_attempt(success=True)
        return data
    else:
        record_call_attempt(success=False)
        return data


def check_number_health():
    """Test if the phone number is unblocked by checking recent call patterns."""
    print("Checking number health...")

    r = requests.get(
        f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json?PageSize=10",
        auth=(PROJECT_ID, AUTH_TOKEN),
        timeout=10,
    )
    calls = r.json().get("calls", [])

    recent_failures = 0
    last_success = None
    for c in calls:
        if c["status"] == "failed" and c["duration"] == 0 and c.get("sip_result_code") is None:
            recent_failures += 1
        elif c["status"] == "completed" and c["duration"] > 0:
            last_success = c["date_created"]
            break

    state = get_rate_state()
    cooldown = state.get("cooldown_until")

    print(f"\n  Phone: {FROM_NUMBER}")
    print(f"  Recent platform-block failures: {recent_failures}/10")
    print(f"  Last successful call: {last_success or 'none in recent history'}")
    print(f"  Consecutive failures: {state.get('consecutive_failures', 0)}")
    print(f"  Cooldown: {cooldown or 'none'}")
    print(f"  Calls today: {state.get('calls_today', 0)}/{MAX_PER_DAY}")
    print(f"  Calls this hour: {state.get('calls_this_hour', 0)}/{MAX_PER_HOUR}")

    if recent_failures >= 5:
        print(f"\n  [WARNING] Number appears rate-limited. Wait before calling.")
    elif recent_failures >= 3:
        print(f"\n  [CAUTION] Some recent failures. Proceed carefully.")
    else:
        print(f"\n  [OK] Number appears healthy.")


def show_status():
    """Show rate limit state and recent call stats."""
    check_number_health()
    state = get_rate_state()
    allowed, reason = check_rate_limits()
    print(f"\n  Can make call now: {'YES' if allowed else 'NO'}")
    if not allowed:
        print(f"  Reason: {reason}")


# ─── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 make_call_v4.py <phone-number>  # Make a call")
        print("  python3 make_call_v4.py --check          # Check number health")
        print("  python3 make_call_v4.py --status          # Show rate limit status")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--check":
        check_number_health()
        sys.exit(0)

    if arg == "--status":
        show_status()
        sys.exit(0)

    # Phone number normalization
    phone = arg.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"

    print(f"\n{'='*60}")
    print(f"OUTBOUND CALL (v4 - Rate Limited + SWAIG)")
    print(f"{'='*60}")
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {phone}")
    print(f"  Agent: {AGENT_ID}")
    print(f"  SWAIG: save_contact, log_call")
    print(f"{'='*60}\n")

    result = make_call(phone)

    if result:
        print(f"\n{'='*60}")
        print(f"  CALL PLACED - ANSWER YOUR PHONE!")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print(f"  CALL FAILED - check --status for details")
        print(f"{'='*60}")
