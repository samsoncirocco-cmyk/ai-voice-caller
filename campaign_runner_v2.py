#!/usr/bin/env python3
"""
campaign_runner_v2.py — Research-powered batch caller for Fortinet SLED outreach.

For each lead:
  1. Research account via OpenRouter/Sonar (web-grounded intel)
  2. Build personalized SWML with dynamic prompt
  3. Place call via SignalWire
  4. Wait for post_prompt webhook to capture summary
  5. Log everything to flat files (no Firestore required)

Usage:
  # Dry run — research only, no calls
  python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --dry-run

  # Run 10 calls with 4-minute spacing
  python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --limit 10 --interval 240

  # Resume a paused campaign
  python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --resume

  # Run during business hours only (auto-pauses outside window)
  python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --business-hours

Requires:
  - SignalWire credentials in config/signalwire.json
  - OPENROUTER_API_KEY and/or OPENAI_API_KEY in .env
  - webhook_server.py running on hooks.6eyes.dev
"""

import argparse
import base64
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Add parent to path for research_agent import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_agent import research_account, build_dynamic_swml

DEFAULT_PROMPT = "prompts/paul.txt"
DEFAULT_VOICE = "openai.onyx"

# ─── Paths & Config ─────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "signalwire.json"
STATE_DIR = BASE_DIR / "campaigns" / ".state"
LOG_DIR = BASE_DIR / "logs"
RESEARCH_CACHE_DIR = BASE_DIR / "campaigns" / ".research_cache"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    return cfg

CONFIG = load_config()
PROJECT_ID = CONFIG["project_id"]
AUTH_TOKEN = CONFIG["auth_token"]
SPACE_URL = CONFIG["space_url"]
FROM_NUMBER = CONFIG.get("phone_number", "+16028985026")

WEBHOOK_URL = "https://hooks.6eyes.dev/voice-caller/post-call"

# ─── Phone Number Normalization ──────────────────────────────────

def normalize_phone(raw):
    """Normalize phone to E.164 format (+1XXXXXXXXXX)."""
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) > 11:
        return f"+{digits}"
    return None


# ─── CSV Loading ─────────────────────────────────────────────────

def load_leads(csv_path):
    """Load leads from CSV, normalize phones, skip invalid."""
    leads = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone_raw = row.get("phone", "").strip()
            phone = normalize_phone(phone_raw)
            if not phone:
                continue

            # Parse notes field for location and type
            notes = row.get("notes", "")
            state = "South Dakota"  # default
            acct_type = "Education"  # default
            if "Iowa" in notes:
                state = "Iowa"
            elif "Nebraska" in notes:
                state = "Nebraska"
            if "Business" in notes:
                acct_type = "Business Services"
            elif "Government" in notes:
                acct_type = "Government"

            leads.append({
                "phone": phone,
                "name": row.get("name", "").strip(),
                "account": row.get("account", "").strip(),
                "notes": notes,
                "state": state,
                "account_type": acct_type
            })
    return leads


# ─── State Management (flat file) ───────────────────────────────

def get_state_file(csv_path):
    """Get state file path for a campaign."""
    name = Path(csv_path).stem
    return STATE_DIR / f"{name}.json"


def load_state(csv_path):
    sf = get_state_file(csv_path)
    if sf.exists():
        with open(sf) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "skipped": [], "last_index": -1}


def save_state(csv_path, state):
    sf = get_state_file(csv_path)
    with open(sf, "w") as f:
        json.dump(state, f, indent=2)


# ─── Research Cache ──────────────────────────────────────────────

def get_cached_research(account_name):
    """Check if we've already researched this account recently."""
    safe_name = re.sub(r"[^\w\-]", "_", account_name)[:80]
    cache_file = RESEARCH_CACHE_DIR / f"{safe_name}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        # Cache valid for 7 days
        cached_at = cached.get("_cached_at", "")
        if cached_at:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
                if age < 7 * 86400:
                    print(f"  [cache] Using cached research for {account_name}")
                    return cached
            except (ValueError, TypeError):
                pass
    return None


def cache_research(account_name, context):
    """Save research to cache."""
    safe_name = re.sub(r"[^\w\-]", "_", account_name)[:80]
    cache_file = RESEARCH_CACHE_DIR / f"{safe_name}.json"
    context["_cached_at"] = datetime.now(timezone.utc).isoformat()
    with open(cache_file, "w") as f:
        json.dump(context, f, indent=2)


# ─── Call Execution ──────────────────────────────────────────────

def make_call(to_number, swml):
    """Place outbound call via SignalWire Calling API."""
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()

    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "swml": swml
        }
    }

    response = requests.post(
        f"https://{SPACE_URL}/api/calling/calls",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {auth_b64}"
        },
        timeout=30
    )

    if response.status_code == 200:
        data = response.json()
        call_id = data.get("id", data.get("call_id", "unknown"))
        return {"success": True, "call_id": call_id, "data": data}
    else:
        return {"success": False, "status": response.status_code, "error": response.text}


# ─── Business Hours Check ───────────────────────────────────────

def is_business_hours():
    """Check if current time is within calling hours (8am-4pm Central)."""
    from datetime import timedelta
    # Central time = UTC-6 (or UTC-5 during DST, approximate)
    utc_now = datetime.now(timezone.utc)
    central_hour = (utc_now.hour - 6) % 24  # rough approximation
    return 8 <= central_hour < 16


