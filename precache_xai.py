#!/usr/bin/env python3
"""
precache_xai.py — Pre-cache research using XAI/Grok directly (bypasses broken LiteLLM gateway).
Run the night before a campaign to ensure all accounts have research context ready.

Usage:
  python3 precache_xai.py campaigns/blitz-mar19-2026-v2.csv
  python3 precache_xai.py campaigns/blitz-mar19-2026-v2.csv --limit 10
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

BASE_DIR = Path(__file__).resolve().parent

# Load .env
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_URL = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-3-mini"  # faster/cheaper than full grok-3

RESEARCH_PROMPT = """Research the following organization for a cold call about network security:

Organization: {account_name}
Location: {state}
Type: {account_type}

Return a JSON object with EXACTLY these fields (no markdown, no backticks, just raw JSON):
{{
  "summary": "2-3 sentence overview of the organization, size, and what they do",
  "contacts": [
    {{
      "name": "Full name if known, else null",
      "title": "Job title (IT Director, Technology Coordinator, Superintendent, etc.)",
      "email": "Email address if publicly available, else null",
      "phone": "Direct phone if publicly available, else null"
    }}
  ],
  "hook_1": "A specific, conversational opening line referencing something current about this org (hiring, budget, E-Rate, tech upgrade, enrollment change). Not salesy.",
  "hook_2": "A second alternative opening hook",
  "pain_points": ["list", "of", "likely", "infrastructure", "pain", "points"],
  "tech_intel": "Any known technology vendors, current firewall/network equipment",
  "budget_cycle": "When their fiscal year starts or typical budget cycle",
  "conversation_starters": ["2-3 open-ended questions that would reveal their network security needs"]
}}

Be factual. If you don't know something, make reasonable inferences based on org type and location.
Return ONLY the JSON object — no markdown, no explanation."""


def _stable_cache_key(account_name: str, state: str, sf_account_id: str = "") -> str:
    if sf_account_id:
        return sf_account_id
    normalized = re.sub(r"[^\w]", "_", account_name.lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")[:60]
    state_clean = re.sub(r"[^\w]", "", state.lower())[:4]
    return f"{state_clean}__{normalized}"


def _state_fullname(state_raw: str) -> str:
    mapping = {"SD": "South Dakota", "NE": "Nebraska", "IA": "Iowa"}
    if state_raw in mapping.values():
        return state_raw
    return mapping.get(state_raw.upper(), state_raw)


def _vertical_from_context(call_type: str, account_name: str) -> str:
    ct = call_type.lower()
    name = account_name.lower()
    if any(x in name for x in ["school", "district", "academy", "college", "university", "lutheran", "christian"]):
        return "Education"
    if any(x in name for x in ["county", "city", "municipal", "library", "tribe"]):
        return "Government"
    if "erate" in ct:
        return "Education"
    return "Education"


def research_with_xai(account_name: str, state: str, account_type: str) -> dict:
    """Research account using XAI Grok. Returns parsed dict or None."""
    prompt = RESEARCH_PROMPT.format(
        account_name=account_name, state=state, account_type=account_type
    )
    try:
        resp = requests.post(
            XAI_URL,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a B2B sales research assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=45
        )
        if resp.status_code != 200:
            print(f"  ❌ XAI returned {resp.status_code}: {resp.text[:100]}")
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        # Strip markdown fences
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()
        data = json.loads(content)
        return data
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse failed: {e}")
        return None
    except Exception as e:
        print(f"  ❌ XAI call failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--force", action="store_true", help="Re-research even if cached")
    args = parser.parse_args()

    if not XAI_API_KEY:
        print("❌ XAI_API_KEY not set in .env")
        sys.exit(1)

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    targets = rows[:args.limit] if args.limit else rows

    cache_dir = BASE_DIR / "campaigns" / ".research_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"📋 {len(targets)} accounts to pre-cache from {csv_path.name}")
    print(f"   Model: {XAI_MODEL} | Delay: {args.delay}s | Force: {args.force}")
    print()

    success = 0
    cached = 0
    failed = 0

    for i, row in enumerate(targets):
        account_name = row.get("account_name", "").strip()
        state_raw = row.get("state", "SD").strip()
        call_type = row.get("call_type", "erate").strip()
        state = _state_fullname(state_raw)
        vertical = _vertical_from_context(call_type, account_name)

        if not account_name:
            continue

        cache_key = _stable_cache_key(account_name, state, "")
        cache_file = cache_dir / f"{cache_key}.json"

        # Skip if fresh cache exists
        if not args.force and cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text())
                cached_at = existing.get("_cached_at", "")
                if cached_at:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
                    if age < 7 * 86400 and existing.get("_source") != "generic_fallback":
                        print(f"[{i+1:2}/{len(targets)}] ✓ CACHED  {account_name[:55]}")
                        cached += 1
                        continue
            except Exception:
                pass

        print(f"[{i+1:2}/{len(targets)}] 🔍 {account_name[:55]} ({state[:2]})")
        
        result = research_with_xai(account_name, state, vertical)
        if result:
            result["account_name"] = account_name
            result["state"] = state
            result["account_type"] = vertical
            result["_source"] = f"xai/{XAI_MODEL}"
            result["_cache_key"] = cache_key
            result["_cached_at"] = datetime.now(timezone.utc).isoformat()
            
            cache_file.write_text(json.dumps(result, indent=2))
            hook = result.get("hook_1", "")[:70]
            contacts_count = len(result.get("contacts", []))
            print(f"          ✅ {contacts_count} contacts | {hook[:70]}")
            success += 1
        else:
            print(f"          ❌ Failed to research")
            failed += 1

        if i < len(targets) - 1:
            time.sleep(args.delay)

    print()
    print("=" * 60)
    print("PRE-CACHE COMPLETE")
    print(f"  ✅ Researched:  {success}")
    print(f"  ✓  From cache:  {cached}")
    print(f"  ❌ Failed:      {failed}")
    print(f"  Total:         {len(targets)}")

    if failed == 0:
        print()
        print("🚀 All accounts ready — blitz is GO for launch!")
    else:
        print(f"\n⚠️  {failed} accounts need retry (run with --force)")
    print("=" * 60)


if __name__ == "__main__":
    main()
