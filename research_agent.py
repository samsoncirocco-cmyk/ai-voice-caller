#!/usr/bin/env python3
"""
research_agent.py — Pre-call account research using OpenRouter → Perplexity Sonar.

Researches each account before Paul calls, generating personalized context,
opening hooks, and objection handlers. Feeds directly into build_dynamic_swml().

Supports fallback to OpenAI if OpenRouter is unavailable.

Usage:
  # Research a single account
  python3 research_agent.py "Aberdeen Catholic School System" "South Dakota" "Education"

  # Import as module
  from research_agent import research_account, build_dynamic_swml
  context = research_account("Tripp-Delmont School District", "South Dakota", "Education")
  swml = build_dynamic_swml(context)

Requires:
  OPENROUTER_API_KEY in .env or environment
  OPENAI_API_KEY in .env or environment (fallback)
"""

import json
import os
import re
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

def load_env():
    """Load .env file if present."""
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# OpenRouter model: Perplexity Sonar (web-grounded, ~$1/1M tokens)
OPENROUTER_MODEL = "perplexity/sonar"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Fallback: OpenAI (no web grounding, but good for structured output)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"


# ─── Research Prompt ─────────────────────────────────────────────

RESEARCH_PROMPT = """Research the following organization for a cold call about network security:

Organization: {account_name}
Location: {state}
Type: {account_type}

Return a JSON object with EXACTLY these fields (no markdown, no backticks, just raw JSON):
{{
  "summary": "2-3 sentence overview of the organization, size, and what they do",
  "contacts": [
    {{
      "name": "Full name if found, else null",
      "title": "Job title (IT Director, Technology Coordinator, Superintendent, etc.)",
      "email": "Email address if publicly available, else null",
      "phone": "Direct phone if publicly available, else null",
      "source_url": "URL where this person was found (district website, LinkedIn, news, etc.)",
      "source_type": "official_directory | linkedin | news_mention | web_mention",
      "confidence": "high (official directory) | medium (linkedin/news) | low (web mention)"
    }}
  ],
  "hook_1": "A specific, personalized opening line referencing something current about this org (hiring, budget, news, E-Rate, board decision, tech upgrade). Must be conversational, not salesy.",
  "hook_2": "A second alternative opening hook using different intel",
  "pain_points": ["list", "of", "likely", "infrastructure", "pain", "points"],
  "tech_intel": "Any known technology vendors, current firewall/network equipment, or recent RFPs",
  "budget_cycle": "When their fiscal year starts, any known budget timelines or E-Rate filing windows",
  "conversation_starters": ["2-3 open-ended questions that would reveal their network security needs"]
}}

For contacts: search the organization's official website staff directory FIRST (highest confidence).
Then LinkedIn, then news mentions. Include up to 3 candidates. If no contacts found, return empty array [].
Do NOT invent contacts — only include people you found in a real source with a source_url.

Focus on publicly available information. If you can't find specific details, make reasonable inferences based on the organization type and location. Be factual, not speculative."""


# ─── Research Functions ──────────────────────────────────────────

def research_via_openrouter(account_name, state, account_type):
    """Research account using OpenRouter → Perplexity Sonar (web-grounded)."""
    if not OPENROUTER_API_KEY:
        return None

    prompt = RESEARCH_PROMPT.format(
        account_name=account_name, state=state, account_type=account_type
    )

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://6eyes.signalwire.com",
                "X-Title": "Fortinet SLED SDR"
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=30
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_research_json(content)
    except Exception as e:
        print(f"  [research] OpenRouter failed: {e}")
        return None


def research_via_openai(account_name, state, account_type):
    """Fallback: research using OpenAI (no web grounding)."""
    if not OPENAI_API_KEY:
        return None

    prompt = RESEARCH_PROMPT.format(
        account_name=account_name, state=state, account_type=account_type
    )

    try:
        response = requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a B2B sales research assistant. Return only valid JSON, no markdown formatting."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=30
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_research_json(content)
    except Exception as e:
        print(f"  [research] OpenAI fallback failed: {e}")
        return None


