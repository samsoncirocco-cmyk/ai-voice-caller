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
import sys
import time
import requests
from pathlib import Path

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
  "it_contact": "Name and title of IT director/manager if findable, otherwise 'Unknown'",
  "hook_1": "A specific, personalized opening line referencing something current about this org (hiring, budget, news, E-Rate, board decision, tech upgrade). Must be conversational, not salesy.",
  "hook_2": "A second alternative opening hook using different intel",
  "pain_points": ["list", "of", "likely", "infrastructure", "pain", "points"],
  "tech_intel": "Any known technology vendors, current firewall/network equipment, or recent RFPs",
  "budget_cycle": "When their fiscal year starts, any known budget timelines or E-Rate filing windows",
  "conversation_starters": ["2-3 open-ended questions that would reveal their network security needs"]
}}

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
    """
    print(f"  [research] Researching: {account_name} ({state}, {account_type})")

    # Try OpenRouter (Perplexity Sonar) first — web-grounded
    result = research_via_openrouter(account_name, state, account_type)
    if result:
        result["_source"] = "openrouter/sonar"
        print(f"  [research] Got context via Sonar: {result.get('summary', '')[:80]}...")
        return result

    # Fallback to OpenAI
    result = research_via_openai(account_name, state, account_type)
    if result:
        result["_source"] = "openai/gpt-4o-mini"
        print(f"  [research] Got context via OpenAI: {result.get('summary', '')[:80]}...")
        return result

    # Last resort: generic context
    print(f"  [research] All providers failed, using generic context")
    return {
        "summary": f"{account_name} is a {account_type.lower()} organization in {state}.",
        "it_contact": "Unknown",
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


# ─── Dynamic SWML Builder ───────────────────────────────────────

def build_context_preamble(context):
    """
    Build a context block to prepend to any prompt file (paul.txt, cold_outreach.txt).
    This injects per-account intel without replacing the base prompt.
    """
    pain_points_str = ", ".join(context.get("pain_points", []))
    starters_str = "\n".join(f"  - {q}" for q in context.get("conversation_starters", []))

    return f"""=== PRE-CALL INTEL (use this to personalize your approach) ===
ACCOUNT: {context.get('summary', 'No specific intel available.')}
IT CONTACT: {context.get('it_contact', 'Unknown — your first goal is to identify them.')}
TECH INTEL: {context.get('tech_intel', 'Unknown')}
BUDGET CYCLE: {context.get('budget_cycle', 'Unknown')}

PERSONALIZED HOOKS (weave one into your opening naturally):
  A: "{context.get('hook_1', '')}"
  B: "{context.get('hook_2', '')}"

LIKELY PAIN POINTS: {pain_points_str}

GOOD DISCOVERY QUESTIONS FOR THIS ACCOUNT:
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
        "- Spoke with: [name or 'unknown']\n"
        "- Role: [title/role]\n"
        "- Organization: [org name]\n"
        "- Current setup: [what they said about their current IT/security setup]\n"
        "- Pain points: [any frustrations or challenges mentioned]\n"
        "- Current vendor: [if mentioned]\n"
        "- Interest level: [1-5]\n"
        "- Follow-up: [what was agreed, or 'none']\n"
        "- Meeting booked: [yes/no, and datetime if yes]\n"
        "- Contact email: [if collected]\n"
        "- Contact direct phone: [if collected]\n"
        "- Gatekeeper name: [if applicable]\n"
        "- Notes: [anything else useful]"
    )

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "languages": [
                            {
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
                            "direction": "outbound"
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