def seconds_until_business_hours():
    """Seconds until next 8am Central."""
    from datetime import timedelta
    utc_now = datetime.now(timezone.utc)
    central_hour = (utc_now.hour - 6) % 24
    if central_hour >= 16:
        hours_until = (24 - central_hour) + 8
    else:
        hours_until = 8 - central_hour
    return hours_until * 3600


# ─── Campaign Log ────────────────────────────────────────────────

def log_call_attempt(lead, result, context_source):
    """Append to campaign log."""
    log_file = LOG_DIR / "campaign_log.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phone": lead["phone"],
        "account": lead["account"],
        "result": "success" if result.get("success") else "failed",
        "call_id": result.get("call_id", ""),
        "error": result.get("error", ""),
        "research_source": context_source
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ─── Main Campaign Runner ───────────────────────────────────────

def run_campaign(csv_path, args):
    leads = load_leads(csv_path)
    print(f"\nLoaded {len(leads)} leads from {csv_path}")

    state = load_state(csv_path) if args.resume else {
        "completed": [], "failed": [], "skipped": [], "last_index": -1
    }

    start_index = state["last_index"] + 1
    completed_phones = set(state["completed"])

    # Apply limit
    remaining = [l for l in leads[start_index:] if l["phone"] not in completed_phones]
    if args.limit:
        remaining = remaining[:args.limit]

    print(f"Will process {len(remaining)} leads (starting at index {start_index})")
    print(f"Interval: {args.interval}s between calls (~{60/args.interval:.1f} calls/min)")
    if args.dry_run:
        print("*** DRY RUN — research only, no calls ***\n")
    else:
        print(f"Calling from: {FROM_NUMBER}")
        print(f"Webhook: {WEBHOOK_URL}\n")

    consecutive_failures = 0

    for i, lead in enumerate(remaining):
        global_index = leads.index(lead)

        # Business hours check
        if args.business_hours and not args.dry_run:
            if not is_business_hours():
                wait = seconds_until_business_hours()
                print(f"\n⏸  Outside business hours. Pausing {wait//3600:.1f}h until 8am Central...")
                time.sleep(wait)

        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(remaining)}] {lead['account']}")
        print(f"  Phone: {lead['phone']}")
        print(f"  State: {lead['state']} | Type: {lead['account_type']}")

        # Step 1: Research
        context = get_cached_research(lead["account"])
        if not context:
            context = research_account(lead["account"], lead["state"], lead["account_type"])
            cache_research(lead["account"], context)

        context_source = context.get("_source", "unknown")
        print(f"  Hook: {context.get('hook_1', 'N/A')[:80]}")

        if args.dry_run:
            print(f"  [DRY RUN] Would call {lead['phone']} with personalized prompt")
            state["last_index"] = global_index
            save_state(csv_path, state)
            continue

        # Step 2: Build personalized SWML
        swml = build_dynamic_swml(
            context,
            base_prompt_path=args.prompt,
            voice=args.voice,
            webhook_url=WEBHOOK_URL
        )

        # Step 3: Place call
        print(f"  Calling {lead['phone']}...")
        result = make_call(lead["phone"], swml)

        if result["success"]:
            print(f"  ✅ Call initiated: {result['call_id']}")
            state["completed"].append(lead["phone"])
            consecutive_failures = 0
        else:
            print(f"  ❌ Call failed: {result.get('error', 'unknown')[:100]}")
            state["failed"].append(lead["phone"])
            consecutive_failures += 1

        # Log
        log_call_attempt(lead, result, context_source)

        # Update state
        state["last_index"] = global_index
        save_state(csv_path, state)

        # Circuit breaker
        if consecutive_failures >= 3:
            print(f"\n🛑 {consecutive_failures} consecutive failures. Pausing 5 min...")
            time.sleep(300)
            consecutive_failures = 0

        # Pacing (randomized ±20% to avoid pattern detection)
        if i < len(remaining) - 1:
            jitter = args.interval * 0.2
            wait = args.interval + random.uniform(-jitter, jitter)
            print(f"  Waiting {wait:.0f}s before next call...")
            time.sleep(wait)

    # Summary
    print(f"\n{'='*60}")
    print("CAMPAIGN SUMMARY")
    print(f"  Completed: {len(state['completed'])}")
    print(f"  Failed:    {len(state['failed'])}")
    print(f"  Remaining: {len(leads) - len(state['completed']) - len(state['failed'])}")
    print(f"  State saved to: {get_state_file(csv_path)}")
    print(f"  Call log: {LOG_DIR / 'campaign_log.jsonl'}")
    print(f"  Summaries: {LOG_DIR / 'call_summaries.jsonl'}")


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research-powered campaign caller for Fortinet SLED")
    parser.add_argument("csv_file", help="Path to leads CSV")
    parser.add_argument("--dry-run", action="store_true", help="Research only, no calls")
    parser.add_argument("--limit", type=int, default=None, help="Max calls to make")
    parser.add_argument("--interval", type=int, default=240, help="Seconds between calls (default: 240 = 4 min)")
    parser.add_argument("--resume", action="store_true", help="Resume from last position")
    parser.add_argument("--business-hours", action="store_true", help="Only call 8am-4pm Central")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt file path (default: prompts/paul.txt)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="TTS voice (default: openai.onyx)")

    args = parser.parse_args()

    if not Path(args.csv_file).exists():
        print(f"Error: {args.csv_file} not found")
        sys.exit(1)

    run_campaign(args.csv_file, args)
