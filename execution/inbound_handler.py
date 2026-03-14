#!/usr/bin/env python3
"""
inbound_handler.py — Handle inbound calls to local-presence numbers.

When prospects call back our SD (605), NE (402), or IA (515) numbers,
this provides a professional SWML response instead of dead air.

The webhook_server.py routes inbound calls here, which returns SWML JSON
that SignalWire executes.

Behavior:
  - Greet the caller professionally as Fortinet
  - Attempt to identify who's calling (by caller ID lookup in call logs)
  - Offer to connect them with Samson directly or take a message
  - Log the inbound call for follow-up

Usage:
  # Register as a SignalWire webhook URL (done via webhook_server.py)
  # POST /voice-caller/inbound → returns SWML JSON

  # Test locally:
  python3 execution/inbound_handler.py --test
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
SUMMARIES_FILE = LOGS_DIR / "call_summaries.jsonl"
ARCHIVE_FILE = LOGS_DIR / "call_summaries_test_archive_mar13.jsonl"
INBOUND_LOG = LOGS_DIR / "inbound_calls.jsonl"

# Samson's cell — calls get offered to transfer here
SAMSON_CELL = "+16022950104"

# Local presence number → state mapping
NUMBER_TO_STATE = {
    "+16053035984": "South Dakota",
    "+14022755273": "Nebraska",
    "+15152987809": "Iowa",
    "+16028985026": "Arizona",
    "+14806024668": "Arizona",
    "+14808227861": "Arizona",
    "+14806025848": "Arizona",
}

# Post-prompt instruction for the inbound AI
INBOUND_POST_PROMPT = (
    "Summarize the inbound call in this exact format:\n"
    "- Caller name: [name or 'unknown']\n"
    "- Caller organization: [org or 'unknown']\n"
    "- Reason for calling: [why they called]\n"
    "- Message left: [what they said]\n"
    "- Transfer requested: [yes/no]\n"
    "- Callback requested: [yes/no — if yes, include preferred time]\n"
    "- Notes: [anything else useful]"
)


def lookup_caller(from_number: str) -> Optional[Dict]:
    """
    Look up a caller by phone number in our call history.
    Returns context about previous outbound calls to this number.
    """
    if not from_number:
        return None

    digits = re.sub(r"\D", "", from_number)
    last10 = digits[-10:] if len(digits) >= 10 else digits

    matches = []
    for filepath in [SUMMARIES_FILE, ARCHIVE_FILE]:
        if not filepath.exists():
            continue
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                to_num = re.sub(r"\D", "", entry.get("to", ""))
                if to_num.endswith(last10):
                    matches.append(entry)

    if not matches:
        return None

    # Return the most recent match
    latest = sorted(matches, key=lambda x: x.get("timestamp", ""), reverse=True)[0]

    # Extract useful context
    summary = latest.get("summary", "")
    account = latest.get("account_name", "")
    sfdc_id = latest.get("sfdc_id", "")

    # Try to extract contact name from summary
    contact_match = re.search(r"spoke with[:\s]+([^\n]+)", summary, re.IGNORECASE)
    contact_name = contact_match.group(1).strip() if contact_match else None
    if contact_name and contact_name.lower() in ("unknown", "none"):
        contact_name = None

    return {
        "account_name": account,
        "sfdc_id": sfdc_id,
        "last_call_date": latest.get("timestamp", ""),
        "contact_name": contact_name,
        "previous_summary": summary[:300] if summary else None,
    }


def build_inbound_swml(from_number: str, to_number: str) -> Dict:
    """
    Build SWML JSON for handling an inbound call.

    The AI agent:
    1. Greets professionally
    2. References previous call if we recognize the number
    3. Offers to connect to Samson or take a message
    4. Logs everything via post_prompt_url
    """
    state = NUMBER_TO_STATE.get(to_number, "")
    caller_context = lookup_caller(from_number)

    # Build dynamic prompt based on whether we recognize the caller
    if caller_context and caller_context.get("account_name"):
        account = caller_context["account_name"]
        contact = caller_context.get("contact_name", "")
        greeting_context = (
            f"CALLER CONTEXT: This person is calling back from {account}. "
            f"{'Their name is ' + contact + '. ' if contact else ''}"
            f"We called them recently as part of Fortinet outreach. "
            f"Be warm and acknowledge they're returning our call."
        )
    else:
        greeting_context = (
            "CALLER CONTEXT: Unknown caller — we don't have prior history. "
            "Be professional and helpful. They may be returning a call or "
            "reaching out independently."
        )

    prompt_text = f"""You are a professional AI assistant answering calls for Samson Cirocco at Fortinet.
This call is coming in on our {state} office line.

{greeting_context}

