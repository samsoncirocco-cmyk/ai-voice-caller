#!/usr/bin/env python3
"""
make_call_v8.py — Flexible inline SWML caller. Supports voice/prompt/from CLI args.

Usage:
  python3 make_call_v8.py                                           # Defaults
  python3 make_call_v8.py +16025551234                              # Custom number
  python3 make_call_v8.py +16025551234 --voice openai.onyx          # Custom voice
  python3 make_call_v8.py +16025551234 --prompt prompts/cold_outreach.txt
  python3 make_call_v8.py +16025551234 --from +14806024668          # Second number

Voices (best → most robotic):
  elevenlabs.thomas     — most human, needs ElevenLabs linked
  openai.onyx           — deep male, very natural (recommended)
  openai.echo           — lighter male, natural
  gcloud.en-US-Casual-K — Google casual male
  rime.marsh:arcana     — newer engine, natural
  amazon.Matthew-Neural — better Polly (current default, avoid)
"""

import sys
import json
import base64
import os
import argparse
import requests

# === Credentials ===
_cfg_path = os.path.join(os.path.dirname(__file__), "config", "signalwire.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

SPACE_URL  = _cfg["space_url"]
PROJECT_ID = _cfg["project_id"]
AUTH_TOKEN = _cfg["auth_token"]

DEFAULT_FROM   = _cfg.get("phone_number", "+14806024668")  # Load from config, not hardcoded
DEFAULT_TO     = "+16022950104"
DEFAULT_VOICE  = "openai.onyx"
DEFAULT_PROMPT = "prompts/paul.txt"

POST_PROMPT = (
    "Summarize the call in this exact format:\n"
    "- Call outcome: [Connected / Left Voicemail / No Answer / Wrong Number / Not Interested / Meeting Booked]\n"
    "- Spoke with: [name or 'unknown']\n"
    "- Role: [title/role]\n"
    "- Organization: [org name]\n"
    "- Current vendor: [if mentioned, else 'unknown']\n"
    "- Current setup: [what they said about their IT/security environment]\n"
    "- Pain points: [frustrations or challenges mentioned]\n"
    "- Interest level: [1-5]\n"
    "- Follow-up: [what was agreed, or 'none']\n"
    "- Meeting booked: [yes/no — if yes, include day and time]\n"
    "- Contact email: [if collected, else 'none']\n"
    "- Contact direct phone: [if collected, else 'none']\n"
    "- Notes: [anything else useful]"
)


def load_prompt(path):
    full_path = os.path.join(os.path.dirname(__file__), path)
    return open(full_path).read().strip()


DEFAULT_GREETING = (
    "Hi there! This is Paul calling from Fortinet. "
    "I'm reaching out to IT leaders in your area about network security. "
    "Do you have just a minute?"
)


def build_swml(prompt_text, voice, static_greeting=None):
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                # answer verb REQUIRED before ai — establishes audio path
                {"answer": {}},
                {
                    "ai": {
                        "languages": [
                            {
                                # Note: "speed" field is INVALID and causes silent AI block failure
                                "name": "English",
                                "code": "en-US",
                                "voice": voice
                            }
                        ],
                        "prompt": {
                            "text": prompt_text,
                            "temperature": 0.8
                        },
                        "post_prompt": {
                            "text": POST_PROMPT
                        },
                        "post_prompt_url": "https://hooks.6eyes.dev/voice-caller/post-call",
                        "params": {
                            # FIX 2026-03-03: wait_for_user defaults to True on outbound calls.
                            # Without these params, agent waits for remote party to speak → silence.
                            "ai_model": "gpt-4.1-nano",
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "static_greeting": static_greeting or DEFAULT_GREETING,
                            # FIX 2026-03-09: Reduced from 30s → 10s.
                            # 30s caused AI to loop on open voicemail lines for 68+ minutes.
                            "attention_timeout": 10000,
                            "inactivity_timeout": 10000,
                            "end_of_speech_timeout": 2000,
                            # asr_engine format: "provider:model" — colon-separated string
                            # NOT a nested engine.asr object (that was causing silent AI failure)
                            "asr_engine": "deepgram:nova-3"
                        },
                        # FIX 2026-03-09: SWAIG end_call function.
                        # Prompts tell the AI to "hang up immediately after voicemail" but
                        # without this function the AI has NO mechanism to actually hang up.
                        # This was the root cause of 68-minute/$47 runaway calls.
                        "SWAIG": {
                            "functions": [
                                {
                                    "function": "end_call",
                                    "purpose": "Hang up the call immediately. MUST be called after leaving a voicemail message. Also call if no one answers after greeting, or call is clearly done.",
                                    "argument": {
                                        "type": "object",
                                        "properties": {
                                            "reason": {
                                                "type": "string",
                                                "description": "Why the call is ending: voicemail_left, no_answer, not_interested, meeting_booked, wrong_number"
                                            }
                                        },
                                        "required": ["reason"]
                                    },
                                    "data_map": {
                                        "expressions": [
                                            {
                                                "string": "%{args.reason}",
                                                "pattern": ".*",
                                                "output": {
                                                    "response": "Call ended.",
                                                    "action": [{"SWML": {"version": "1.0.0", "sections": {"main": [{"hangup": {}}]}}}]
                                                }
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }


def check_signalwire_balance():
    """Check SignalWire balance before placing call. Returns balance in dollars or None on error."""
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }
    try:
        # SignalWire balance endpoint
        url = f"https://{SPACE_URL}/api/relay/rest/accounts/{PROJECT_ID}"
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            balance = data.get("balance", 0)
            return float(balance)
    except Exception as e:
        print(f"⚠️  Could not check balance: {e}")
    return None


def make_call(to_number, from_number, voice, prompt_path, static_greeting=None):
    # BUDGET GUARD: Check balance before placing call
    balance = check_signalwire_balance()
    if balance is not None and balance < 2.0:
        print(f"\n❌ BUDGET GUARD: SignalWire balance (${balance:.2f}) is below $2. Call blocked.")
        print("   Top up account or get explicit approval from Samson to proceed.")
        return
    elif balance is not None:
        print(f"💰 Balance: ${balance:.2f}")
    
    prompt_text = load_prompt(prompt_path)
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()
    swml = build_swml(prompt_text, voice, static_greeting=static_greeting)

    payload = {
        "command": "dial",
        "params": {
            "from": from_number,
            "to": to_number,
            "max_duration": 90,       # Hard cap: 90 seconds. Prevents runaway calls.
            # FIX 2026-03-09: AMD — detect voicemail vs. live human.
            # "DetectMessageEnd" waits for the beep, then lets the AI deliver voicemail script.
            # Without this, the AI had no idea it was talking to a voicemail system.
            "machine_detection": "DetectMessageEnd",
            "machine_detection_timeout": 30,
            "machine_detection_speech_end_threshold": 1200,
            "machine_detection_silence_timeout": 3000,
            "swml": swml
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }

    url = f"https://{SPACE_URL}/api/calling/calls"

    print(f"\n📞 {from_number} → {to_number}")
    print(f"🎙  Voice:  {voice}")
    print(f"📄 Prompt: {prompt_path}\n")

    response = requests.post(url, json=payload, headers=headers)

    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

    if response.status_code == 200:
        print("\n✅ Call initiated.")
    else:
        print(f"\n❌ Call failed ({response.status_code}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("to", nargs="?", default=DEFAULT_TO)
    parser.add_argument("--voice",  default=DEFAULT_VOICE)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--from",   dest="from_number", default=DEFAULT_FROM)
    args = parser.parse_args()

    make_call(args.to, args.from_number, args.voice, args.prompt)
