#!/usr/bin/env python3
"""
research_agent.py — Pre-call account research routed through the House AI Gateway.

MIGRATION NOTE (2026-03-14):
  This is the gateway-routed version. Inference is routed through LiteLLM at
  LITELLM_BASE_URL using virtual key LITELLM_VOICE_CALLER_KEY and model alias
  `research-brain` (perplexity/sonar → grok-3 fallback, configured in gateway
  config.yaml). Decision 013: this is the ONLY file with direct AI API calls.

  Backward compatibility: if LITELLM_BASE_URL is not set, falls back to the
  original direct OpenRouter + OpenAI path so migration can be gradual.

  Circuit breaker: 3 consecutive non-200 gateway responses within this process
  trip the breaker — subsequent calls use generic context instead of hitting
  the gateway. The campaign continues without interruption.

Usage:
  # Research a single account
  python3 research_agent.py "Aberdeen Catholic School System" "South Dakota" "Education"

  # Import as module
  from research_agent import research_account, build_dynamic_swml
  context = research_account("Tripp-Delmont School District", "South Dakota", "Education")
  swml = build_dynamic_swml(context)

Requires (gateway mode — preferred):
  LITELLM_BASE_URL=http://<gateway-tailscale-ip>:4000
  LITELLM_VOICE_CALLER_KEY=sk-...  (virtual key provisioned in LiteLLM)

Requires (legacy fallback mode — used if LITELLM_BASE_URL is unset):
  OPENROUTER_API_KEY in .env or environment
  OPENAI_API_KEY in .env or environment (fallback)
"""

import json
import os
import re
import subprocess
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

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

# ─── Gateway Config (primary) ────────────────────────────────────

# LiteLLM gateway endpoint. Set to Tailscale IP of the M4 Mini gateway.
# Example: http://100.x.x.x:4000
LITELLM_BASE_URL         = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
LITELLM_VOICE_CALLER_KEY = os.environ.get("LITELLM_VOICE_CALLER_KEY", "")
# Research uses a dedicated key scoped to research-brain model (Decision 024)
# Falls back to LITELLM_VOICE_CALLER_KEY if not set (backward compat)
LITELLM_RESEARCH_KEY     = os.environ.get("LITELLM_RESEARCH_KEY", "") or LITELLM_VOICE_CALLER_KEY

# Model alias — gateway routes `research-brain` → perplexity/sonar → grok-3 fallback
GATEWAY_MODEL  = "research-brain"
GATEWAY_URL    = f"{LITELLM_BASE_URL}/chat/completions" if LITELLM_BASE_URL else ""

# Whether gateway mode is active (both vars must be set)
GATEWAY_ENABLED = bool(LITELLM_BASE_URL and LITELLM_RESEARCH_KEY)

# ─── Legacy Config (fallback when LITELLM_BASE_URL is unset) ─────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")

# OpenRouter model: Perplexity Sonar (web-grounded, ~$1/1M tokens)
OPENROUTER_MODEL = "perplexity/sonar"
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"

# Fallback: OpenAI-compatible endpoint (configured for xAI Grok)
OPENAI_URL   = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "grok-4-fast-non-reasoning"  # xAI grok-4-fast-non-reasoning via OPENAI_BASE_URL=https://api.x.ai/v1

# XAI direct fallback — used when LiteLLM gateway is down/auth-invalid
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_URL     = "https://api.x.ai/v1/chat/completions"
XAI_MODEL   = "grok-3-mini"  # fast, cheap, capable for research

# ─── Circuit Breaker (module-level, per-process) ─────────────────
# Tracks consecutive gateway failures. After CIRCUIT_BREAKER_THRESHOLD failures,
# _gateway_tripped = True and all remaining calls in this process use generic context.
# Resets to 0 on any successful gateway call.

CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN = 300  # seconds before auto-reset after trip

_gateway_consecutive_failures: int = 0
_gateway_tripped: bool = False
_gateway_tripped_at: float = 0.0  # time.time() when tripped


def _cb_record_success():
    """Record a successful gateway call — resets consecutive failure count and un-trips breaker."""
    global _gateway_consecutive_failures, _gateway_tripped, _gateway_tripped_at
    _gateway_consecutive_failures = 0
    if _gateway_tripped:
        _gateway_tripped = False
        _gateway_tripped_at = 0.0
        print("\n✅ [circuit-breaker] Gateway recovered — resuming normal routing.")


