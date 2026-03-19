#!/usr/bin/env python3
"""
precache_blitz.py — Pre-cache research for all accounts in a blitz CSV.

Run this the night before a call campaign to pre-load L1 cache for all targets.
On campaign day, every call will hit L1 cache instead of waiting for API.

Usage:
  python3 precache_blitz.py campaigns/blitz-mar19-2026-v2.csv
  python3 precache_blitz.py campaigns/blitz-mar19-2026-v2.csv --limit 10
  python3 precache_blitz.py campaigns/blitz-mar19-2026-v2.csv --dry-run
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# Load .env
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from research_agent import research_account, get_circuit_breaker_status

ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def vertical_from_call_type(call_type: str, account_name: str) -> str:
    """Infer vertical from call_type and account name."""
    ct = call_type.lower()
    name = account_name.lower()
    
    if "erate" in ct or "school" in name or "district" in name or "lutheran" in name or "christian" in name or "academy" in name or "university" in name or "college" in name:
        return "Education"
    if "gov" in ct or "county" in name or "city of" in name or "municipal" in name or "rec" in name or "library" in name:
        return "Government"
    return "Education"  # default for unknown


def state_fullname(state_abbr: str) -> str:
    mapping = {
        "SD": "South Dakota",
        "NE": "Nebraska", 
        "IA": "Iowa",
    }
    # If already full name, return as-is
    if state_abbr in mapping.values():
        return state_abbr
    return mapping.get(state_abbr.upper(), state_abbr)


def main():
    parser = argparse.ArgumentParser(description="Pre-cache research for a blitz CSV")
    parser.add_argument("csv_file", help="Path to blitz CSV file")
    parser.add_argument("--limit", type=int, default=None, help="Max accounts to research")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be researched, don't call API")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between API calls (default: 3.0)")
    parser.add_argument("--skip-cached", action="store_true", default=True, help="Skip already-cached accounts (default: True)")
    parser.add_argument("--force", action="store_true", help="Force re-research even if cached")
    args = parser.parse_args()

    if args.force:
        args.skip_cached = False

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"📋 Loaded {len(rows)} accounts from {csv_path.name}")
    print(f"   Delay: {args.delay}s between calls")
    print(f"   Skip cached: {args.skip_cached}")
    if args.dry_run:
        print("   *** DRY RUN — no API calls ***")
    print()

    # Show gateway status
    cb = get_circuit_breaker_status()
    if cb["gateway_enabled"]:
        print(f"🌐 Gateway: {cb['gateway_url']} (model: research-brain)")
    else:
        print("⚠️  Gateway not configured — using legacy OpenRouter/OpenAI")
    print()

    cache_dir = BASE_DIR / "campaigns" / ".research_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    targets = rows[:args.limit] if args.limit else rows

    success = 0
    cached_hits = 0
    failed = 0
    skipped = 0

    for i, row in enumerate(targets):
        account_name = row.get("account_name", "").strip()
        state_raw = row.get("state", "SD").strip()
        call_type = row.get("call_type", "erate").strip()
        state = state_fullname(state_raw)
        vertical = vertical_from_call_type(call_type, account_name)

        if not account_name:
            skipped += 1
            continue

        # Check L1 cache (quick file check, no API)
        from research_agent import _stable_cache_key, _check_json_ttl
        import re
        cache_key = _stable_cache_key(account_name, state, "")
        cache_file = cache_dir / f"{cache_key}.json"

        if args.skip_cached and not args.force and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                if _check_json_ttl(cached, 7) and cached.get("_source") != "generic_fallback":
                    print(f"[{i+1}/{len(targets)}] ✓ CACHED  {account_name}")
                    cached_hits += 1
                    continue
            except Exception:
                pass

        print(f"[{i+1}/{len(targets)}] 🔍 {account_name} ({state}, {vertical})")

        if args.dry_run:
            print(f"          [DRY RUN] Would research via gateway/API")
            skipped += 1
            continue

        # Run research
        context = research_account(account_name, state, vertical)
        if context and context.get("_source") != "generic_fallback":
            summary = context.get("summary", "")[:80]
            contacts = context.get("contacts", [])
            hook = context.get("hook_1", "")[:60]
            print(f"          ✅ {context['_source']} | contacts={len(contacts)} | hook: {hook}...")
            print(f"             Summary: {summary}")
            success += 1
        elif context and context.get("_source") == "generic_fallback":
            print(f"          ⚠️  Generic fallback (API unavailable)")
            failed += 1
        else:
            print(f"          ❌ Research returned None (gateway hard fail)")
            failed += 1
            # Check if circuit breaker tripped
            cb = get_circuit_breaker_status()
            if cb["tripped"]:
                print(f"\n🛑 Circuit breaker tripped — stopping pre-cache. Fix gateway before campaign.")
                break

        # Rate limiting between API calls
        if i < len(targets) - 1:
            time.sleep(args.delay)

    print()
    print("=" * 60)
    print("PRE-CACHE SUMMARY")
    print(f"  ✅ Researched:  {success}")
    print(f"  ✓  Cached hits: {cached_hits}")
    print(f"  ❌ Failed:      {failed}")
    print(f"  ⏭  Skipped:    {skipped}")
    print(f"  Total:         {len(targets)}")
    print()

    cb = get_circuit_breaker_status()
    if cb["tripped"]:
        print("⚠️  WARNING: Gateway circuit breaker is TRIPPED")
        print("   Run with --skip-cached=False tomorrow to check status")
    elif success + cached_hits == len(targets):
        print("🚀 All accounts pre-cached — tomorrow's blitz is ready to launch!")
    else:
        print(f"⚠️  {failed} accounts have no research context — calls will use generic prompts")
    print("=" * 60)


if __name__ == "__main__":
    main()