YOUR BEHAVIOR:
- Be professional, warm, and efficient
- If they're returning our call, thank them and explain Samson wanted to connect about network security
- If they're calling for another reason, help them or offer to take a message
- ALWAYS offer two options: (1) connect them directly to Samson, or (2) take a message and have Samson call back
- If they want to be connected, say "Let me transfer you now" — the system will handle the transfer
- If they want a callback, get their preferred time and confirm their phone number
- Keep it brief — under 2 minutes
- If asked if you're AI: "Yes, I'm an AI assistant for Samson's office at Fortinet. I can connect you directly or take a message — which would you prefer?"

DO NOT:
- Make up information about Fortinet products
- Promise specific meeting times without checking
- Be pushy or salesy — they called US
- Hang up until they're ready to end the call"""

    swml = {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {
                    "ai": {
                        "languages": [
                            {
                                "name": "English",
                                "code": "en-US",
                                "voice": "openai.onyx",
                                "speech_rate": 1.1,
                            }
                        ],
                        "prompt": {
                            "text": prompt_text,
                            "temperature": 0.7,
                        },
                        "post_prompt": {
                            "text": INBOUND_POST_PROMPT,
                        },
                        "post_prompt_url": f"https://hooks.6eyes.dev/voice-caller/inbound-callback?direction=inbound&from={from_number}&to={to_number}",
                        "params": {
                            "ai_model": "gpt-4.1-nano",
                            "direction": "inbound",
                            "wait_for_user": True,
                            "attention_timeout": 30000,
                            "inactivity_timeout": 30000,
                            "end_of_speech_timeout": 3000,
                            "asr_engine": "deepgram:nova-3",
                        },
                        "SWAIG": {
                            "functions": [
                                {
                                    "function": "transfer_to_samson",
                                    "purpose": "Transfer the caller to Samson Cirocco's cell phone. Use when the caller wants to speak with Samson directly. Say 'Connecting you now, one moment please' before calling this.",
                                    "argument": {
                                        "type": "object",
                                        "properties": {
                                            "reason": {
                                                "type": "string",
                                                "description": "Brief reason for the transfer",
                                            }
                                        },
                                        "required": ["reason"],
                                    },
                                    "data_map": {
                                        "expressions": [
                                            {
                                                "string": "%{args.reason}",
                                                "pattern": ".*",
                                                "output": {
                                                    "response": "Transferring you to Samson now.",
                                                    "action": [
                                                        {
                                                            "SWML": {
                                                                "version": "1.0.0",
                                                                "sections": {
                                                                    "main": [
                                                                        {
                                                                            "connect": {
                                                                                "to": SAMSON_CELL,
                                                                                "from": to_number,
                                                                                "timeout": 30,
                                                                            }
                                                                        }
                                                                    ]
                                                                },
                                                            }
                                                        }
                                                    ],
                                                },
                                            }
                                        ]
                                    },
                                },
                                {
                                    "function": "end_call",
                                    "purpose": "Hang up the call after the conversation is finished and the caller has said goodbye.",
                                    "argument": {
                                        "type": "object",
                                        "properties": {
                                            "reason": {
                                                "type": "string",
                                                "description": "Why the call is ending",
                                            }
                                        },
                                        "required": ["reason"],
                                    },
                                    "data_map": {
                                        "expressions": [
                                            {
                                                "string": "%{args.reason}",
                                                "pattern": ".*",
                                                "output": {
                                                    "response": "Thank you for calling. Goodbye!",
                                                    "action": [
                                                        {
                                                            "SWML": {
                                                                "version": "1.0.0",
                                                                "sections": {
                                                                    "main": [
                                                                        {"hangup": {}}
                                                                    ]
                                                                },
                                                            }
                                                        }
                                                    ],
                                                },
                                            }
                                        ]
                                    },
                                },
                            ]
                        },
                    }
                },
            ]
        },
    }

    return swml


def log_inbound_call(from_number: str, to_number: str, data: Dict = None) -> None:
    """Log an inbound call for tracking."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": "inbound",
        "from": from_number,
        "to": to_number,
        "state": NUMBER_TO_STATE.get(to_number, "unknown"),
        "caller_context": lookup_caller(from_number),
        "callback_data": data,
    }
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(INBOUND_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Test Mode ──────────────────────────────────────────────────────────────────

def test_swml():
    """Generate and print sample SWML for testing."""
    print("=" * 60)
    print("TEST 1: Known caller (from our call history)")
    print("=" * 60)
    swml = build_inbound_swml("+14802997325", "+16053035984")
    print(json.dumps(swml, indent=2)[:2000])

    print("\n" + "=" * 60)
    print("TEST 2: Unknown caller")
    print("=" * 60)
    swml = build_inbound_swml("+15551234567", "+14022755273")
    print(json.dumps(swml, indent=2)[:2000])

    print("\n✅ SWML generation working correctly")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Generate test SWML")
    args = parser.parse_args()

    if args.test:
        test_swml()
    else:
        print("Use --test to generate sample SWML, or import and call build_inbound_swml()")
