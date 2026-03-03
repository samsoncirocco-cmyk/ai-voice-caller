#!/usr/bin/env python3
"""
AI Voice Caller — Production Server
Uses SignalWire Agents SDK to serve SWML for outbound AI phone calls.
Two agent profiles: cold-caller and discovery.

Routes:
  /cold-caller  — Cold call agent (qualify prospects for Fortinet)
  /discovery    — Discovery agent (find IT decision-makers)
  /health       — Health check
"""
import os
import json
from datetime import datetime
from signalwire_agents import AgentBase, AgentServer, SwaigFunctionResult

# ── Configuration ──────────────────────────────────────────────────────
PORT = 3001
WEBHOOK_URL = "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook"
VOICE = "amazon.Matthew"
MODEL = "gpt-4.1-nano"


# ── Cold Caller Agent ──────────────────────────────────────────────────
def create_cold_caller():
    agent = AgentBase(
        name="cold-caller",
        route="/cold-caller",
        suppress_logs=False,
        basic_auth=("signalwire", "fortinet2026"),
    )

    # AI params
    agent.set_params({
        "static_greeting": (
            "Hey there! This is Matt calling from Fortinet. "
            "Hope I'm not catching you at a bad time — do you have just a quick minute?"
        ),
        "direction": "outbound",
        "end_of_speech_timeout": 1500,
        "attention_timeout": 15000,
        "inactivity_timeout": 30000,
        "ai_model": MODEL,
    })

    # Voice
    agent.add_language(
        "English", "en-US", VOICE,
        speech_fillers=["um", "uh", "so", "let me think"],
        function_fillers=["One moment while I save that...", "Let me note that down..."],
    )

    # Prompt
    agent.prompt_add_section("Identity", body=(
        "You are Matt, a friendly solutions consultant calling on behalf of Fortinet. "
        "You specialize in cybersecurity for K-12 schools, local government, and state agencies."
    ))

    agent.prompt_add_section("Goal", body=(
        "Your goal is a brief, warm conversation:\n"
        "1. Introduce yourself: 'This is Matt from Fortinet.'\n"
        "2. Ask about their biggest cybersecurity challenge right now.\n"
        "3. Listen actively — reference what they say.\n"
        "4. If there's a fit, offer a 15-minute follow-up call with a local Fortinet partner.\n"
        "5. If they're not interested, thank them warmly and end the call.\n"
        "Keep it under 2 minutes. Be conversational, not scripted."
    ))

    agent.prompt_add_section("Style", body=(
        "- Speak naturally, like a real human — use contractions, casual phrasing\n"
        "- Mirror their energy (if they're formal, be professional; if casual, be relaxed)\n"
        "- Never read a script — respond to what they actually say\n"
        "- If they say 'not interested', respect it immediately — don't push\n"
        "- Use their name if they give it\n"
        "- Laugh naturally if something's funny"
    ))

    agent.prompt_add_section("Objection Handling", body=(
        "'Not interested': 'Totally understand. If anything changes, Fortinet is always here. Have a great day!'\n"
        "'Send me info': 'Happy to! What's the best email? I'll send over a quick one-pager.'\n"
        "'Who is this?': 'Matt from Fortinet — we help organizations like yours with cybersecurity. Just reaching out to see if there's anything we can help with.'\n"
        "'I'm busy': 'No worries at all. When would be a better time to catch you for 60 seconds?'"
    ))

    agent.prompt_add_section("Important Rules", body=(
        "- NEVER make up Fortinet product details you're unsure about\n"
        "- If asked technical questions, offer to connect them with a specialist\n"
        "- Always log the call outcome using log_call before ending\n"
        "- If you get contact info, save it with save_contact"
    ))

    # SWAIG functions — webhook-based
    agent.define_tool(
        name="save_contact",
        description="Save contact information collected during the call (name, email, phone, role, organization)",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Full name of the contact"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Direct phone number"},
                "role": {"type": "string", "description": "Job title or role"},
                "organization": {"type": "string", "description": "Organization name"},
                "notes": {"type": "string", "description": "Any relevant notes"},
            },
        },
        required=["contact_name"],
        handler=handle_save_contact,
        secure=False,
    )

    agent.define_tool(
        name="log_call",
        description="Log the outcome of this call (must be called before ending every call)",
        parameters={
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["meeting_scheduled", "info_requested", "callback_requested", "not_interested", "no_answer", "wrong_person", "voicemail"],
                    "description": "Call outcome",
                },
                "interest_level": {
                    "type": "string",
                    "enum": ["hot", "warm", "cold", "none"],
                    "description": "Prospect interest level",
                },
                "summary": {"type": "string", "description": "Brief summary of the conversation"},
                "next_steps": {"type": "string", "description": "Agreed next steps, if any"},
                "contact_name": {"type": "string", "description": "Name of person spoken to"},
            },
        },
        required=["outcome", "summary"],
        handler=handle_log_call,
        secure=False,
    )

    return agent


