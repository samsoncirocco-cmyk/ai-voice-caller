#!/usr/bin/env python3
"""
make_call_v8.py — Clean inline SWML, credentials from config, prompt from file.

Usage:
  python3 make_call_v8.py                  # Call Samson's cell (default)
  python3 make_call_v8.py +16025551234     # Call any number

To edit Paul's script: open prompts/paul.txt — no code changes needed.
"""

import sys
import json
import base64
import os
import requests

# === Credentials (from config/signalwire.json — gitignored, never hardcode) ===
_cfg_path = os.path.join(os.path.dirname(__file__), "config", "signalwire.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

SPACE_URL  = _cfg["space_url"]
PROJECT_ID = _cfg["project_id"]
AUTH_TOKEN = _cfg["auth_token"]

FROM_NUMBER = "+16028985026"
DEFAULT_TO  = "+16022950104"  # Samson's cell

# === Prompt (edit prompts/paul.txt to change Paul's script — no code needed) ===
_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "paul.txt")
PAUL_PROMPT = open(_prompt_path).read().strip()

POST_PROMPT = (
    "Summarize the call in this exact format:\n"
    "- Spoke with: [name or 'unknown']\n"
    "- Role: [title/role]\n"
    "- Organization: [school district or municipality name]\n"
    "- Current setup: [what they said about their current IT/security setup]\n"
    "- Pain points: [any frustrations or challenges mentioned]\n"
    "- Interest level: [1-5]\n"
    "- Follow-up: [what was agreed, or 'none']\n"
    "- Notes: [anything else useful]"
)


def build_swml():
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "prompt": {
                            "text": PAUL_PROMPT,
                            "temperature": 0.8
                        },
                        "post_prompt": {
                            "text": POST_PROMPT
                        },
                        "post_prompt_url": "https://hooks.6eyes.dev/voice-caller/post-call",
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
    response = requests.post(url, json=payload, headers=headers)

    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

    if response.status_code == 200:
        print("\n✅ Call initiated. Prompt loaded from prompts/paul.txt")
    else:
        print(f"\n❌ Call failed ({response.status_code}). Check credentials.")


if __name__ == "__main__":
    to = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TO
    make_call(to)
