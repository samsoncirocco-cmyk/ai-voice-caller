#!/usr/bin/env python3
"""
make_call_v8.py — Clean inline SWML, no relay-bin, no SWAIG webhooks.

Root cause diagnosis (March 3, 2026):
  - The referenced AI agent (f2c41814...) returned 404 — it no longer exists
  - v3-v7 all had SWAIG webhook pointing to GCF function that was never deployed
    → SignalWire silently fails to initialize AI stream when SWAIG webhook is unreachable
  - Fix: inline SWML with prompt directly in call body, zero external dependencies

Usage:
  python3 make_call_v8.py                          # Call Samson's cell (default)
  python3 make_call_v8.py +16025551234             # Call any number

Once this works:
  - Add SWAIG functions back one at a time, verifying each works
  - Build campaign runner on top of this pattern
"""

import sys
import json
import base64
import requests

# === Credentials ===
SPACE_URL   = "6eyes.signalwire.com"
PROJECT_ID  = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
AUTH_TOKEN  = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"

FROM_NUMBER = "+16028985026"
DEFAULT_TO  = "+16022950104"  # Samson's cell

# === Inline SWML (no relay-bin, no agent_id, no SWAIG) ===
def build_swml():
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "prompt": {
                            "text": (
                                "You are Paul, calling on behalf of Samson at Fortinet. "
                                "You are reaching out to IT directors at school districts and municipalities "
                                "in South Dakota and Nebraska about network security infrastructure. "
                                "Your goal is to identify the right IT contact and schedule a brief meeting. "
                                "Be professional, friendly, and concise. "
                                "If asked, you are not an AI — you are Paul, a member of Samson's outreach team."
                            ),
                            "temperature": 0.7
                        },
                        "post_prompt": {
                            "text": (
                                "Summarize: who you spoke with, their role, "
                                "interest level (1-5), and any follow-up agreed to."
                            )
                        },
                        "params": {
                            "direction": "outbound"
                        }
                    }
                }
            ]
        }
    }


def make_call(to_number):
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()
    swml = build_swml()

    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "swml": swml
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }

    url = f"https://{SPACE_URL}/api/calling/calls"

    print(f"\nCalling {to_number} from {FROM_NUMBER}...")
    print(f"SWML (inline, no external deps):\n{json.dumps(swml, indent=2)}\n")

    response = requests.post(url, json=payload, headers=headers)

    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

    if response.status_code == 200:
        print("\n✅ Call initiated. Pick up — Paul should introduce himself and start talking.")
        print("If still silent: check SignalWire call logs at https://6eyes.signalwire.com")
    else:
        print(f"\n❌ Call failed ({response.status_code}). Check credentials and number ownership.")


if __name__ == "__main__":
    to = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TO
    make_call(to)
