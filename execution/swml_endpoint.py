"""
SWML Endpoint for SignalWire AI Outbound Calls
Deployed as a Google Cloud Function alongside the existing SWAIG webhook.

When the Compatibility API places an outbound call with Url pointing here,
SignalWire POSTs to this endpoint and expects SWML JSON instructions back.
We return an 'ai' method block that starts the AI agent conversation.

ROOT CAUSE FIX: The old approach pointed Url at /api/ai/agent/{id} or relied
on the phone number's Voice URL (/api/fabric/resources/{id}/execute), both of
which don't return valid SWML/LAML — causing silence on outbound calls.
"""

import json
import functions_framework
from flask import jsonify, request

# Agent configurations keyed by a friendly name.
# Prompt text and SWAIG functions match what's already configured in SignalWire Fabric,
# but we inline them here so the SWML response is self-contained.
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

# SWAIG function definitions — these point to the existing GCF webhook
SWAIG_WEBHOOK = "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook"

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
    """Build SWML JSON for the specified agent."""
    agent = AGENTS.get(agent_key, AGENTS["cold-caller"])

    swml = {
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
    return swml


@functions_framework.http
def swml_outbound(request):
    """
    Google Cloud Function entry point.
    Returns SWML JSON for SignalWire outbound AI calls.

    Query params:
      - agent: agent key (default: "cold-caller")
                Options: "cold-caller", "discovery-caller"

    The Compatibility API should call with:
      Url=https://us-central1-tatt-pro.cloudfunctions.net/swmlOutbound?agent=cold-caller
    """
    agent_key = request.args.get("agent", "cold-caller")
    swml = build_swml(agent_key)

    return jsonify(swml)
