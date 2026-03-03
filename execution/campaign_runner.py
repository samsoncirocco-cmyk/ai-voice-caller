#!/usr/bin/env python3
"""
Campaign Runner - Batch outbound calls from CSV with rate-limit protection.

Usage:
  python3 campaign_runner.py campaigns/sample.csv --campaign-name test-run
  python3 campaign_runner.py campaigns/sample.csv --dry-run
  python3 campaign_runner.py campaigns/sample.csv --resume --campaign-name test-run
  python3 campaign_runner.py --help

CSV format: phone, name, account, notes
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from google.cloud import firestore

# ─── Paths ─────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "signalwire.json"
STATE_DIR = BASE_DIR / "campaigns" / ".state"


# ─── Configuration ──────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

CONFIG = load_config()
PROJECT_ID = CONFIG["project_id"]
AUTH_TOKEN = CONFIG["auth_token"]
SPACE_URL = CONFIG["space_url"]
FROM_NUMBER = CONFIG["phone_number"]
AGENT_ID = CONFIG["ai_agent"]["agent_id"]

RATE_LIMITS = CONFIG.get("rate_limits", {})
MIN_INTERVAL = RATE_LIMITS.get("min_interval_seconds", 30)
MAX_PER_HOUR = RATE_LIMITS.get("max_calls_per_hour", 20)
MAX_PER_DAY = RATE_LIMITS.get("max_calls_per_day", 100)
COOLDOWN_SECONDS = RATE_LIMITS.get("cooldown_on_failure_seconds", 300)
MAX_CONSEC_FAIL = RATE_LIMITS.get("max_consecutive_failures", 3)

db = firestore.Client(project="tatt-pro")


# ─── Rate Limit (reuses Firestore call_rate collection) ─────────

def get_rate_state():
    doc = db.collection("call_rate").document("state").get()
    if doc.exists:
        return doc.to_dict()
    return {
        "last_call_time": None,
        "consecutive_failures": 0,
        "cooldown_until": None,
        "calls_today": 0,
        "calls_this_hour": 0,
        "today_date": None,
        "hour_start": None,
    }


def update_rate_state(updates):
    db.collection("call_rate").document("state").set(updates, merge=True)


def _parse_dt(val):
    if val is None:
        return None
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return val


def check_rate_limits():
    state = get_rate_state()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    cooldown_until = _parse_dt(state.get("cooldown_until"))
    if cooldown_until and now < cooldown_until:
        remaining = int((cooldown_until - now).total_seconds())
        return False, f"Cooldown active. {remaining}s remaining.", remaining

    last_call = _parse_dt(state.get("last_call_time"))
    if last_call:
        elapsed = (now - last_call).total_seconds()
        if elapsed < MIN_INTERVAL:
            wait = int(MIN_INTERVAL - elapsed) + 1
            return False, f"Min interval. Wait {wait}s.", wait

    hour_start = _parse_dt(state.get("hour_start"))
    calls_this_hour = state.get("calls_this_hour", 0)
    if hour_start and (now - hour_start).total_seconds() < 3600:
        if calls_this_hour >= MAX_PER_HOUR:
            wait = int(3600 - (now - hour_start).total_seconds()) + 1
            return False, f"Hourly limit ({MAX_PER_HOUR}/hr).", wait

    today = now.strftime("%Y-%m-%d")
    calls_today = state.get("calls_today", 0)
    if state.get("today_date") == today and calls_today >= MAX_PER_DAY:
        return False, f"Daily limit ({MAX_PER_DAY}/day). Try tomorrow.", 0

    return True, "OK", 0


def record_call_attempt(success):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    state = get_rate_state()
    today = now.strftime("%Y-%m-%d")

    calls_today = 1 if state.get("today_date") != today else state.get("calls_today", 0) + 1

    hour_start = _parse_dt(state.get("hour_start"))
    if hour_start and (now - hour_start).total_seconds() < 3600:
        calls_this_hour = state.get("calls_this_hour", 0) + 1
    else:
        calls_this_hour = 1
        hour_start = now

    updates = {
        "last_call_time": now.isoformat(),
        "calls_today": calls_today,
        "today_date": today,
        "calls_this_hour": calls_this_hour,
        "hour_start": hour_start.isoformat() if isinstance(hour_start, datetime) else hour_start,
    }

    if success:
        updates["consecutive_failures"] = 0
        updates["cooldown_until"] = None
    else:
        failures = state.get("consecutive_failures", 0) + 1
        updates["consecutive_failures"] = failures
        if failures >= MAX_CONSEC_FAIL:
            cooldown_end = now + timedelta(seconds=COOLDOWN_SECONDS)
            updates["cooldown_until"] = cooldown_end.isoformat()
            print(f"  [COOLDOWN] {failures} consecutive failures. Pausing until {cooldown_end.strftime('%H:%M:%S')} UTC")

    update_rate_state(updates)


# ─── Phone Normalization ────────────────────────────────────────

def normalize_phone(raw):
    phone = raw.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"
    return phone


# ─── CSV Handling ───────────────────────────────────────────────

REQUIRED_COLUMNS = {"phone", "name"}

def read_csv(csv_path):
    rows = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - headers
        if missing:
            print(f"  [ERROR] CSV missing required columns: {missing}")
            sys.exit(1)
        for i, row in enumerate(reader):
            row["_index"] = i
            row["phone_normalized"] = normalize_phone(row["phone"])
            rows.append(row)
    return rows


def write_results_csv(csv_path, rows):
    output_path = csv_path.replace(".csv", "_results.csv")
    fieldnames = ["phone", "name", "account", "notes", "result_status", "call_sid", "duration"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "phone": row.get("phone", ""),
                "name": row.get("name", ""),
                "account": row.get("account", ""),
                "notes": row.get("notes", ""),
                "result_status": row.get("result_status", "pending"),
                "call_sid": row.get("call_sid", ""),
                "duration": row.get("duration", ""),
            })
    print(f"  Results written to {output_path}")
    return output_path


# ─── State (Resume Support) ────────────────────────────────────

def state_file_path(campaign_name):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{campaign_name}.json"


def load_state(campaign_name):
    path = state_file_path(campaign_name)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {"completed_indices": [], "results": {}}


def save_state(campaign_name, state):
    path = state_file_path(campaign_name)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


# ─── Firestore Logging ─────────────────────────────────────────

def log_campaign_run(campaign_name, csv_path, total, completed, failed, skipped):
    db.collection("campaign_runs").add({
        "campaign_name": campaign_name,
        "csv_path": csv_path,
        "total_contacts": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "from_number": FROM_NUMBER,
        "agent_id": AGENT_ID,
    })


def log_campaign_call(campaign_name, row, status, call_sid, duration):
    db.collection("campaign_calls").add({
        "campaign_name": campaign_name,
        "phone": row.get("phone_normalized", ""),
        "name": row.get("name", ""),
        "account": row.get("account", ""),
        "status": status,
        "call_sid": call_sid or "",
        "duration": duration or 0,
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    })


# ─── Call Logic ─────────────────────────────────────────────────

def make_call(to_number):
    api_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"
    agent_url = f"https://{SPACE_URL}/api/ai/agent/{AGENT_ID}"

    try:
        resp = requests.post(
            api_url,
            auth=(PROJECT_ID, AUTH_TOKEN),
            data={"From": FROM_NUMBER, "To": to_number, "Url": agent_url},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return None, f"request_error: {e}", None

    if resp.status_code not in (200, 201):
        return None, f"http_{resp.status_code}", None

    data = resp.json()
    sid = data.get("sid")

    # Wait and check result
    time.sleep(20)
    try:
        check = requests.get(
            f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls/{sid}.json",
            auth=(PROJECT_ID, AUTH_TOKEN),
            timeout=10,
        )
        cd = check.json()
        status = cd.get("status", "unknown")
        duration = cd.get("duration", 0)
        sip = cd.get("sip_result_code")

        if status == "failed" and duration == 0 and sip is None:
            return sid, "platform_rate_limited", 0
        elif status == "failed" and sip == 500:
            return sid, "carrier_blocked", 0
        elif status in ("completed", "in-progress", "ringing", "queued"):
            return sid, status, duration
        else:
            return sid, status, duration
    except Exception:
        return sid, "check_failed", None


def is_success_status(status):
    return status in ("completed", "in-progress", "ringing", "queued")


# ─── Campaign Runner ───────────────────────────────────────────

def run_campaign(csv_path, campaign_name, resume=False, dry_run=False):
    rows = read_csv(csv_path)
    total = len(rows)

    print(f"\n{'='*60}")
    print(f"CAMPAIGN: {campaign_name}")
    print(f"{'='*60}")
    print(f"  CSV:      {csv_path}")
    print(f"  Contacts: {total}")
    print(f"  From:     {FROM_NUMBER}")
    print(f"  Agent:    {AGENT_ID[:16]}...")
    print(f"  Mode:     {'DRY RUN' if dry_run else 'LIVE'}")

    if dry_run:
        print(f"\n  --- Dry Run Validation ---")
        for row in rows:
            phone = row["phone_normalized"]
            name = row.get("name", "?")
            account = row.get("account", "")
            valid = phone.startswith("+") and len(phone) >= 11
            tag = "OK" if valid else "INVALID"
            print(f"  [{tag}] {name:<20} {phone:<16} {account}")

        allowed, reason, _ = check_rate_limits()
        print(f"\n  Rate limit check: {'CLEAR' if allowed else 'BLOCKED - ' + reason}")
        print(f"  Estimated time: ~{total * MIN_INTERVAL}s ({total} calls x {MIN_INTERVAL}s interval)")
        print(f"\n  No calls were made.")
        return

    # Resume support
    state = load_state(campaign_name) if resume else {"completed_indices": [], "results": {}}
    completed_indices = set(state["completed_indices"])

    if resume and completed_indices:
        print(f"  Resuming: {len(completed_indices)}/{total} already done")

    completed = 0
    failed = 0
    skipped = len(completed_indices)

    print(f"{'='*60}\n")

    for row in rows:
        idx = row["_index"]
        if idx in completed_indices:
            continue

        phone = row["phone_normalized"]
        name = row.get("name", "Unknown")

        print(f"  [{idx+1}/{total}] {name} ({phone})")

        # Check rate limits; wait if needed
        allowed, reason, wait_secs = check_rate_limits()
        if not allowed and wait_secs > 0 and wait_secs <= COOLDOWN_SECONDS:
            print(f"    Waiting {wait_secs}s ({reason})")
            time.sleep(wait_secs)
            allowed, reason, _ = check_rate_limits()

        if not allowed:
            print(f"    [SKIPPED] {reason}")
            row["result_status"] = f"skipped: {reason}"
            continue

        # Make the call
        sid, status, duration = make_call(phone)
        success = is_success_status(status)
        record_call_attempt(success)

        row["result_status"] = status
        row["call_sid"] = sid or ""
        row["duration"] = duration or 0

        print(f"    Status: {status}, SID: {(sid or 'none')[:20]}, Duration: {duration or 0}s")

        log_campaign_call(campaign_name, row, status, sid, duration)

        if success:
            completed += 1
        else:
            failed += 1

        # Update state for resume
        state["completed_indices"].append(idx)
        state["results"][str(idx)] = {"status": status, "sid": sid, "duration": duration}
        save_state(campaign_name, state)

        # Merge results back into rows for CSV output
        # (wait MIN_INTERVAL is handled by rate limiter on next iteration)

    # Write results CSV
    write_results_csv(csv_path, rows)

    # Log to Firestore
    log_campaign_run(campaign_name, csv_path, total, completed, failed, skipped)

    print(f"\n{'='*60}")
    print(f"CAMPAIGN COMPLETE: {campaign_name}")
    print(f"  Total: {total}  Completed: {completed}  Failed: {failed}  Skipped: {skipped}")
    print(f"{'='*60}")


# ─── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Campaign Runner - Batch outbound calls from CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s campaigns/sample.csv --campaign-name test-run --dry-run
  %(prog)s campaigns/sample.csv --campaign-name outreach-feb
  %(prog)s campaigns/sample.csv --campaign-name outreach-feb --resume
        """
    )
    parser.add_argument("csv_file", help="Path to CSV file (columns: phone, name, account, notes)")
    parser.add_argument("--campaign-name", "-n", required=True, help="Name for this campaign run")
    parser.add_argument("--dry-run", action="store_true", help="Validate CSV and show plan without calling")
    parser.add_argument("--resume", action="store_true", help="Resume a previously interrupted campaign")

    args = parser.parse_args()

    if not os.path.exists(args.csv_file):
        print(f"  [ERROR] CSV not found: {args.csv_file}")
        sys.exit(1)

    run_campaign(args.csv_file, args.campaign_name, resume=args.resume, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