# ── Discovery Agent ────────────────────────────────────────────────────
def create_discovery_agent():
    agent = AgentBase(
        name="discovery",
        route="/discovery",
        suppress_logs=False,
        basic_auth=("signalwire", "fortinet2026"),
    )

    # AI params
    agent.set_params({
        "static_greeting": (
            "Hi there! This is Matt calling from Fortinet. "
            "I'm trying to reach whoever handles IT or cybersecurity at your organization — "
            "could you point me in the right direction?"
        ),
        "direction": "outbound",
        "end_of_speech_timeout": 1500,
        "attention_timeout": 15000,
        "inactivity_timeout": 30000,
        "ai_model": MODEL,
    })

    # Voice
    agent.add_language(
        "English", "en-US", VOICE,
        speech_fillers=["um", "let me see"],
        function_fillers=["Let me jot that down...", "Got it, saving that..."],
    )

    # Prompt
    agent.prompt_add_section("Identity", body=(
        "You are Matt, a warm and personable assistant calling on behalf of Fortinet. "
        "Your sole job is to find out who handles IT or cybersecurity decisions at this organization."
    ))

    agent.prompt_add_section("Goal", body=(
        "1. Introduce yourself warmly.\n"
        "2. Ask who handles IT, cybersecurity, or technology decisions.\n"
        "3. Get their name and direct phone number (or extension).\n"
        "4. If they offer an email, take that too.\n"
        "5. Confirm what you heard by repeating it back.\n"
        "6. Thank them sincerely — they just did you a huge favor.\n"
        "7. Save the contact info using save_contact.\n"
        "8. Log the call using log_call."
    ))

    agent.prompt_add_section("Style", body=(
        "- Be genuinely grateful — you're asking for help, not selling\n"
        "- Keep it under 60 seconds\n"
        "- If they transfer you, go with it and repeat the process\n"
        "- If they don't know, thank them anyway\n"
        "- Use phrases like 'I really appreciate your help' and 'You've been super helpful'\n"
        "- Sound human — not robotic"
    ))

    agent.prompt_add_section("If They Ask Why", body=(
        "If they ask why you're calling or what Fortinet does:\n"
        "'We're a cybersecurity company — we work with a lot of schools and government agencies "
        "in the area, and I just wanted to connect with the right person to see if there's "
        "anything we can help with. Nothing urgent at all!'"
    ))

    # SWAIG functions
    agent.define_tool(
        name="save_contact",
        description="Save the IT contact information discovered during the call",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Name of the IT/cybersecurity contact"},
                "phone": {"type": "string", "description": "Direct phone number or extension"},
                "email": {"type": "string", "description": "Email address if provided"},
                "role": {"type": "string", "description": "Their title or role"},
                "organization": {"type": "string", "description": "Organization name"},
                "notes": {"type": "string", "description": "Any additional context"},
            },
        },
        required=["contact_name"],
        handler=handle_save_contact,
        secure=False,
    )

    agent.define_tool(
        name="log_call",
        description="Log the outcome of this discovery call",
        parameters={
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["contact_found", "transferred", "no_info", "wrong_number", "voicemail"],
                    "description": "Discovery call outcome",
                },
                "summary": {"type": "string", "description": "Brief summary"},
                "contact_name": {"type": "string", "description": "Who answered the phone"},
            },
        },
        required=["outcome", "summary"],
        handler=handle_log_call,
        secure=False,
    )

    return agent


# ── SWAIG Function Handlers ───────────────────────────────────────────
def handle_save_contact(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
    """Forward contact data to webhook and log locally."""
    try:
        import urllib.request
        payload = {
            "function": "save_contact",
            "timestamp": datetime.utcnow().isoformat(),
            "data": args,
            "call_metadata": {
                "call_id": raw_data.get("call_id", "") if raw_data else "",
                "caller": raw_data.get("call_from", "") if raw_data else "",
                "callee": raw_data.get("call_to", "") if raw_data else "",
            },
        }
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"⚠️  Webhook error (save_contact): {e}")

    name = args.get("contact_name", "Unknown")
    print(f"✅ Contact saved: {name}")
    return SwaigFunctionResult(f"Contact information for {name} has been saved successfully.")


def handle_log_call(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
    """Forward call log to webhook and log locally."""
    try:
        import urllib.request
        payload = {
            "function": "log_call",
            "timestamp": datetime.utcnow().isoformat(),
            "data": args,
            "call_metadata": {
                "call_id": raw_data.get("call_id", "") if raw_data else "",
                "caller": raw_data.get("call_from", "") if raw_data else "",
                "callee": raw_data.get("call_to", "") if raw_data else "",
            },
        }
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"⚠️  Webhook error (log_call): {e}")

    outcome = args.get("outcome", "unknown")
    summary = args.get("summary", "")
    print(f"📞 Call logged: {outcome} — {summary}")
    return SwaigFunctionResult(f"Call logged as {outcome}.")


# ── Health Check (added via custom route) ──────────────────────────────
def add_health_check(app):
    """Add /health endpoint to the FastAPI app."""
    from fastapi import Response

    @app.get("/health")
    async def health():
        return Response(
            content=json.dumps({
                "status": "ok",
                "service": "ai-voice-caller",
                "agents": ["cold-caller", "discovery"],
                "timestamp": datetime.utcnow().isoformat(),
            }),
            media_type="application/json",
        )


# ── Main ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 AI Voice Caller — Production Server")
    print("=" * 60)
    print(f"  Port:    {PORT}")
    print(f"  Voice:   {VOICE}")
    print(f"  Model:   {MODEL}")
    print(f"  Agents:  /cold-caller, /discovery")
    print(f"  Health:  /health")
    print("=" * 60)

    server = AgentServer(port=PORT)

    # Register agents
    cold_caller = create_cold_caller()
    discovery = create_discovery_agent()
    server.register(cold_caller, "/cold-caller")
    server.register(discovery, "/discovery")

    # Add health check
    app = server.app  # Access underlying FastAPI app
    add_health_check(app)

    print("\n✅ Server ready. Waiting for SignalWire requests...\n")
    server.run()