def _cb_record_failure():
    """Record a gateway failure. Returns True if the breaker just tripped."""
    global _gateway_consecutive_failures, _gateway_tripped, _gateway_tripped_at
    _gateway_consecutive_failures += 1
    if _gateway_consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD and not _gateway_tripped:
        _gateway_tripped = True
        _gateway_tripped_at = time.time()
        print(
            f"\n⚡ [circuit-breaker] TRIPPED after {_gateway_consecutive_failures} consecutive"
            f" gateway failures. Will auto-retry in {CIRCUIT_BREAKER_COOLDOWN}s."
        )
        return True
    return False


def _cb_is_tripped() -> bool:
    global _gateway_tripped, _gateway_tripped_at, _gateway_consecutive_failures
    if _gateway_tripped and _gateway_tripped_at > 0:
        elapsed = time.time() - _gateway_tripped_at
        if elapsed >= CIRCUIT_BREAKER_COOLDOWN:
            print(
                f"\n🔄 [circuit-breaker] Cooldown expired ({elapsed:.0f}s). "
                f"Resetting — next call will retry the gateway."
            )
            _gateway_tripped = False
            _gateway_tripped_at = 0.0
            _gateway_consecutive_failures = 0
            return False
    return _gateway_tripped


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


# ─── Gateway Research Function ────────────────────────────────────

