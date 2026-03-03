#!/usr/bin/env python3
"""
make_call_v6.py — Hybrid: v5's working Calling API (dict payload) + v5_fixed's SWML (static_greeting)

Root cause of silence: AI was waiting for user to speak first on an outbound call.
Fix: static_greeting + wait_for_user=False + no answer verb before ai.

Root cause of v5_fixed not ringing: swml passed as JSON string instead of dict.
Fix: Pass swml as dict object (like v5 does).

Usage:
  python3 make_call_v6.py +16022950104
  python3 make_call_v6.py +16022950104 --discovery
"""
import sys
import os
import json
import time
import requests

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "signalwire.json")

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

CONFIG = load_config()

PROJECT_ID = CONFIG["project_id"]
AUTH_TOKEN = CONFIG["auth_token"]
SPACE_URL = CONFIG["space_url"]
FROM_NUMBER = CONFIG["phone_number"]  # +14806024668
SWAIG_URL = CONFIG["swaig_webhook_url"]

SWAIG_FUNCTIONS = [
    {
        "function": "save_contact",
        "web_hook_url": SWAIG_URL,
        "description": "Save IT contact information when obtained.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact full name"},
                "phone": {"type": "string", "description": "Direct phone number"},
                "account": {"type": "string", "description": "Organization name"}
            },
            "required": ["name"]
        }
    },
    {
        "function": "log_call",
        "web_hook_url": SWAIG_URL,
        "description": "Log call outcome. Always call this before ending.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "description": "Call outcome: interested, not_interested, callback_requested, wrong_person, no_answer"},
                "summary": {"type": "string", "description": "Brief one-sentence call summary"}
            },
            "required": ["outcome"]
        }
    }
]


def get_swml(agent_type="cold_caller"):
    """Build SWML with static_greeting so AI speaks first on outbound calls."""

    if agent_type == "discovery":
        prompt_text = (
            "You are Matt, a friendly technology advisor calling on behalf of Fortinet. "
            "This is a discovery call. You called them — introduce yourself immediately.\n\n"
            "Your goal: Find out who handles IT security at this organization.\n"
            "Be warm, grateful they picked up, and keep it under 60 seconds.\n"
            "If they give you a name and number, confirm it back, then call save_contact.\n"
            "Before ending, call log_call with the outcome."
        )
        greeting = (
            "Hey there! This is Matt from Fortinet. I know I'm calling out of the blue, "
            "so I really appreciate you picking up. Quick question — do you happen to know "
            "who handles IT security for your organization?"
        )
    else:
        prompt_text = (
            "You are Matt, a knowledgeable and professional solutions consultant calling "
            "on behalf of Fortinet. You specialize in helping IT leaders in education and "
            "local government modernize their security infrastructure.\n\n"
            "IMPORTANT: This is an OUTBOUND call. You called them.\n\n"
            "CONVERSATION FLOW:\n"
            "1. After your greeting, confirm they have a minute\n"
            "2. Ask: What happens to your phones when the internet goes down?\n"
            "3. Based on their answer, briefly mention how Fortinet helps\n"
            "4. Offer a 15-minute follow-up call with their local Fortinet partner\n"
            "5. If interested, collect preferred contact method\n\n"
            "GUIDELINES:\n"
            "- Keep sentences short and conversational\n"
            "- If they're busy, offer to call back\n"
            "- Keep the call under 3 minutes\n"
            "- Call log_call before ending"
        )
        greeting = (
            "Hi there! This is Matt calling from Fortinet. "
            "I'm reaching out to IT leaders in your area about cybersecurity solutions. "
            "Do you have just a minute?"
        )

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "prompt": {
                            "text": prompt_text,
                            "confidence": 0.6,
                            "temperature": 0.3
                        },
                        "post_prompt": {
                            "text": "Call log_call with the outcome before ending."
                        },
                        "params": {
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "start_paused": False,
                            "static_greeting": greeting,
                            "outbound_attention_timeout": 30000,
                            "end_of_speech_timeout": 2000,
                            "inactivity_timeout": 30000
                        },
                        "voice": "amazon.Matthew:standard:en-US",
                        "engine": {
                            "asr": {"engine": "deepgram", "model": "nova-3"},
                            "tts": {"engine": "amazon", "voice": "Matthew"}
                        },
                        "languages": [
                            {
                                "code": "en-US",
                                "provider": "amazon",
                                "voice": "amazon.Matthew:standard:en-US"
                            }
                        ],
                        "SWAIG": {
                            "functions": SWAIG_FUNCTIONS
                        },
                        "barge": {
                            "enable": True,
                            "mode": ["complete", "partial"]
                        }
                    }
                }
            ]
        }
    }


def make_call(to_number, agent_type="cold_caller"):
    """Place call via Calling API with SWML as dict (not string)."""
    swml = get_swml(agent_type)

    api_url = f"https://{SPACE_URL}/api/calling/calls"

    # KEY: pass swml as dict, NOT json.dumps string
    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "caller_id": FROM_NUMBER,
            "swml": swml
        }
    }

    print(f"\n{'='*60}")
    print(f"OUTBOUND AI CALL v6 (Calling API + Dict SWML + Static Greeting)")
    print(f"{'='*60}")
    print(f"  From:    {FROM_NUMBER}")
    print(f"  To:      {to_number}")
    print(f"  Agent:   {agent_type}")
    print(f"  Greeting: {swml['sections']['main'][0]['ai']['params']['static_greeting'][:60]}...")
    print(f"{'='*60}\n")

    try:
        resp = requests.post(
            api_url,
            auth=(PROJECT_ID, AUTH_TOKEN),
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=20
        )
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Request failed: {e}")
        return None

    if resp.status_code not in [200, 201]:
        print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
        return None

    data = resp.json()
    call_id = data.get("id", "unknown")
    print(f"  ✅ Call queued: {call_id}")
    print(f"  Status: {data.get('status')}")
    print(f"  Source: {data.get('source')}")
    print(f"  Type: {data.get('type')}")

    # Wait and poll via Compatibility API
    print(f"\n  Waiting for call to connect...")
    compat_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json?PageSize=1"

    for i in range(12):
        time.sleep(5)
        try:
            r = requests.get(compat_url, auth=(PROJECT_ID, AUTH_TOKEN), timeout=10)
            if r.ok:
                calls = r.json().get("calls", [])
                if calls:
                    latest = calls[0]
                    status = latest.get("status", "?")
                    duration = latest.get("duration", 0)
                    sip = latest.get("sip_result_code", "N/A")
                    print(f"  [{i+1}/12] Latest call: {status} | {duration}s | SIP: {sip}")

                    if status in ("completed", "failed", "busy", "no-answer", "canceled"):
                        if status == "completed" and int(duration or 0) > 5:
                            print(f"\n  🎉 Call completed ({duration}s) — AI should have spoken!")
                        elif status == "completed":
                            print(f"\n  ⚠️  Short call ({duration}s) — AI may not have had time to speak")
                        elif status == "failed":
                            print(f"\n  ❌ Call failed (SIP {sip})")
                        return latest
        except:
            pass

    print("  Polling timed out — check SignalWire dashboard")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 make_call_v6.py <phone-number>")
        print("  python3 make_call_v6.py <phone-number> --discovery")
        sys.exit(1)

    phone = sys.argv[1].replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"

    agent_type = "cold_caller"
    if len(sys.argv) > 2 and sys.argv[2] == "--discovery":
        agent_type = "discovery"

    make_call(phone, agent_type)
