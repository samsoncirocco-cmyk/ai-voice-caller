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

  # Use SmartRouter for intelligent routing (default when using accounts.db mode)
  python3 campaign_runner_v2.py --db campaigns/accounts.db --limit 10

Requires:
  - SignalWire credentials in config/signalwire.json
  - OPENROUTER_API_KEY and/or OPENAI_API_KEY in .env
  - webhook_server.py running on hooks.6eyes.dev

Routing Rules (GSD - 2026-03-09):
  - K-12         → +16028985026 + prompts/paul.txt
  - Municipal/Gov→ +16028985026 + prompts/paul.txt
  - Unknown/Cold → +14806024668 + prompts/cold_outreach.txt
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
sys.path.insert(0, str(Path(__file__).resolve().parent / "execution"))
from research_agent import research_account, build_dynamic_swml

# SmartRouter for intelligent vertical-based routing
try:
    from smart_router import SmartRouter
except ImportError:
    SmartRouter = None  # Fallback: use legacy CSV mode

try:
    import cost_tracker
except ImportError:
    cost_tracker = None

DEFAULT_PROMPT = "prompts/paul.txt"
DEFAULT_VOICE = "openai.onyx"

# ─── State-Based Routing (2026-03-09) ────────────────────────────────
# State → local presence number (605/402/515 for SD/NE/IA)
STATE_FROM_NUMBERS = {
    "SD": "+16053035984",  # 605 - South Dakota local presence
    "NE": "+14022755273",  # 402 - Nebraska local presence
    "IA": "+15152987809",  # 515 - Iowa local presence
}
DEFAULT_FROM_NUMBER = "+16028985026"  # 602 - fallback for non-territory states

# Vertical → prompt_file mapping (from_number determined by state, not vertical)
VERTICAL_PROMPTS = {
    "k12":        "prompts/k12.txt",        # K-12 specialized — E-Rate, lean IT, district language
    "government": "prompts/paul.txt",        # Municipal/county/gov
    "higher_ed":  "prompts/cold_outreach.txt",
    "other":      "prompts/cold_outreach.txt",
}

def select_from_number(state: str) -> str:
    """Select outbound number based on account state for local presence."""
    if not state:
        return DEFAULT_FROM_NUMBER
    return STATE_FROM_NUMBERS.get(state.strip().upper(), DEFAULT_FROM_NUMBER)

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
                "account_type": acct_type,
                # Pass SFDC Account ID so research_agent uses the stable cache key
                "sf_account_id": row.get("sf_account_id", "").strip(),
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
        if os.path.getmtime(cache_file) < time.time() - (30 * 86400):
            try:
                cache_file.unlink()
                print(f"  [cache] Removed stale cache file: {cache_file.name}")
            except OSError:
                pass
            return None
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