def research_via_gateway(account_name, state, account_type):
    """
    Route research through the House AI LiteLLM gateway.
    Uses model alias `research-brain` — gateway handles Sonar → Grok-3 fallback.
    Updates circuit-breaker state on success/failure.
    Returns parsed dict on success, None on any failure.
    """
    if not GATEWAY_ENABLED:
        return None

    if _cb_is_tripped():
        # Breaker already tripped — don't even try
        return None

    prompt = RESEARCH_PROMPT.format(
        account_name=account_name, state=state, account_type=account_type
    )

    try:
        response = requests.post(
            GATEWAY_URL,
            headers={
                "Authorization": f"Bearer {LITELLM_RESEARCH_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GATEWAY_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a B2B sales research assistant. Return only valid JSON, no markdown formatting."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=90  # sonar can be slow; matches gateway config.yaml timeout
        )

        if response.status_code != 200:
            print(
                f"  [research] Gateway returned {response.status_code}: "
                f"{response.text[:200]}"
            )
            _cb_record_failure()
            return None

        content = response.json()["choices"][0]["message"]["content"]
        result = parse_research_json(content)
        if result:
            _cb_record_success()
            return result
        else:
            # Parsed but invalid JSON from model — still counts as failure
            _cb_record_failure()
            return None

    except requests.exceptions.ConnectionError as e:
        print(f"  [research] Gateway unreachable ({LITELLM_BASE_URL}): {e}")
        _cb_record_failure()
        return None
    except requests.exceptions.Timeout:
        print(f"  [research] Gateway timed out after 90s")
        _cb_record_failure()
        return None
    except Exception as e:
        print(f"  [research] Gateway call failed: {e}")
        _cb_record_failure()
        return None


# ─── Legacy Research Functions (fallback when LITELLM_BASE_URL unset) ──

def research_via_openrouter(account_name, state, account_type):
    """Research account using OpenRouter → Perplexity Sonar (web-grounded).
    LEGACY PATH — only used when LITELLM_BASE_URL is not configured."""
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
    """Fallback: research using OpenAI (no web grounding).
    LEGACY PATH — only used when LITELLM_BASE_URL is not configured."""
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


def research_via_xai(account_name, state, account_type):
    """Research account using XAI Grok directly. Used as gateway fallback.
    Only activates when gateway is configured but failing (auth error, timeout, etc.)."""
    if not XAI_API_KEY:
        return None
    prompt = RESEARCH_PROMPT.format(
        account_name=account_name, state=state, account_type=account_type
    )
    try:
        response = requests.post(
            XAI_URL,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a B2B sales research assistant. Return only valid JSON, no markdown formatting."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=45
        )
        if response.status_code != 200:
            print(f"  [research] XAI returned {response.status_code}: {response.text[:100]}")
            return None
        content = response.json()["choices"][0]["message"]["content"]
        return parse_research_json(content)
    except Exception as e:
        print(f"  [research] XAI fallback failed: {e}")
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


# ─── BigQuery Cache (L2) ─────────────────────────────────────────

BQ_PROJECT   = "tatt-pro"
BQ_DATASET   = "sled_intelligence"
BQ_TABLE     = "research_cache"
BQ_TABLE_REF = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
L1_TTL_DAYS  = 7
L2_TTL_DAYS  = 30


def _stable_cache_key(account_name: str, state: str, sf_account_id: str = "") -> str:
    """
    Build a collision-resistant cache key.
    Priority: sf_account_id (opaque SFDC ID, perfectly stable)
              → state + normalized account name (removes punctuation, lowercased)
    Never key by raw account_name alone — names collide across states.
    """
    if sf_account_id:
        return sf_account_id  # e.g. "001Hr00000XYZabcIAE"
    normalized = re.sub(r"[^\w]", "_", account_name.lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")[:60]
    state_clean = re.sub(r"[^\w]", "", state.lower())[:4]
    return f"{state_clean}__{normalized}"


def _check_json_ttl(data: dict, max_days: int) -> bool:
    """Return True if _cached_at in data is within max_days. Always reads from JSON field, not filesystem mtime."""
    cached_at = data.get("_cached_at", "")
    if not cached_at:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
        return age < max_days * 86400
    except Exception:
        return False


def _bq_client():
    """Return a BigQuery client for tatt-pro using ADC. Cached at module level."""
    if not hasattr(_bq_client, "_instance"):
        from google.cloud import bigquery as _bq
        _bq_client._instance = _bq.Client(project=BQ_PROJECT)
    return _bq_client._instance


def _bq_ensure_table() -> bool:
    """
    Create research_cache table in sled_intelligence if it doesn't exist.
    Returns True on success, False on any failure (best-effort).
    Schema uses BigQuery JSON type for full_json payload.
    """
    try:
        from google.cloud import bigquery as _bq
        from google.cloud.exceptions import NotFound
        client = _bq_client()
        table_ref = client.dataset(BQ_DATASET).table(BQ_TABLE)
        try:
            client.get_table(table_ref)
            return True  # already exists
        except NotFound:
            pass
        schema = [
            _bq.SchemaField("account_id",    "STRING",    mode="REQUIRED",
                            description="Cache key: sf_account_id or state__normalized_name"),
            _bq.SchemaField("account_name",  "STRING",    description="Human-readable account name"),
            _bq.SchemaField("sf_account_id", "STRING",    description="Salesforce Account ID if known"),
            _bq.SchemaField("state",         "STRING"),
            _bq.SchemaField("account_type",  "STRING"),
            _bq.SchemaField("researched_at", "TIMESTAMP", mode="REQUIRED",
                            description="Canonical TTL anchor — always read from this field"),
            _bq.SchemaField("source",        "STRING",    description="openrouter/sonar | openai/gpt-4o-mini | generic"),
            _bq.SchemaField("summary",       "STRING"),
            _bq.SchemaField("contacts_json", "STRING",    description="JSON array of discovered contacts"),
            _bq.SchemaField("full_json",     "JSON",      description="Full research payload"),
        ]
        table = _bq.Table(table_ref, schema=schema)
        table.description = "AI pre-call research cache — shared L2 across all machines"
        client.create_table(table)
        print(f"  [research] Created BQ table {BQ_TABLE_REF}")
        return True
    except Exception as e:
        print(f"  [research] BQ table ensure failed (non-fatal): {e}")
        return False


def _bq_pull(cache_key: str) -> dict | None:
    """
    Best-effort: query BigQuery for existing research within L2_TTL_DAYS.
    TTL evaluated from researched_at column — never BQ ingestion time.
    Returns parsed dict on hit, None on miss/stale/any failure.
    Never raises — cache infra must never block calling.
    """
    try:
        client = _bq_client()
        query = f"""
            SELECT full_json, researched_at
            FROM `{BQ_TABLE_REF}`
            WHERE account_id = @account_id
              AND researched_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {L2_TTL_DAYS} DAY)
            ORDER BY researched_at DESC
            LIMIT 1
        """
        from google.cloud import bigquery as _bq
        job_config = _bq.QueryJobConfig(
            query_parameters=[
                _bq.ScalarQueryParameter("account_id", "STRING", cache_key)
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())
        if not rows:
            return None
        raw = rows[0]["full_json"]
        # BQ JSON type comes back as string; parse it
        data = json.loads(raw) if isinstance(raw, str) else raw
        # Belt-and-suspenders: validate TTL from the JSON's own _cached_at field
        if not _check_json_ttl(data, L2_TTL_DAYS):
            return None
        # Never serve cached generic_fallback — it's a failure signal, not real research
        if data.get("_source") == "generic_fallback":
            return None
        return data
    except Exception as e:
        print(f"  [research] BQ L2 pull failed (non-fatal): {e}")
        return None


def _bq_push(result: dict) -> None:
    """
    Best-effort: stream-insert research result into BigQuery L2.
    Never raises — cache infra must never block calling.
    Structured fields stored in dedicated columns; full payload in full_json.
    """
    try:
        _bq_ensure_table()
        client = _bq_client()
        contacts = result.get("contacts", [])
        row = {
            "account_id":    result.get("_cache_key", ""),
            "account_name":  result.get("account_name", ""),
            "sf_account_id": result.get("sf_account_id", ""),
            "state":         result.get("state", ""),
            "account_type":  result.get("account_type", ""),
            # Use _cached_at from JSON as canonical researched_at (constraint #2)
            "researched_at": result.get("_cached_at", datetime.now(timezone.utc).isoformat()),
            "source":        result.get("_source", "unknown"),
            "summary":       result.get("summary", ""),
            "contacts_json": json.dumps(contacts),
            "full_json":     json.dumps(result),
        }
        errors = client.insert_rows_json(BQ_TABLE_REF, [row])
        if errors:
            print(f"  [research] BQ push insert errors (non-fatal): {errors}")
    except Exception as e:
        print(f"  [research] BQ L2 push failed (non-fatal): {e}")


# ─── Core Research Function ───────────────────────────────────────

def research_account(account_name, state, account_type="Education", sf_account_id=""):
    """
    Research an account using the House AI Gateway (primary) or direct API (legacy fallback).

    Gateway mode (LITELLM_BASE_URL set):
      → requests.post(LITELLM_BASE_URL/chat/completions, model=research-brain)
      → gateway routes: perplexity/sonar → grok-3 fallback (Decision 003)
      → circuit-breaker trips after 3 consecutive non-200 responses (Decision 014)

    Legacy mode (LITELLM_BASE_URL unset):
      → OpenRouter (Perplexity Sonar) → OpenAI (xAI Grok) fallback

    Last resort (all providers fail, or circuit-breaker tripped):
      → generic context — campaign continues with non-personalized prompts

    Cache hierarchy (never blocks calling on failure):
      L1 — local  campaigns/.research_cache/{key}.json  TTL: 7 days
      L2 — BigQuery sled_intelligence.research_cache     TTL: 30 days
      MISS — call inference provider → write L1 + L2

    Cache key: sf_account_id (preferred) or state__normalized_name (collision-safe).
    TTL evaluated from JSON's _cached_at field, not filesystem timestamp.
    """
    cache_dir = Path(__file__).resolve().parent / "campaigns" / ".research_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_key = _stable_cache_key(account_name, state, sf_account_id)
    cache_file = cache_dir / f"{cache_key}.json"

    # --- L1: local cache ---
    if cache_file.exists():
        if os.path.getmtime(cache_file) < time.time() - (30 * 86400):
            try:
                cache_file.unlink()
                print(f"  [research] L1 stale cache removed: {cache_file.name}")
            except Exception:
                pass
        try:
            if cache_file.exists():
                cached = json.loads(cache_file.read_text())
                if _check_json_ttl(cached, L1_TTL_DAYS):
                    print(f"  [research] L1 hit: {account_name} (key={cache_key})")
                    cached.setdefault("account_name", account_name)
                    cached.setdefault("state", state)
                    return cached
        except Exception:
            pass

    # --- L2: BigQuery sled_intelligence.research_cache ---
    bq_data = _bq_pull(cache_key)
    if bq_data:
        print(f"  [research] L2 BQ hit: {account_name} (key={cache_key})")
        bq_data.setdefault("account_name", account_name)
        bq_data.setdefault("state", state)
        # Repopulate L1 from BQ hit so next call is local-fast
        try:
            cache_file.write_text(json.dumps(bq_data, indent=2))
        except Exception:
            pass
        return bq_data

    # --- MISS: run inference ---
    print(f"  [research] Cache miss — researching: {account_name} ({state}, {account_type})")

    def _cache_and_return(result):
        result["account_name"] = account_name
        result["state"] = state
        result["account_type"] = account_type
        result["_cache_key"] = cache_key
        if sf_account_id:
            result["sf_account_id"] = sf_account_id
        result["_cached_at"] = datetime.now(timezone.utc).isoformat()
        # Never cache generic_fallback — it's a signal of failure, not real research
        if result.get("_source") == "generic_fallback":
            return result
        # Write L1 — always, fast
        try:
            cache_file.write_text(json.dumps(result, indent=2))
        except Exception:
            pass
        # Write L2 BigQuery — best-effort, never blocks calling
        _bq_push(result)
        return result

    # ── Gateway path (preferred when LITELLM_BASE_URL is set) ──────
    if GATEWAY_ENABLED:
        if not _cb_is_tripped():
            result = research_via_gateway(account_name, state, account_type)
            if result:
                result["_source"] = "gateway/research-brain"
                print(f"  [research] Got context via gateway: {result.get('summary', '')[:80]}...")
                return _cache_and_return(result)
        # Gateway failed or circuit breaker tripped — fall through to XAI direct
        if _cb_is_tripped() or not result:
            print(f"  [research] Gateway unavailable — trying XAI direct fallback...")
            result = research_via_xai(account_name, state, account_type)
            if result:
                result["_source"] = "xai/grok-3-mini-fallback"
                print(f"  [research] Got context via XAI fallback: {result.get('summary', '')[:80]}...")
                return _cache_and_return(result)
            # XAI also failed — use generic context so campaign can continue
            print(f"  [research] All providers failed for {account_name}, using generic context")
        # Decision updated 2026-03-18: fall through to generic context (don't hard-fail)
        # Gateway key rotation happened; using generic is better than dropping calls

    # ── Legacy path (only when LITELLM_BASE_URL is NOT configured) ─
    elif not GATEWAY_ENABLED:
        # Try OpenRouter (Perplexity Sonar) first — web-grounded
        result = research_via_openrouter(account_name, state, account_type)
        if result:
            result["_source"] = "openrouter/sonar"
            print(f"  [research] Got context via Sonar: {result.get('summary', '')[:80]}...")
            return _cache_and_return(result)

        # Fallback to XAI Grok directly
        result = research_via_xai(account_name, state, account_type)
        if result:
            result["_source"] = "xai/grok-3-mini"
            print(f"  [research] Got context via XAI: {result.get('summary', '')[:80]}...")
            return _cache_and_return(result)

        # Fallback to OpenAI / xAI Grok
        result = research_via_openai(account_name, state, account_type)
        if result:
            result["_source"] = "openai/gpt-4o-mini"
            print(f"  [research] Got context via OpenAI: {result.get('summary', '')[:80]}...")
            return _cache_and_return(result)

    # ── Last resort: generic context — campaign keeps running ───────
    print(f"  [research] All providers failed, using generic context for {account_name}")
    result = {
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
    return _cache_and_return(result)


# ─── Circuit Breaker Status (for campaign_runner_v2 to inspect) ──

def get_circuit_breaker_status() -> dict:
    """Return current circuit breaker state for campaign-level logging."""
    return {
        "tripped": _gateway_tripped,
        "consecutive_failures": _gateway_consecutive_failures,
        "threshold": CIRCUIT_BREAKER_THRESHOLD,
        "gateway_enabled": GATEWAY_ENABLED,
        "gateway_url": GATEWAY_URL or "(none — legacy mode)",
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

def parse_agent_name(prompt_path: str) -> str:
    """Read first prompt line and parse '# AGENT_NAME: <Name>'."""
    full_path = Path(__file__).resolve().parent / prompt_path
    try:
        with open(full_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
    except Exception:
        return "Paul"

    match = re.match(r"^#\s*AGENT_NAME:\s*(.+?)\s*$", first_line)
    if match:
        return match.group(1).strip()
    return "Paul"

# ─── SFDC History Lookup ──────────────────────────────────────────

SF_ALIAS = "fortinet"


def _sf_query(soql: str) -> list:
    """Run a SOQL query via sf CLI. Returns list of record dicts, or [] on failure."""
    try:
        proc = subprocess.run(
            ["sf", "data", "query", "--query", soql, "--json", "--target-org", SF_ALIAS],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return []
        return json.loads(proc.stdout).get("result", {}).get("records", [])
    except Exception:
        return []


def lookup_sfdc_history(account_name: str, sf_account_id: str = "") -> Optional[Dict]:
    """
    Pull relationship history from SFDC for an account.
    Returns dict with last_activity, open_opp, contacts, or None if not found.
    Best-effort — never blocks the call if SFDC is unreachable.
    """
    escaped = account_name.replace("'", "\\'")

    # Find the account
    if sf_account_id:
        acct_records = _sf_query(
            f"SELECT Id, Name, LastActivityDate, OwnerId FROM Account WHERE Id = '{sf_account_id}' LIMIT 1"
        )
    else:
        acct_records = _sf_query(
            f"SELECT Id, Name, LastActivityDate, OwnerId FROM Account WHERE Name = '{escaped}' LIMIT 1"
        )

    if not acct_records:
        return None

    acct = acct_records[0]
    acct_id = acct.get("Id", "")
    result = {
        "sfdc_account_id": acct_id,
        "last_activity_date": acct.get("LastActivityDate"),
    }

    # Recent tasks (last 3 call outcomes)
    tasks = _sf_query(
        f"SELECT Subject, Description, ActivityDate FROM Task "
        f"WHERE WhatId = '{acct_id}' AND Status = 'Completed' "
        f"ORDER BY ActivityDate DESC LIMIT 3"
    )
    if tasks:
        result["recent_tasks"] = [
            {"subject": t.get("Subject", ""), "date": t.get("ActivityDate", ""),
             "note": (t.get("Description") or "")[:150]}
            for t in tasks
        ]

    # Open opportunities
    opps = _sf_query(
        f"SELECT Name, StageName, Amount, CloseDate FROM Opportunity "
        f"WHERE AccountId = '{acct_id}' AND IsClosed = false LIMIT 1"
    )
    if opps:
        opp = opps[0]
        result["open_opp"] = {
            "name": opp.get("Name", ""),
            "stage": opp.get("StageName", ""),
            "amount": opp.get("Amount"),
            "close_date": opp.get("CloseDate", ""),
        }

    # Contacts on the account
    contacts = _sf_query(
        f"SELECT Name, Title, Email, Phone FROM Contact "
        f"WHERE AccountId = '{acct_id}' ORDER BY LastModifiedDate DESC LIMIT 3"
    )
    if contacts:
        result["sfdc_contacts"] = [
            {"name": c.get("Name", ""), "title": c.get("Title", ""),
             "email": c.get("Email"), "phone": c.get("Phone")}
            for c in contacts
        ]

    return result


def _format_sfdc_history(history: Optional[Dict]) -> str:
    """Format SFDC history into a block for the prompt preamble."""
    if not history:
        return "No prior SFDC history found."

    lines = []
    if history.get("last_activity_date"):
        lines.append(f"Last activity: {history['last_activity_date']}")

    if history.get("recent_tasks"):
        for t in history["recent_tasks"]:
            note = f" — {t['note']}" if t["note"] else ""
            lines.append(f"  • {t['date']}: {t['subject']}{note}")

    if history.get("open_opp"):
        opp = history["open_opp"]
        amt = f"${opp['amount']:,.0f}" if opp.get("amount") else "no amount"
        lines.append(f"OPEN DEAL: {opp['name']} | Stage: {opp['stage']} | {amt} | Close: {opp['close_date']}")

    if history.get("sfdc_contacts"):
        for c in history["sfdc_contacts"]:
            title = f" ({c['title']})" if c.get("title") else ""
            lines.append(f"  Contact: {c['name']}{title}")

    return "\n".join(lines) if lines else "No prior SFDC history found."


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

    # SFDC history — pull relationship context if available
    sfdc_history = context.get("_sfdc_history")
    sfdc_block = _format_sfdc_history(sfdc_history)

    return f"""=== YOU ARE CALLING: {location.upper()} ===
This is the account. Know this name. Reference it naturally.

=== YOUR RELATIONSHIP HISTORY (from Salesforce) ===
{sfdc_block}
=== END RELATIONSHIP HISTORY ===

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

    NOTE: SignalWire SWML ai_model, asr_engine, voice, and all SignalWire params
    are intentionally NOT routed through the LiteLLM gateway (Decision 002).
    These are SignalWire-managed inference — separate billing, separate control plane.
    """
    # Load base prompt
    full_path = Path(__file__).resolve().parent / base_prompt_path
    if full_path.exists():
        base_prompt = full_path.read_text().strip()
    else:
        base_prompt = "You are Paul, calling on behalf of Samson at Fortinet."

    # Enrich with SFDC history if not already present
    if "_sfdc_history" not in context:
        try:
            sfdc_hist = lookup_sfdc_history(
                context.get("account_name", ""),
                sf_account_id=context.get("sf_account_id", ""),
            )
            if sfdc_hist:
                context["_sfdc_history"] = sfdc_hist
                print(f"  [sfdc] Attached history: last_activity={sfdc_hist.get('last_activity_date', 'none')}"
                      f", open_opp={'yes' if sfdc_hist.get('open_opp') else 'no'}"
                      f", contacts={len(sfdc_hist.get('sfdc_contacts', []))}")
        except Exception as e:
            print(f"  [sfdc] History lookup failed (non-blocking): {e}")

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
    agent_name = parse_agent_name(base_prompt_path)
    account_name = context.get("account_name", "")
    hook = context.get("hook_1", "")
    if account_name and hook:
        # Use research-generated hook as the static greeting (max 200 chars)
        static_greeting = hook[:200]
    else:
        static_greeting = (
            f"Hi there! This is {agent_name} calling from Fortinet. "
            "I'm reaching out about network security solutions. "
            "Do you have just a minute?"
        )

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                # answer verb REQUIRED before ai — establishes audio path
                {"answer": {}},
                {"record_call": {"stereo": True, "format": "mp3"}},
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
                            # NOTE: ai_model is SignalWire's parameter — NOT routable through our gateway
                            # (Decision 002). SignalWire runs this on their own infrastructure.
                            "ai_model": "gpt-4o-mini",
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "static_greeting": static_greeting,
                            "static_greeting_no_barge": True,
                            "acknowledge_interruptions": True,
                            "enable_thinking": True,
                            "hard_stop_time": "5m",
                            # attention_timeout (not outbound_attention_timeout — invalid param)
                            "attention_timeout": 60000,
                            "inactivity_timeout": 60000,
                            "end_of_speech_timeout": 2000,
                            # asr_engine format: "provider:model" colon-separated string
                            # NOT a nested engine.asr object (was causing silent AI failure)
                            "asr_engine": "deepgram:nova-3"
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

    # Print routing info
    if GATEWAY_ENABLED:
        print(f"[gateway] Routing through: {GATEWAY_URL}")
        print(f"[gateway] Model alias: {GATEWAY_MODEL}")
    else:
        print("[legacy] LITELLM_BASE_URL not set — using direct OpenRouter/OpenAI")

    context = research_account(account, state, acct_type)
    print("\n=== RESEARCH RESULT ===")
    print(json.dumps(context, indent=2))

    print("\n=== CIRCUIT BREAKER STATUS ===")
    print(json.dumps(get_circuit_breaker_status(), indent=2))

    print("\n=== GENERATED SWML PROMPT (first 500 chars) ===")
    swml = build_dynamic_swml(context)
    # main[0] is now {"answer": {}}, main[2] is the ai block
    ai_block = next(s for s in swml["sections"]["main"] if "ai" in s)
    prompt = ai_block["ai"]["prompt"]["text"]
    print(prompt[:500])
    print(f"\n... [{len(prompt)} total chars]")