def parse_research_json(content):
    """Parse JSON from LLM response, handling markdown fences."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"  [research] Failed to parse JSON: {content[:200]}...")
        return None


def research_account(account_name, state, account_type="Education"):
    """
    Research an account using best available AI provider.
    Returns dict with summary, hooks, pain points, etc.
    Falls back gracefully if APIs are unavailable.
    Caches results for 7 days to avoid repeat API calls.
    """
    # --- Cache check ---
    cache_dir = Path(__file__).resolve().parent / "campaigns" / ".research_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\s-]", "", account_name).replace(" ", "_")[:80]
    cache_file = cache_dir / f"{safe_name}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            cached_at = cached.get("_cached_at", "")
            if cached_at:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
                if age < 7 * 86400:
                    print(f"  [research] Cache hit: {account_name}")
                    cached.setdefault("account_name", account_name)
                    cached.setdefault("state", state)
                    return cached
        except Exception:
            pass

    print(f"  [research] Researching: {account_name} ({state}, {account_type})")

    def _cache_and_return(result):
        result["account_name"] = account_name
        result["state"] = state
        result["account_type"] = account_type
        result["_cached_at"] = datetime.now(timezone.utc).isoformat()
        try:
            cache_file.write_text(json.dumps(result, indent=2))
        except Exception:
            pass
        return result

    # Try OpenRouter (Perplexity Sonar) first — web-grounded
    result = research_via_openrouter(account_name, state, account_type)
    if result:
        result["_source"] = "openrouter/sonar"
        print(f"  [research] Got context via Sonar: {result.get('summary', '')[:80]}...")
        return _cache_and_return(result)

    # Fallback to OpenAI
    result = research_via_openai(account_name, state, account_type)
    if result:
        result["_source"] = "openai/gpt-4o-mini"
        print(f"  [research] Got context via OpenAI: {result.get('summary', '')[:80]}...")
        return _cache_and_return(result)

    # Last resort: generic context
    print(f"  [research] All providers failed, using generic context")
    return {
        "summary": f"{account_name} is a {account_type.lower()} organization in {state}.",
        "contacts": [],
        "hook_1": f"I'm reaching out to {account_type.lower()} organizations in {state} about network security — do you have a moment?",
        "hook_2": f"We've been working with several {account_type.lower()} institutions in {state} on infrastructure security, and I wanted to connect.",
        "pain_points": ["network security", "firewall management", "compliance requirements"],
        "tech_intel": "Unknown",
        "budget_cycle": "Typical fiscal year",
        "conversation_starters": [
            "How are you currently handling your network security infrastructure?",
            "Have you looked at any upgrades to your firewall or switch infrastructure recently?",
            "What's your biggest technology challenge right now?"
        ],
        "_source": "generic_fallback"
    }


# ─── Contact Helpers ─────────────────────────────────────────────

def _format_contacts_for_prompt(contacts):
    """Format contacts list for injection into SWML prompt."""
    if not contacts:
        return "Unknown — your first goal is to identify the IT Director or Technology Coordinator."
    lines = []
    for c in contacts[:3]:  # max 3 candidates
        name = c.get("name") or "Unknown"
        title = c.get("title") or "Unknown title"
        conf = c.get("confidence", "low")
        email = c.get("email") or ""
        phone = c.get("phone") or ""
        extra = " | ".join(filter(None, [email, phone]))
        lines.append(f"  - {name} ({title}) [{conf} confidence]{' — ' + extra if extra else ''}")
    return "\n" + "\n".join(lines)


# ─── Dynamic SWML Builder ───────────────────────────────────────

def build_context_preamble(context):
    """
    Build a context block to prepend to any prompt file (paul.txt, cold_outreach.txt).
    This injects per-account intel without replacing the base prompt.
    """
    pain_points_str = ", ".join(context.get("pain_points", []))
    starters_str = "\n".join(f"  - {q}" for q in context.get("conversation_starters", []))

    account_name = context.get('account_name', 'Unknown Account')
    state = context.get('state', '')
    location = f"{account_name}, {state}" if state else account_name

    return f"""=== YOU ARE CALLING: {location.upper()} ===
This is the account. Know this name. Reference it naturally.

=== PRE-CALL INTEL ===
ACCOUNT SUMMARY: {context.get('summary', 'No specific intel available.')}
IT CONTACT: {_format_contacts_for_prompt(context.get('contacts', []))}
TECH INTEL: {context.get('tech_intel', 'Unknown')}
BUDGET CYCLE: {context.get('budget_cycle', 'Unknown')}

PERSONALIZED HOOKS (use one naturally after you get permission):
  A: "{context.get('hook_1', '')}"
  B: "{context.get('hook_2', '')}"

LIKELY PAIN POINTS: {pain_points_str}

GOOD DISCOVERY QUESTIONS:
{starters_str}
=== END PRE-CALL INTEL ===

"""


def build_dynamic_swml(context, base_prompt_path="prompts/paul.txt",
                       voice="openai.onyx",
                       webhook_url="https://hooks.6eyes.dev/voice-caller/post-call"):
    """
    Build SWML with per-call context prepended to an existing prompt file.
    Works with prompts/paul.txt, prompts/cold_outreach.txt, or any prompt file.
    """
    # Load base prompt
    full_path = Path(__file__).resolve().parent / base_prompt_path
    if full_path.exists():
        base_prompt = full_path.read_text().strip()
    else:
        base_prompt = "You are Paul, calling on behalf of Samson at Fortinet."

    # Prepend account context
    preamble = build_context_preamble(context)
    prompt_text = preamble + base_prompt

    post_prompt = (
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
        "- Gatekeeper name: [if applicable, else 'none']\n"
        "- Notes: [anything else useful]"
    )

    # Build a personalized static greeting using the account context
    account_name = context.get("_account_name", "")
    hook = context.get("hook_1", "")
    if account_name and hook:
        # Use research-generated hook as the static greeting (max 200 chars)
        static_greeting = hook[:200]
    else:
        static_greeting = (
            "Hi there! This is Paul calling from Fortinet. "
            "I'm reaching out about network security solutions. "
            "Do you have just a minute?"
        )

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "languages": [
                            {
                                # Note: "speed" field is INVALID — omitted intentionally
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
                            "text": post_prompt
                        },
                        "post_prompt_url": webhook_url,
                        "params": {
                            # FIX 2026-03-03: wait_for_user defaults to True on outbound calls.
                            # Without these params, agent waits for remote party to speak → silence.
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "start_paused": False,
                            "static_greeting": static_greeting,
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


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 research_agent.py <account_name> <state> [account_type]")
        print("Example: python3 research_agent.py 'Tripp-Delmont School District' 'South Dakota' 'Education'")
        sys.exit(1)

    account = sys.argv[1]
    state = sys.argv[2]
    acct_type = sys.argv[3] if len(sys.argv) > 3 else "Education"

    context = research_account(account, state, acct_type)
    print("\n=== RESEARCH RESULT ===")
    print(json.dumps(context, indent=2))

    print("\n=== GENERATED SWML PROMPT (first 500 chars) ===")
    swml = build_dynamic_swml(context)
    prompt = swml["sections"]["main"][0]["ai"]["prompt"]["text"]
    print(prompt[:500])
    print(f"\n... [{len(prompt)} total chars]")
