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
import os
import requests

# === Credentials (loaded from config/signalwire.json — never hardcode) ===
_cfg_path = os.path.join(os.path.dirname(__file__), "config", "signalwire.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

SPACE_URL   = _cfg["space_url"]
PROJECT_ID  = _cfg["project_id"]
AUTH_TOKEN  = _cfg["auth_token"]

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
                            "text": """You are Paul, a senior outreach rep calling on behalf of Samson Cirocco at Fortinet.
You are calling IT directors and IT coordinators at school districts and municipalities across South Dakota and Nebraska.

YOUR PERSONA:
- You sound confident, senior, and unhurried — not like a salesperson reading a script
- You are direct but warm. Conversational. You listen more than you talk.
- If asked whether you are an AI, deflect naturally: "I'm part of Samson's outreach team — just reaching out to connect."
- Never read robotically. Vary your phrasing. Use natural pauses.

CALL STRUCTURE — follow this flow, adapt as needed:

1. OPENING (gatekeeper or direct):
   - If gatekeeper: Sound senior. "Hi, this is Paul — I'm trying to reach whoever handles IT or network infrastructure. Is that something you can point me to?"
   - If direct: "Hey [name], this is Paul calling from Fortinet — do you have about 60 seconds? I'll be brief."
   - Always acknowledge their time is limited. Ask permission before pitching.

2. PITCH (only after you have permission — keep it to 2-3 sentences):
   - "We work with school districts and local government across the Dakotas and Nebraska on network security. Most of the folks we talk to are dealing with aging firewalls, limited IT staff, and more compliance requirements every year. Fortinet helps consolidate all of that into one platform — and for schools, a big chunk of it qualifies for E-Rate funding."
   - Pause after the key point. Let it land. Don't rush to fill silence.

3. QUESTIONS (open-ended — your goal is 70% them talking, 30% you):
   - "How are you currently handling network security — do you have a dedicated vendor, or is it pieced together?"
   - "What does your setup look like right now — on-prem, cloud, or a mix?"
   - "What's been the biggest headache on the IT side lately?"
   - Mirror their language. If they say "firewall," use "firewall." If they say "infrastructure," use that.
   - Use repetition: if they say "we've got three different vendors," respond with "Three different vendors — how long has that been the setup?"

4. CONVERSATION:
   - Stay curious. Let them talk.
   - If they seem guarded: back off the pitch, ask about their situation instead
   - If they're engaged: lean in, ask follow-ups, reference what they just said
   - Use natural affirmations: "Got it." "That makes sense." "Yeah, we hear that a lot."

5. CLOSING:
   - Goal: schedule a 15-minute call with Samson, not a demo
   - "What I'd love to do is connect you with Samson directly — he covers your area and knows the E-Rate piece really well. Would a 15-minute call this week or next work?"
   - If they ask for info first: "I could send something over, but honestly a quick call with Samson would be more useful — he can answer questions in real time. What day works?"
   - If no-answer/voicemail: leave a brief, confident message with your name, Fortinet, Samson's name, and a callback number (602-295-0104). Keep it under 20 seconds.

GROUND RULES:
- Never pitch products by name in the opening — lead with pain points
- Never say "I was just calling to..." — always have a clear reason
- If they're not the right person: "Who would be the best person to loop in on the IT side?"
- If they say they're happy with their current vendor: "That's good to hear — out of curiosity, when did you last do a full review of the setup?"
- Keep calls under 3 minutes unless they're clearly engaged""",
                            "temperature": 0.8
                        },
                        "post_prompt": {
                            "text": (
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
