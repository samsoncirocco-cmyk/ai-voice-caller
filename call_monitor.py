#!/usr/bin/env python3
"""
Call Monitor - Checks if SignalWire number is unblocked and runs health probes.

Usage:
  python3 call_monitor.py              # One-time health check
  python3 call_monitor.py --watch      # Poll every 5 minutes until unblocked
  python3 call_monitor.py --probe      # Make a single test call to check
"""
import sys
import json
import time
from datetime import datetime, timezone

import requests

# ─── Config ────────────────────────────────────────────────

PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"
SPACE = "6eyes.signalwire.com"
FROM = "+16028985026"
PROBE_TO = "+16022950104"
AGENT_ID = "e2c8a606-24ce-4392-a7a8-c11bd79a7a45"

AUTH = (PROJECT_ID, AUTH_TOKEN)
CALLS_URL = f"https://{SPACE}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"


def get_recent_calls(count=10):
    """Fetch recent calls."""
    r = requests.get(f"{CALLS_URL}?PageSize={count}", auth=AUTH, timeout=10)
    return r.json().get("calls", [])


def analyze_health():
    """Analyze recent call patterns."""
    calls = get_recent_calls(15)
    now = datetime.now(timezone.utc)

    platform_blocks = 0
    carrier_blocks = 0
    successes = 0
    last_success_time = None

    for c in calls:
        status = c["status"]
        dur = c["duration"]
        sip = c.get("sip_result_code")

        if status == "completed" and dur > 0:
            successes += 1
            if not last_success_time:
                last_success_time = c["date_created"]
        elif status == "failed" and dur == 0 and sip is None:
            platform_blocks += 1
        elif status == "failed" and sip == 500:
            carrier_blocks += 1

    # Determine health status
    if platform_blocks >= 5:
        health = "BLOCKED"
        emoji = "[X]"
    elif platform_blocks >= 3:
        health = "DEGRADED"
        emoji = "[!]"
    elif carrier_blocks >= 3:
        health = "CARRIER_ISSUES"
        emoji = "[~]"
    else:
        health = "HEALTHY"
        emoji = "[OK]"

    return {
        "health": health,
        "emoji": emoji,
        "platform_blocks": platform_blocks,
        "carrier_blocks": carrier_blocks,
        "successes": successes,
        "last_success": last_success_time,
        "total_checked": len(calls),
    }


def print_health(h):
    """Print health report."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"\n  [{ts}] Number Health: {h['emoji']} {h['health']}")
    print(f"  ├── Platform blocks: {h['platform_blocks']}/{h['total_checked']}")
    print(f"  ├── Carrier blocks:  {h['carrier_blocks']}/{h['total_checked']}")
    print(f"  ├── Successes:       {h['successes']}/{h['total_checked']}")
    print(f"  └── Last success:    {h['last_success'] or 'none recent'}")


def probe_call():
    """Make a single test call to check if unblocked."""
    print(f"  Sending probe call to {PROBE_TO}...")
    agent_url = f"https://{SPACE}/api/ai/agent/{AGENT_ID}"

    resp = requests.post(CALLS_URL, auth=AUTH, data={
        "From": FROM,
        "To": PROBE_TO,
        "Url": agent_url,
    }, timeout=15)

    if resp.status_code not in [200, 201]:
        print(f"  Probe failed to queue: HTTP {resp.status_code}")
        return False

    sid = resp.json().get("sid")
    print(f"  Probe SID: {sid}")
    print(f"  Waiting 25s...")
    time.sleep(25)

    check = requests.get(
        f"https://{SPACE}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls/{sid}.json",
        auth=AUTH, timeout=10,
    )
    cd = check.json()
    status = cd.get("status")
    dur = cd.get("duration", 0)
    sip = cd.get("sip_result_code")

    if status == "failed" and dur == 0 and sip is None:
        print(f"  Probe result: STILL BLOCKED")
        return False
    elif status in ("completed", "in-progress", "ringing"):
        print(f"  Probe result: UNBLOCKED! Duration={dur}s")
        return True
    else:
        print(f"  Probe result: {status}, dur={dur}s, sip={sip}")
        return status != "failed"


def watch_mode():
    """Poll every 5 minutes until unblocked."""
    print("Watch mode: checking every 5 minutes until unblocked...")
    print("Press Ctrl+C to stop.\n")

    while True:
        h = analyze_health()
        print_health(h)

        if h["health"] == "HEALTHY":
            print("\n  Number appears healthy! Run --probe to verify with a real call.")
            break

        print(f"  Next check in 5 minutes...")
        try:
            time.sleep(300)
        except KeyboardInterrupt:
            print("\n  Stopped.")
            break


# ─── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"\n{'='*50}")
    print(f"  SignalWire Number Health Monitor")
    print(f"  Number: {FROM}")
    print(f"{'='*50}")

    if cmd == "--watch":
        watch_mode()
    elif cmd == "--probe":
        h = analyze_health()
        print_health(h)
        if h["health"] == "BLOCKED":
            print("\n  Number is blocked. Probe would waste a call attempt.")
            print("  Use --watch to wait for recovery first.")
        else:
            probe_call()
    else:
        h = analyze_health()
        print_health(h)
        if h["health"] != "HEALTHY":
            print(f"\n  Recommendation: wait, then run --probe to verify")
