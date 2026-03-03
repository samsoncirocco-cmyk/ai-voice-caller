#!/usr/bin/env python3
"""
Process Callbacks - Auto-dial scheduled callbacks from Firestore.

When the AI agent schedules a callback during a call, it lands in the
Firestore 'callbacks' collection. This script picks them up and auto-dials
when due.

Usage:
  python3 process_callbacks.py --list        # Show all pending callbacks
  python3 process_callbacks.py --dry-run     # Show what would be processed now
  python3 process_callbacks.py --process     # Execute due callbacks
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Paths & Config ---

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "signalwire.json"


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


CONFIG = load_config()
PROJECT_ID = CONFIG["project_id"]
AUTH_TOKEN = CONFIG["auth_token"]
SPACE_URL = CONFIG["space_url"]
FROM_NUMBER = CONFIG["phone_number"]
AGENT_ID = CONFIG["ai_agent"]["agent_id"]

db = firestore.Client(project="tatt-pro")


# --- Rate Limit Check (reuses call_rate/state) ---

def check_rate_limits():
    """Check Firestore call_rate/state. Returns (allowed, reason)."""
    doc = db.collection("call_rate").document("state").get()
    if not doc.exists:
        return True, "OK"
    state = doc.to_dict()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    limits = CONFIG.get("rate_limits", {})

    # Cooldown check
    cooldown_until = state.get("cooldown_until")
    if cooldown_until:
        if isinstance(cooldown_until, str):
            cooldown_until = datetime.fromisoformat(cooldown_until)
        if now < cooldown_until:
            remaining = int((cooldown_until - now).total_seconds())
            return False, f"Cooldown active. {remaining}s remaining."

    # Min interval
    last_call = state.get("last_call_time")
    if last_call:
        if isinstance(last_call, str):
            last_call = datetime.fromisoformat(last_call)
        elapsed = (now - last_call).total_seconds()
        min_interval = limits.get("min_interval_seconds", 30)
        if elapsed < min_interval:
            return False, f"Too soon. Wait {int(min_interval - elapsed)}s."

    # Hourly limit
    hour_start = state.get("hour_start")
    calls_this_hour = state.get("calls_this_hour", 0)
    max_per_hour = limits.get("max_calls_per_hour", 20)
    if hour_start:
        if isinstance(hour_start, str):
            hour_start = datetime.fromisoformat(hour_start)
        if (now - hour_start).total_seconds() < 3600 and calls_this_hour >= max_per_hour:
            return False, f"Hourly limit reached ({max_per_hour}/hr)."

    # Daily limit
    today = now.strftime("%Y-%m-%d")
    calls_today = state.get("calls_today", 0)
    max_per_day = limits.get("max_calls_per_day", 100)
    if state.get("today_date") == today and calls_today >= max_per_day:
        return False, f"Daily limit reached ({max_per_day}/day)."

    return True, "OK"


def record_call_attempt(success):
    """Record attempt in call_rate/state (mirrors make_call_v4 logic)."""
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    doc = db.collection("call_rate").document("state").get()
    state = doc.to_dict() if doc.exists else {}
    today = now.strftime("%Y-%m-%d")
    limits = CONFIG.get("rate_limits", {})

    calls_today = 1 if state.get("today_date") != today else state.get("calls_today", 0) + 1

    hour_start = state.get("hour_start")
    if hour_start and isinstance(hour_start, str):
        hour_start = datetime.fromisoformat(hour_start)
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
        max_failures = limits.get("max_consecutive_failures", 3)
        if failures >= max_failures:
            cooldown_secs = limits.get("cooldown_on_failure_seconds", 300)
            updates["cooldown_until"] = (now + timedelta(seconds=cooldown_secs)).isoformat()

    db.collection("call_rate").document("state").set(updates, merge=True)


# --- Firestore Helpers ---

def parse_callback_datetime(val):
    """Parse callback_datetime from Firestore (could be string, timestamp, or dict)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def get_pending_callbacks():
    """Fetch all callbacks with status='pending'."""
    docs = db.collection("callbacks").where(filter=FieldFilter("status", "==", "pending")).stream()
    callbacks = []
    for doc in docs:
        data = doc.to_dict()
        data["_doc_id"] = doc.id
        data["_callback_dt"] = parse_callback_datetime(data.get("callback_datetime"))
        callbacks.append(data)
    return sorted(callbacks, key=lambda c: c.get("_callback_dt") or datetime.max)


# --- Call Logic ---

