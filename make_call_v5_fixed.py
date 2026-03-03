"""
make_call_v5.py — Outbound AI Call Script (Fixed)

ROOT CAUSE FIX:
- Old approach: Compatibility API Url=/api/ai/agent/{id} or no Url
  → Compatibility API expects cXML (XML), not a raw agent endpoint → SIP 500 or silence
- New approach: Calling API with inline SWML containing the 'ai' method
  → AI speaks first with static_greeting, SWAIG functions fire correctly

Uses the Calling API (/api/calling/calls) with inline SWML, NOT the Compatibility API.
The Compatibility API only supports cXML (XML) responses, which don't have an AI verb.
The Calling API natively supports SWML with the 'ai' method for AI agent conversations.

Usage:
  python make_call_v5.py --to +16022950104
  python make_call_v5.py --to +16022950104 --agent discovery-caller
  python make_call_v5.py --to +16022950104 --from-number +14806024668
"""

import argparse
import json
import sys
import time

import requests

# === SignalWire Credentials ===
SW_SPACE = "6eyes.signalwire.com"
SW_PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
SW_AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"

# === Phone Numbers ===
DEFAULT_FROM = "+14806024668"  # 480 number (clean, not rate-limited)
# +16028985026 is DEAD — 10/10 platform blocks, do not use

# === SWAIG Webhook ===
SWAIG_WEBHOOK = "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook"

# === Calling API Endpoint (supports inline SWML) ===
CALLS_URL = f"https://{SW_SPACE}/api/calling/calls"

# === Compatibility API (for polling call status only) ===
COMPAT_CALLS_URL = f"https://{SW_SPACE}/api/laml/2010-04-01/Accounts/{SW_PROJECT_ID}/Calls"

# === Agent Configurations ===
AGENTS = {
    "cold-caller": {
        "name": "Fortinet SLED Cold Caller v1",
        "voice": "amazon.Matthew:standard:en-US",
        "prompt": (
            "You are Matt, a friendly and professional technology solutions advisor "
            "calling on behalf of Fortinet. You're reaching out to state, local, and "
            "education (SLED) IT leaders in Arizona about cybersecurity solutions.\n\n"
            "IMPORTANT: This is an OUTBOUND call. You called them. Introduce yourself "
            "immediately and state your purpose clearly.\n\n"
            "Your goals:\n"
            "1. Introduce yourself and Fortinet briefly\n"
            "2. Ask about their current cybersecurity challenges\n"
            "3. Gauge interest in a follow-up meeting with their Fortinet account team\n"
            "4. If interested, collect their preferred contact method and schedule a callback\n"
            "5. Be respectful of their time — if they're busy, offer to call back\n\n"
            "Keep responses concise (2-3 sentences max). Be warm, not pushy.\n"
            "If they ask you to stop calling or aren't interested, thank them and end the call.\n"
            "Use save_contact for contact info, log_call at end, score_lead for qualified leads, "
            "schedule_callback if they want a follow-up call, send_info_email if they want info emailed."
        ),
        "static_greeting": (
            "Hi there! This is Matt calling from Fortinet. "
            "I'm reaching out to IT leaders in Arizona about cybersecurity solutions. "
            "Do you have just a minute?"
        ),
    },
    "discovery-caller": {
        "name": "Discovery Caller",
        "voice": "amazon.Matthew:standard:en-US",
        "prompt": (
            "You are Matt, a technology solutions advisor calling on behalf of Fortinet. "
            "This is a discovery call to learn about the organization's IT infrastructure "
            "and cybersecurity posture.\n\n"
            "IMPORTANT: This is an OUTBOUND call. You called them.\n\n"
            "Your goals:\n"
            "1. Introduce yourself briefly\n"
            "2. Ask about their current network security setup\n"
            "3. Understand their biggest IT challenges\n"
            "4. Determine if there's an opportunity for Fortinet solutions\n"
            "5. If interested, schedule a deeper technical discussion\n\n"
            "Keep responses concise. Be consultative, not salesy.\n"
            "Use save_contact, log_call, score_lead, schedule_callback, send_info_email as needed."
        ),
        "static_greeting": (
            "Hi! This is Matt with Fortinet. I'm reaching out to learn a bit about "
            "your organization's cybersecurity setup. Is now an okay time for a quick chat?"
        ),
    },
}

# SWAIG function definitions
SWAIG_FUNCTIONS = [
    {
        "function": "save_contact",
        "description": "Save or update contact information for the person on the call",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact full name"},
                "email": {"type": "string", "description": "Contact email"},
                "phone": {"type": "string", "description": "Contact phone number"},
                "title": {"type": "string", "description": "Job title"},
                "organization": {"type": "string", "description": "Organization name"},
            },
        },
        "web_hook_url": SWAIG_WEBHOOK,
    },
    {
        "function": "log_call",
        "description": "Log the call outcome and summary at the end of the conversation",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "description": "Call outcome: interested, not_interested, callback, no_answer, busy, wrong_number"},
                "summary": {"type": "string", "description": "Brief summary of the conversation"},
                "duration_estimate": {"type": "string", "description": "Estimated call duration"},
            },
        },
        "web_hook_url": SWAIG_WEBHOOK,
    },
    {
        "function": "score_lead",
        "description": "Score the lead based on interest level and fit",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "description": "Lead score 1-10"},
                "reason": {"type": "string", "description": "Reason for the score"},
                "qualified": {"type": "boolean", "description": "Whether lead is qualified for follow-up"},
            },
        },
        "web_hook_url": SWAIG_WEBHOOK,
    },
    {
        "function": "schedule_callback",
        "description": "Schedule a callback at a specific date and time",
        "parameters": {
            "type": "object",
            "properties": {
                "callback_date": {"type": "string", "description": "Preferred callback date"},
                "callback_time": {"type": "string", "description": "Preferred callback time"},
                "notes": {"type": "string", "description": "Notes for the callback"},
            },
        },
        "web_hook_url": SWAIG_WEBHOOK,
    },
    {
        "function": "send_info_email",
        "description": "Queue an info email to be sent to the contact",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address to send to"},
                "topic": {"type": "string", "description": "What info they want"},
            },
        },
        "web_hook_url": SWAIG_WEBHOOK,
    },
]


