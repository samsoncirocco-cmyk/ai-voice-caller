#!/usr/bin/env python3
"""
Make outbound AI agent calls using SignalWire Calling API with inline SWML.

This version fixes the SIP 500 errors by using the Calling API (/api/calling/calls)
instead of the Compatibility API (/api/laml/.../Calls.json).

The Calling API properly supports SWML with AI agents inline.

Usage:
  python3 make_call_v5.py <phone-number>
  python3 make_call_v5.py --status      # Show recent call stats
"""
import sys
import os
import json
import time
import requests
from datetime import datetime
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

# ─── SWML AI Agent Configuration ──────────────────────────────

def get_cold_caller_swml():
    """Get SWML for the Fortinet Cold Caller AI agent."""
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {
                    "ai": {
                        "prompt": {
                            "text": """You are Paul, a knowledgeable and professional solutions consultant calling on behalf of Fortinet. You specialize in helping IT leaders in education and local government modernize their voice and security infrastructure.

You are NOT pushy or aggressive. You are genuinely curious about their challenges and focused on finding solutions that fit their needs.

CONVERSATION FLOW:
1. GREETING: Hi, this is Paul from Fortinet. Is this the IT department?
2. CONFIRM TIME: Do you have 2 minutes for a quick question about your voice systems?
3. KILLER QUESTION: Quick question -- what happens to your phones when the internet goes down?
4. QUALIFY INTEREST based on their answer:
   - No survivability: That is a common gap. Most organizations lose 911 capability during outages.
   - Have failover: Smart. Are you happy with that setup, or is it something you would improve?
   - Don't know: That is actually why I am calling. We help ensure voice reliability.
5. PIVOT TO SOLUTION: We are helping organizations in your area with three main areas:
   - Unified SASE (secure network access for hybrid work)
   - OT Security (protecting critical infrastructure)
   - AI-Driven Security (automated threat detection)
6. SCHEDULE OR SEND INFO: Would you be open to a 15-minute call with our partner High Point Networks?

GUIDELINES:
- Keep sentences short and conversational
- If they say they're busy, respect their time and offer to call back
- Keep the call under 3 minutes
- Always log the call outcome using log_call before ending""",
                            "confidence": 0.6,
                            "temperature": 0.3
                        },
                        "post_prompt": {
                            "text": "Summarize the call outcome. Log the call using log_call with the outcome (interested, not_interested, callback_requested, wrong_person, no_answer)."
                        },
                        "params": {
                            "ai_model": "gpt-4.1-nano",
                            "direction": "outbound",
                            "end_of_speech_timeout": 2000,
                            "inactivity_timeout": 30000
                        },
                        "languages": [
                            {
                                "code": "en-US",
                                "provider": "amazon",
                                "voice": "amazon.Matthew:standard:en-US"
                            }
                        ],
                        "SWAIG": {
                            "functions": [
                                {
                                    "function": "log_call",
                                    "web_hook_url": CONFIG["swaig_webhook_url"],
                                    "description": "Log call outcome. Always call this before ending.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "outcome": {
                                                "type": "string",
                                                "description": "Call outcome: interested, not_interested, callback_requested, wrong_person, no_answer"
                                            },
                                            "summary": {
                                                "type": "string",
                                                "description": "Brief one-sentence call summary"
                                            }
                                        },
                                        "required": ["outcome"]
                                    }
                                },
                                {
                                    "function": "save_contact",
                                    "web_hook_url": CONFIG["swaig_webhook_url"],
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
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }


def get_discovery_swml():
    """Get SWML for the Discovery Caller AI agent (shorter, simpler)."""
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {
                    "ai": {
                        "prompt": {
                            "text": """You are Paul, and you work with Samson at Fortinet. You're calling schools and government organizations to help them with IT security. Be WARM, GRATEFUL, and CONVERSATIONAL.

Start with:
'Hey there! This is Paul from Fortinet. I know I'm calling out of the blue here, so I really appreciate you picking up.'

Then ask:
'Quick question - I'm trying to get in touch with whoever handles your IT stuff. Do you happen to know who that would be?'

Key behaviors:
- Use natural language ('Hey', 'you know', 'um')
- Thank them for their time
- Be patient if they need to look something up
- If they don't know, thank them anyway and end the call
- Keep it under 60 seconds
- Be genuinely grateful

IMPORTANT: When you get a contact name and phone number, CONFIRM what you heard, then call save_contact. Before ending, call log_call with the outcome.""",
                            "confidence": 0.6,
                            "temperature": 0.3
                        },
                        "post_prompt": {
                            "text": "Call log_call with outcome: contact_captured, refused, no_answer, or error."
                        },
                        "params": {
                            "ai_model": "gpt-4.1-nano",
                            "direction": "outbound",
                            "end_of_speech_timeout": 2000,
                            "inactivity_timeout": 20000
                        },
                        "languages": [
                            {
                                "code": "en-US",
                                "provider": "amazon",
                                "voice": "amazon.Matthew:standard:en-US"
                            }
                        ],
                        "SWAIG": {
                            "functions": [
                                {
                                    "function": "save_contact",
                                    "web_hook_url": CONFIG["swaig_webhook_url"],
                                    "description": "Save IT contact name, phone, and organization.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "phone": {"type": "string"},
                                            "account": {"type": "string"}
                                        },
                                        "required": ["name"]
                                    }
                                },
                                {
                                    "function": "log_call",
                                    "web_hook_url": CONFIG["swaig_webhook_url"],
                                    "description": "Log call outcome.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "outcome": {"type": "string"},
                                            "summary": {"type": "string"}
                                        },
                                        "required": ["outcome"]
                                    }
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }


# ─── Call Functions ────────────────────────────────────────────

def make_call(to_number, agent_type="cold_caller"):
    """
    Make outbound call using SignalWire Calling API with inline SWML.
    
    Args:
        to_number: Phone number to call (E.164 format)
        agent_type: "cold_caller" or "discovery"
    """
    # Get appropriate SWML
    if agent_type == "discovery":
        swml = get_discovery_swml()
        print(f"  Using Discovery agent")
    else:
        swml = get_cold_caller_swml()
        print(f"  Using Cold Caller agent")
    
    # Use Calling API (not Compatibility API)
    api_url = f"https://{SPACE_URL}/api/calling/calls"
    
    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "caller_id": FROM_NUMBER,
            "swml": swml
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    print(f"  Calling {to_number} via Calling API...")
    
    try:
        resp = requests.post(
            api_url,
            auth=(PROJECT_ID, AUTH_TOKEN),
            json=payload,
            headers=headers,
            timeout=20
        )
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Request failed: {e}")
        return None
    
    if resp.status_code not in [200, 201]:
        print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    
    data = resp.json()
    call_id = data.get("id")
    status = data.get("status")
    
    print(f"  Call ID: {call_id}")
    print(f"  Status: {status}")
    print(f"  Type: {data.get('type')}")
    
    return data


def check_status():
    """Show recent call statistics from Compatibility API."""
    print("=== RECENT CALLS ===")
    
    url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json?PageSize=10"
    resp = requests.get(url, auth=(PROJECT_ID, AUTH_TOKEN), timeout=10)
    
    if not resp.ok:
        print(f"Error: {resp.text}")
        return
    
    calls = resp.json().get("calls", [])
    
    completed = sum(1 for c in calls if c["status"] == "completed")
    failed = sum(1 for c in calls if c["status"] == "failed")
    
    print(f"\n  Last 10 calls: {completed} completed, {failed} failed")
    print("")
    
    for call in calls:
        sip = call.get("sip_result_code") or "N/A"
        status_icon = "✓" if call["status"] == "completed" else "✗"
        start = call.get("start_time", "N/A")
        print(f"  {status_icon} {call['status'][:8]:8} | SIP:{str(sip):4} | {call['duration']:3}s | {start[:20] if start else 'N/A'}")


# ─── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 make_call_v5.py <phone-number>              # Cold caller agent")
        print("  python3 make_call_v5.py <phone-number> --discovery  # Discovery agent")
        print("  python3 make_call_v5.py --status                    # Show recent calls")
        sys.exit(1)
    
    arg = sys.argv[1]
    
    if arg == "--status":
        check_status()
        sys.exit(0)
    
    # Determine agent type
    agent_type = "cold_caller"
    if len(sys.argv) > 2 and sys.argv[2] == "--discovery":
        agent_type = "discovery"
    
    # Phone number normalization
    phone = arg.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"
    
    print(f"\n{'='*60}")
    print(f"OUTBOUND AI AGENT CALL (v5 - Calling API + Inline SWML)")
    print(f"{'='*60}")
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {phone}")
    print(f"  Agent: {agent_type}")
    print(f"{'='*60}\n")
    
    result = make_call(phone, agent_type)
    
    if result:
        print(f"\n{'='*60}")
        print(f"  CALL INITIATED - ANSWER YOUR PHONE!")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print(f"  CALL FAILED")
        print(f"{'='*60}")
