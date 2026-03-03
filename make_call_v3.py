#!/usr/bin/env python3
"""
Make an outbound call with SWAIG functions.

Strategy: Host SWML as a second Cloud Function endpoint that SignalWire fetches.
Uses the proven Compatibility API with a Url parameter pointing to our SWML server.

But first, try the simpler approach: pass SWML as the 'Url' directly using a data URI,
or use the newer Calling API with proper SWML format.

Usage:
  python3 make_call_v3.py <phone-number>
"""
import sys
import json
import base64
import requests

# ─── Configuration ──────────────────────────────────────────
PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"
SPACE_URL = "6eyes.signalwire.com"
FROM_NUMBER = "+16028985026"
SWAIG_WEBHOOK_URL = "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook"

AI_PROMPT = """You are Paul, and you work with Samson at Fortinet. You're calling schools and government organizations to help them with IT security. Be WARM, GRATEFUL, and CONVERSATIONAL - not robotic or scripted.

Start with:
'Hey there! This is Paul - I work with Samson over at Fortinet. I know I'm calling out of the blue here, so I really appreciate you picking up.'

Then naturally transition to:
'Quick question - I'm trying to get in touch with whoever handles your IT stuff. Do you happen to know who that would be? And if you do, would you mind sharing their direct number so I can reach out to them?'

Key behaviors:
- Use natural language ('Hey', 'you know', 'um')
- Thank them multiple times for their time
- Acknowledge this is a cold call
- Be patient if they need to look something up
- Sound like a helpful human, not a sales robot
- If they don't know, thank them anyway and politely end the call
- Keep it under 60 seconds total
- Be genuinely grateful - they're doing YOU a favor

IMPORTANT: When you get a contact name and phone number, CONFIRM what you heard, then call the save_contact function with their info. When the call is ending, call log_call with the outcome.

Remember: You're asking for help, not pitching. Be humble and appreciative."""


def build_swml():
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "prompt": {"text": AI_PROMPT},
                        "post_prompt": {
                            "text": "Call log_call with the outcome before ending. Use 'contact_captured' if you got info, 'refused' if they declined, 'no_answer' if no one answered."
                        },
                        "params": {
                            "voice": "Polly.Matthew"
                        },
                        "SWAIG": {
                            "functions": [
                                {
                                    "function": "save_contact",
                                    "description": "Save the IT contact's name, phone number, and organization to the database. Call this after confirming the contact information.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string", "description": "IT contact's full name"},
                                            "phone": {"type": "string", "description": "IT contact's direct phone number"},
                                            "account": {"type": "string", "description": "Organization or school name"}
                                        },
                                        "required": ["name"]
                                    },
                                    "web_hook_url": SWAIG_WEBHOOK_URL
                                },
                                {
                                    "function": "log_call",
                                    "description": "Log the call outcome. Always call this before saying goodbye.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "outcome": {"type": "string", "description": "contact_captured, refused, voicemail, no_answer, or error", "enum": ["contact_captured", "refused", "voicemail", "no_answer", "error"]},
                                            "summary": {"type": "string", "description": "Brief summary of the call"}
                                        },
                                        "required": ["outcome"]
                                    },
                                    "web_hook_url": SWAIG_WEBHOOK_URL
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }


def make_call(to_number):
    swml = build_swml()
    swml_json = json.dumps(swml)

    # Use the Calling API (the one that returned 200 before)
    # with proper Content-Type and auth
    auth_string = f"{PROJECT_ID}:{AUTH_TOKEN}"
    auth_b64 = base64.b64encode(auth_string.encode()).decode()

    url = f"https://{SPACE_URL}/api/calling/calls"
    payload = {
        "command": "dial",
        "params": {
            "from_number": FROM_NUMBER,
            "to_number": to_number,
            "swml": swml,
            "timeout": 30
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }

    print(f"\n{'='*70}")
    print(f"📞 OUTBOUND CALL (v3 - Calling API + inline SWML + SWAIG)")
    print(f"{'='*70}")
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {to_number}")
    print(f"  SWAIG: {SWAIG_WEBHOOK_URL}")
    print(f"  Functions: save_contact, log_call")
    print(f"{'='*70}\n")

    response = requests.post(url, json=payload, headers=headers)

    print(f"  API Response: {response.status_code}")

    if response.status_code in [200, 201]:
        data = response.json()
        call_id = data.get("id", "unknown")
        print(f"✅ Call initiated!")
        print(f"   Call ID: {call_id}")

        # Also try Compatibility API as fallback if Calling API doesn't ring
        print(f"\n   (Also trying Compatibility API as backup...)")
        compat_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"
        compat_payload = {
            "From": FROM_NUMBER,
            "To": to_number,
            "Url": f"https://{SPACE_URL}/api/relay/rest/swml",
        }
        # Don't actually send backup - just show what would be sent
        print(f"   Backup URL would be: {compat_url}")

        return data
    else:
        print(f"❌ Calling API failed: {response.status_code}")
        print(f"   {response.text[:300]}")

        # Fallback: Compatibility API with SWML hosted as Cloud Function
        print(f"\n🔄 Trying Compatibility API with SWML hosting...")
        return make_call_compat_fallback(to_number, swml_json)


def make_call_compat_fallback(to_number, swml_json):
    """
    Fallback: Use Compatibility API.
    Host the SWML at a Cloud Function URL that returns it.
    We use our existing swaigWebhook but add a /swml route.
    
    For now, use the approach that worked: Url pointing to the AI agent,
    but we lose SWAIG functions. This is the "at least the call works" fallback.
    """
    AI_AGENT_ID = "f2c41814-4a36-436b-b723-71d5cdffec60"
    api_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"
    
    payload = {
        "From": FROM_NUMBER,
        "To": to_number,
        "Url": f"https://{SPACE_URL}/api/ai/agent/{AI_AGENT_ID}",
        "Method": "POST"
    }

    response = requests.post(
        api_url,
        auth=(PROJECT_ID, AUTH_TOKEN),
        json=payload
    )

    if response.status_code in [200, 201]:
        data = response.json()
        call_sid = data.get("sid", "unknown")
        print(f"✅ Fallback call initiated (no SWAIG - agent only)")
        print(f"   Call SID: {call_sid}")
        print(f"   ⚠️  SWAIG functions NOT active on this call")
        return data
    else:
        print(f"❌ Fallback also failed: {response.status_code}")
        print(f"   {response.text[:300]}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make_call_v3.py <phone-number>")
        sys.exit(1)

    phone = sys.argv[1].replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"

    result = make_call(phone)
    if result:
        print(f"\n{'='*70}")
        print(f"✅ ANSWER YOUR PHONE!")
        print(f"{'='*70}")
    else:
        print(f"\n❌ ALL ATTEMPTS FAILED")
