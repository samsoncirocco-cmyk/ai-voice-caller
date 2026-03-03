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
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "start_paused": False,
                            "static_greeting": static_greeting or DEFAULT_GREETING,
                            "outbound_attention_timeout": 30000
                        },
                        "engine": {
                            "asr": {"engine": "deepgram", "model": "nova-3"}
                        }
                    }
                }
            ]
        }
    }


def make_call(to_number, from_number, voice, prompt_path, static_greeting=None):
    prompt_text = load_prompt(prompt_path)
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()
    swml = build_swml(prompt_text, voice, static_greeting=static_greeting)

    payload = {
        "command": "dial",
        "params": {
            "from": from_number,
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