def make_call(to_number, swml, from_number=None):
    """Place outbound call via SignalWire Calling API."""
    auth_b64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()

    payload = {
        "command": "dial",
        "params": {
            "from": from_number or FROM_NUMBER,
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
    """Check if current time is within calling hours (8am-4pm Central, M-F)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    local_now = datetime.now(ZoneInfo("America/Chicago"))
    if local_now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return 8 <= local_now.hour < 16


def seconds_until_business_hours():
    """Seconds until next 8am Central."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    local_now = datetime.now(ZoneInfo("America/Chicago"))
    local_hour = local_now.hour
    if local_hour >= 16:
        hours_until = (24 - local_hour) + 8
    else:
        hours_until = max(0, 8 - local_hour)
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


def append_pending_summary_stub(call_id, phone, account):
    """Write a minimal pending record so every initiated call has a summary entry."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summaries_file = LOG_DIR / "call_summaries.jsonl"
    stub = {
        "call_id": call_id,
        "phone": phone,
        "account": account,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    with open(summaries_file, "a") as f:
        f.write(json.dumps(stub) + "\n")


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

        # Step 1: Research — L1 (local) + L2 (BigQuery) caching handled inside research_account().
        # Legacy get_cached_research()/cache_research() removed: they keyed by account_name only,
        # which bypassed the stable sf_account_id key and shadowed BigQuery hits.
        context = research_account(
            lead["account"], lead["state"], lead["account_type"],
            sf_account_id=lead.get("sf_account_id", ""),
        )

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
        balance_before = None
        if cost_tracker:
            try:
                balance_before = cost_tracker.get_balance(CONFIG)
            except Exception as exc:
                print(f"  [warn] Could not fetch pre-call balance: {exc}")
        result = make_call(lead["phone"], swml, from_number=args.from_number)

        call_id_for_cost = None
        if result["success"]:
            print(f"  ✅ Call initiated: {result['call_id']}")
            append_pending_summary_stub(result["call_id"], lead["phone"], lead["account"])
            call_id_for_cost = result["call_id"]
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

        if cost_tracker and call_id_for_cost and balance_before is not None:
            try:
                balance_after = cost_tracker.get_balance(CONFIG)
                cost_tracker.log_call_cost(call_id_for_cost, balance_before, balance_after)
            except Exception as exc:
                print(f"  [warn] Could not log call cost for {call_id_for_cost}: {exc}")

    # Summary
    print(f"\n{'='*60}")
    print("CAMPAIGN SUMMARY")
    print(f"  Completed: {len(state['completed'])}")
    print(f"  Failed:    {len(state['failed'])}")
    print(f"  Remaining: {len(leads) - len(state['completed']) - len(state['failed'])}")
    print(f"  State saved to: {get_state_file(csv_path)}")
    print(f"  Call log: {LOG_DIR / 'campaign_log.jsonl'}")
    print(f"  Summaries: {LOG_DIR / 'call_summaries.jsonl'}")


# ─── SmartRouter-based Campaign Runner ──────────────────────────

def run_campaign_db(args):
    """
    Run campaign using SmartRouter with accounts.db (default routing layer).
    
    This is the primary mode — uses intelligent routing based on vertical
    classification with GSD-defined rules:
      - K-12         → +16028985026 + paul.txt
      - Municipal/Gov→ +16028985026 + paul.txt  
      - Unknown/Cold → +14806024668 + cold_outreach.txt
    """
    if SmartRouter is None:
        print("Error: SmartRouter not available. Install execution/smart_router.py")
        sys.exit(1)
    
    router = SmartRouter(
        db_path=args.db,
        bypass_time_windows=args.bypass_time_windows,
    )
    
    print(f"\n{'='*60}")
    print("SMART ROUTER MODE")
    print(f"  Database: {args.db}")
    print(f"  Bypass time windows: {args.bypass_time_windows}")
    print(f"  Limit: {args.limit or 'unlimited'}")
    print(f"  Interval: {args.interval}s between calls")
    if args.dry_run:
        print("  *** DRY RUN — routing decisions only, no calls ***")
    print(f"\n  State-based routing (local presence):")
    for state, num in STATE_FROM_NUMBERS.items():
        print(f"    {state} → {num}")
    print(f"    (fallback) → {DEFAULT_FROM_NUMBER}")
    print(f"\n  Vertical → Prompt mapping:")
    for vertical, prompt in VERTICAL_PROMPTS.items():
        print(f"    {vertical:12} → {prompt}")
    print(f"{'='*60}\n")
    
    # Get DB stats
    stats = router.db.get_stats()
    print(f"Account status: {json.dumps(stats, indent=2)}")
    
    calls_made = 0
    # SAFETY 2026-03-09: Hard cap at 50 calls if no --limit provided.
    # Previous default was 999999 — could call entire account list uncontrolled.
    calls_limit = args.limit or 50
    consecutive_failures = 0
    
    results_by_vertical = {}
    
    while calls_made < calls_limit:
        # Business hours check
        if args.business_hours and not args.dry_run:
            if not is_business_hours():
                wait = seconds_until_business_hours()
                print(f"\n⏸  Outside business hours. Pausing {wait//3600:.1f}h until 8am Central...")
                time.sleep(wait)
        
        # Get next call from SmartRouter
        routing = router.get_next_call(f"campaign-runner-{os.getpid()}")
        
        if routing is None:
            print("\n✓ No more callable accounts (all filtered by time windows or completed)")
            break
        
        account = routing["account"]
        vertical = routing["vertical"]
        prompt_file = routing["prompt_file"]
        voice = routing["voice"]
        reason = routing["reason"]
        
        # Apply state-based routing for local presence + vertical prompt selection
        account_state = account.get("state", "")
        from_number = select_from_number(account_state)
        gsd_prompt = VERTICAL_PROMPTS.get(vertical, VERTICAL_PROMPTS["other"])
        
        calls_made += 1
        
        print(f"\n{'─'*60}")
        print(f"[{calls_made}/{args.limit or '∞'}] {account['account_name']}")
        print(f"  Phone:    {account['phone']}")
        print(f"  State:    {account['state']} | Vertical: {vertical}")
        print(f"  From:     {from_number}")
        print(f"  Prompt:   {gsd_prompt}")
        print(f"  Reason:   {reason}")
        
        # Track by vertical for summary
        if vertical not in results_by_vertical:
            results_by_vertical[vertical] = {"attempted": 0, "success": 0, "failed": 0}
        results_by_vertical[vertical]["attempted"] += 1
        
        if args.dry_run:
            print(f"  [DRY RUN] Would call {account['phone']} via SmartRouter")
            # Complete the call as no_answer so it doesn't block next run
            router.complete_call(
                account["account_id"],
                outcome="no_answer",
                notes=f"DRY RUN — vertical={vertical}, prompt={gsd_prompt}",
                answered=False,
            )
            results_by_vertical[vertical]["success"] += 1
            continue
        
        # Research account
        context = research_account(
            account["account_name"],
            account.get("state", ""),
            vertical,
            sf_account_id=account.get("sfdc_id", ""),
        )
        context_source = context.get("_source", "unknown")
        print(f"  Research: {context_source} | Hook: {context.get('hook_1', 'N/A')[:60]}")
        
        # Build SWML with GSD-routed prompt
        swml = build_dynamic_swml(
            context,
            base_prompt_path=gsd_prompt,
            voice=voice,
            webhook_url=WEBHOOK_URL,
        )
        
        # Place call with GSD-routed from_number
        print(f"  Calling {account['phone']}...")
        balance_before = None
        if cost_tracker:
            try:
                balance_before = cost_tracker.get_balance(CONFIG)
            except Exception as exc:
                print(f"  [warn] Could not fetch pre-call balance: {exc}")
        result = make_call(account["phone"], swml, from_number=from_number)

        call_id_for_cost = None
        if result["success"]:
            print(f"  ✅ Call initiated: {result['call_id']}")
            append_pending_summary_stub(result["call_id"], account["phone"], account["account_name"])
            call_id_for_cost = result["call_id"]
            # Note: actual outcome comes from webhook; mark as voicemail for now
            router.complete_call(
                account["account_id"],
                outcome="voicemail",  # conservative default
                notes=f"call_id={result['call_id']} | vertical={vertical} | prompt={gsd_prompt}",
                answered=False,
            )
            results_by_vertical[vertical]["success"] += 1
            consecutive_failures = 0
        else:
            print(f"  ❌ Call failed: {result.get('error', 'unknown')[:100]}")
            router.complete_call(
                account["account_id"],
                outcome="no_answer",
                notes=f"API error: {result.get('error', 'unknown')[:200]}",
                answered=False,
            )
            results_by_vertical[vertical]["failed"] += 1
            consecutive_failures += 1
        
        # Log
        log_call_attempt(
            {"phone": account["phone"], "account": account["account_name"]},
            result,
            context_source,
        )
        
        # Circuit breaker
        if consecutive_failures >= 3:
            print(f"\n🛑 {consecutive_failures} consecutive failures. Pausing 5 min...")
            time.sleep(300)
            consecutive_failures = 0
        
        # Pacing
        if calls_made < calls_limit:
            jitter = args.interval * 0.2
            wait = args.interval + random.uniform(-jitter, jitter)
            print(f"  Waiting {wait:.0f}s before next call...")
            time.sleep(wait)

        if cost_tracker and call_id_for_cost and balance_before is not None:
            try:
                balance_after = cost_tracker.get_balance(CONFIG)
                cost_tracker.log_call_cost(call_id_for_cost, balance_before, balance_after)
            except Exception as exc:
                print(f"  [warn] Could not log call cost for {call_id_for_cost}: {exc}")
    
    # Summary
    print(f"\n{'='*60}")
    print("SMART ROUTER CAMPAIGN SUMMARY")
    print(f"  Total calls: {calls_made}")
    print(f"\n  Results by vertical:")
    for vert, counts in results_by_vertical.items():
        print(f"    {vert:12}: {counts['attempted']} attempted, {counts['success']} success, {counts['failed']} failed")
    print(f"\n  Call log: {LOG_DIR / 'campaign_log.jsonl'}")
    print(f"{'='*60}")
    
    return results_by_vertical


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research-powered campaign caller for Fortinet SLED")
    parser.add_argument("csv_file", nargs="?", default=None, help="Path to leads CSV (legacy mode)")
    parser.add_argument("--db", default=None, 
                        help="Path to accounts.db (SmartRouter mode - recommended)")
    parser.add_argument("--dry-run", action="store_true", help="Research only, no calls")
    parser.add_argument("--limit", type=int, default=None, help="Max calls to make")
    parser.add_argument("--interval", type=int, default=240, help="Seconds between calls (default: 240 = 4 min)")
    parser.add_argument("--resume", action="store_true", help="Resume from last position (CSV mode only)")
    parser.add_argument("--business-hours", action="store_true", help="Only call 8am-4pm Central")
    parser.add_argument("--bypass-time-windows", action="store_true", 
                        help="Ignore SmartRouter time-of-day rules (for testing)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt file path (CSV mode; SmartRouter uses GSD rules)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="TTS voice (default: openai.onyx)")
    parser.add_argument("--from", dest="from_number", default=None,
                        help="Outbound caller ID (CSV mode; SmartRouter uses GSD rules)")

    args = parser.parse_args()

    # SmartRouter mode (preferred)
    if args.db:
        if not Path(args.db).exists():
            print(f"Error: {args.db} not found")
            sys.exit(1)
        run_campaign_db(args)
    # Legacy CSV mode
    elif args.csv_file:
        if not Path(args.csv_file).exists():
            print(f"Error: {args.csv_file} not found")
            sys.exit(1)
        run_campaign(args.csv_file, args)
    else:
        print("Error: Must provide either --db (SmartRouter mode) or csv_file (legacy mode)")
        parser.print_help()
        sys.exit(1)