def make_callback_call(phone):
    """Place a call via Compatibility API. Returns (call_sid, status, duration)."""
    api_url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"
    agent_url = f"https://{SPACE_URL}/api/ai/agent/{AGENT_ID}"

    try:
        resp = requests.post(
            api_url,
            auth=(PROJECT_ID, AUTH_TOKEN),
            data={"From": FROM_NUMBER, "To": phone, "Url": agent_url},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return None, f"request_error: {e}", 0

    if resp.status_code not in (200, 201):
        return None, f"http_{resp.status_code}", 0

    data = resp.json()
    sid = data.get("sid")

    print(f"    SID: {sid} - waiting 20s to verify...")
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
        return sid, status, duration
    except Exception:
        return sid, "check_failed", 0


# --- Commands ---

def cmd_list():
    """Show all pending callbacks."""
    callbacks = get_pending_callbacks()
    if not callbacks:
        print("No pending callbacks.")
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    print(f"\nPending callbacks ({len(callbacks)}):")
    print(f"{'='*70}")
    print(f"  {'Phone':<16} {'Name':<20} {'Scheduled':<22} {'Status'}")
    print(f"  {'-'*14}   {'-'*18}   {'-'*20}   {'-'*10}")

    for cb in callbacks:
        phone = cb.get("phone", "?")
        name = cb.get("contact_name", cb.get("name", "?"))
        cb_dt = cb.get("_callback_dt")
        if cb_dt:
            dt_str = cb_dt.strftime("%Y-%m-%d %H:%M UTC")
            if cb_dt <= now:
                tag = "DUE NOW"
            else:
                delta = cb_dt - now
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                tag = f"in {hours}h {mins}m"
        else:
            dt_str = "not set"
            tag = "no datetime"

        print(f"  {phone:<16} {name:<20} {dt_str:<22} {tag}")

    print(f"{'='*70}")


def cmd_dry_run():
    """Show what would be processed right now."""
    callbacks = get_pending_callbacks()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    due = [cb for cb in callbacks if cb.get("_callback_dt") and cb["_callback_dt"] <= now]
    upcoming = [cb for cb in callbacks if cb.get("_callback_dt") and cb["_callback_dt"] > now]
    no_dt = [cb for cb in callbacks if not cb.get("_callback_dt")]

    allowed, reason = check_rate_limits()

    print(f"\nDry Run Report")
    print(f"{'='*70}")
    print(f"  Rate limit check: {'CLEAR' if allowed else 'BLOCKED - ' + reason}")
    print(f"  Due now:    {len(due)}")
    print(f"  Upcoming:   {len(upcoming)}")
    print(f"  No datetime:{len(no_dt)}")

    if due:
        print(f"\n  Would process now:")
        for cb in due:
            phone = cb.get("phone", "?")
            name = cb.get("contact_name", cb.get("name", "?"))
            print(f"    -> Call {phone} ({name})")

    if upcoming:
        print(f"\n  Upcoming (not yet due):")
        for cb in upcoming:
            phone = cb.get("phone", "?")
            name = cb.get("contact_name", cb.get("name", "?"))
            cb_dt = cb["_callback_dt"]
            delta = cb_dt - now
            print(f"    {phone} ({name}) - due in {int(delta.total_seconds()//3600)}h {int((delta.total_seconds()%3600)//60)}m")

    print(f"\n  No calls were made.")
    print(f"{'='*70}")


def cmd_process():
    """Execute due callbacks."""
    callbacks = get_pending_callbacks()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    due = [cb for cb in callbacks if cb.get("_callback_dt") and cb["_callback_dt"] <= now]

    if not due:
        print("No callbacks due right now.")
        return

    print(f"\nProcessing {len(due)} due callback(s)...")
    print(f"{'='*70}")

    for cb in due:
        doc_id = cb["_doc_id"]
        phone = cb.get("phone", "")
        name = cb.get("contact_name", cb.get("name", "Unknown"))

        print(f"\n  [{name}] {phone}")

        # Rate limit check
        allowed, reason = check_rate_limits()
        if not allowed:
            print(f"    [SKIPPED] {reason}")
            continue

        # Make the call
        sid, status, duration = make_callback_call(phone)
        success = status in ("completed", "in-progress", "ringing", "queued")
        record_call_attempt(success)

        print(f"    Result: {status}, duration={duration}s")

        # Update Firestore callback doc
        if success:
            db.collection("callbacks").document(doc_id).update({
                "status": "called",
                "call_sid": sid,
                "called_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "call_status": status,
            })
            print(f"    Updated callback -> 'called'")
        else:
            db.collection("callbacks").document(doc_id).update({
                "status": "failed",
                "call_sid": sid or "",
                "failed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "failure_reason": status,
            })
            print(f"    Updated callback -> 'failed' ({status})")

    print(f"\n{'='*70}")
    print("Done.")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Process scheduled callbacks from Firestore")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Show all pending callbacks")
    group.add_argument("--dry-run", action="store_true", help="Show what would be processed now")
    group.add_argument("--process", action="store_true", help="Execute due callbacks")

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.dry_run:
        cmd_dry_run()
    elif args.process:
        cmd_process()


if __name__ == "__main__":
    main()