def build_swml(agent_key="cold-caller"):
    """Build SWML document for the specified agent."""
    agent = AGENTS.get(agent_key, AGENTS["cold-caller"])

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "prompt": {
                            "text": agent["prompt"],
                        },
                        "params": {
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "start_paused": False,
                            "static_greeting": agent["static_greeting"],
                            "outbound_attention_timeout": 30000,
                        },
                        "voice": agent["voice"],
                        "engine": {
                            "asr": {"engine": "deepgram", "model": "nova-3"},
                            "tts": {"engine": "amazon", "voice": "Matthew"},
                        },
                        "SWAIG": {
                            "functions": SWAIG_FUNCTIONS,
                        },
                        "barge": {
                            "enable": True,
                            "mode": ["complete", "partial"],
                        },
                    }
                }
            ]
        },
    }


def make_call(to_number, from_number=DEFAULT_FROM, agent="cold-caller"):
    """
    Place an outbound AI call using the Calling API with inline SWML.

    The Calling API (/api/calling/calls) supports inline SWML via the 'swml'
    parameter, which allows us to embed the full AI agent configuration
    directly in the call request.
    """
    swml = build_swml(agent)
    swml_str = json.dumps(swml)

    print(f"Placing call via Calling API with inline SWML:")
    print(f"  From: {from_number}")
    print(f"  To:   {to_number}")
    print(f"  Agent: {agent}")
    print()

    payload = {
        "command": "dial",
        "params": {
            "from": from_number,
            "to": to_number,
            "caller_id": from_number,
            "swml": swml_str,
        },
    }

    try:
        resp = requests.post(
            CALLS_URL,
            json=payload,
            auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
            timeout=30,
        )

        if resp.status_code in (200, 201):
            call_data = resp.json()
            call_id = call_data.get("id", call_data.get("sid", "unknown"))
            print(f"Call placed successfully!")
            print(f"  Call ID: {call_id}")
            print(f"  Response: {json.dumps(call_data, indent=2)}")
            print()

            # Poll for status via Compatibility API
            poll_call_status(call_id)
            return call_data
        else:
            print(f"ERROR: Call failed with status {resp.status_code}")
            print(f"  Response: {resp.text}")

            # If Calling API fails, fall back to Compatibility API with SWML URL
            print("\nFalling back to Compatibility API with SWML GCF endpoint...")
            return make_call_compat_fallback(to_number, from_number, agent)

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed: {e}")
        return None


def make_call_compat_fallback(to_number, from_number, agent):
    """
    Fallback: Use Compatibility API with the GCF SWML endpoint.
    The GCF returns SWML JSON — if SignalWire accepts it, great.
    If not (SIP 500), then only the Calling API approach works.
    """
    swml_url = f"https://us-central1-tatt-pro.cloudfunctions.net/swmlOutbound?agent={agent}"
    compat_url = f"{COMPAT_CALLS_URL}.json"

    print(f"  Fallback SWML URL: {swml_url}")

    payload = {
        "From": from_number,
        "To": to_number,
        "Url": swml_url,
    }

    try:
        resp = requests.post(
            compat_url,
            data=payload,
            auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
            timeout=30,
        )

        if resp.status_code in (200, 201):
            call_data = resp.json()
            call_sid = call_data.get("sid", "unknown")
            print(f"Fallback call placed! SID: {call_sid}")
            poll_call_status(call_sid)
            return call_data
        else:
            print(f"Fallback also failed: {resp.status_code}")
            print(f"  Response: {resp.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Fallback request failed: {e}")
        return None


def poll_call_status(call_id, max_polls=12, interval=5):
    """Poll call status until completion or timeout."""
    # Try Compatibility API for status polling
    status_url = f"{COMPAT_CALLS_URL}/{call_id}.json"

    print("Polling call status...")
    for i in range(max_polls):
        time.sleep(interval)
        try:
            resp = requests.get(
                status_url,
                auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")
                duration = data.get("duration", "0")
                print(f"  [{i+1}/{max_polls}] Status: {status}, Duration: {duration}s")

                if status in ("completed", "failed", "busy", "no-answer", "canceled"):
                    print(f"\nCall ended: {status} (duration: {duration}s)")
                    if status == "completed" and int(duration or 0) > 5:
                        print("AI dialogue likely occurred!")
                    elif status == "completed" and int(duration or 0) <= 5:
                        print("WARNING: Very short call — AI may not have spoken.")
                    return data
            else:
                print(f"  [{i+1}/{max_polls}] Status poll returned {resp.status_code}")
        except requests.exceptions.RequestException:
            print(f"  [{i+1}/{max_polls}] Poll failed, retrying...")

    print("Polling timed out — check SignalWire dashboard for final status.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Place an outbound AI call via SignalWire")
    parser.add_argument("--to", required=True, help="Phone number to call (E.164 format)")
    parser.add_argument("--from-number", default=DEFAULT_FROM, help=f"From number (default: {DEFAULT_FROM})")
    parser.add_argument("--agent", default="cold-caller",
                        choices=["cold-caller", "discovery-caller"],
                        help="Agent profile to use (default: cold-caller)")
    args = parser.parse_args()

    make_call(args.to, args.from_number, args.agent)


if __name__ == "__main__":
    main()
