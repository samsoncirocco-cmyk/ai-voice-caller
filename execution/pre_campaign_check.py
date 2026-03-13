#!/usr/bin/env python3
"""
pre_campaign_check.py — Safety check before running any campaign batch.
Verifies hooks-server is live and accepting POST requests.
Exits non-zero if unhealthy so campaign_runner can abort.
"""
import sys
import requests

WEBHOOK_URL = "https://hooks.6eyes.dev/voice-caller/post-call"
HEALTH_URL  = "https://hooks.6eyes.dev/health"

def check():
    # 1. Health endpoint
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code != 200:
            print(f"[PRE-CHECK FAIL] hooks.6eyes.dev health check returned {r.status_code}")
            return False
    except Exception as e:
        print(f"[PRE-CHECK FAIL] hooks.6eyes.dev unreachable: {e}")
        return False

    # 2. POST to webhook with a dummy ping (server ignores unknown call_ids)
    try:
        r = requests.post(WEBHOOK_URL, json={"call_id": "pre-check-ping", "ping": True}, timeout=5)
        if r.status_code not in (200, 400):
            print(f"[PRE-CHECK FAIL] Webhook POST returned unexpected {r.status_code}")
            return False
    except Exception as e:
        print(f"[PRE-CHECK FAIL] Webhook POST failed: {e}")
        return False

    print("[PRE-CHECK OK] hooks-server is live and accepting callbacks")
    return True

if __name__ == "__main__":
    ok = check()
    sys.exit(0 if ok else 1)
