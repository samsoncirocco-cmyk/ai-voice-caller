#!/usr/bin/env python3
"""
call_outcome_sfdc.py — Log a call outcome to Salesforce by creating a Task on the Account.

Creating a Task is the correct Salesforce mechanism — it populates the activity timeline
and automatically updates LastActivityDate (which is read-only/system-managed directly).

Usage:
  python3 execution/call_outcome_sfdc.py "Account Name" interested
  python3 execution/call_outcome_sfdc.py "Account Name" voicemail --note "Left VM, mention SD-WAN"
  python3 execution/call_outcome_sfdc.py "Account Name" --dry-run
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

SF_ALIAS = "fortinet"
BUSINESS_TZ = "America/Phoenix"

OUTCOME_SUBJECTS = {
    "interested":    "Cold Call — Interested — Follow Up Required",
    "voicemail":     "Cold Call — Voicemail Left",
    "not_interested":"Cold Call — Not Interested",
    "no_answer":     "Cold Call — No Answer",
    "callback":      "Cold Call — Requested Callback",
    "meeting":       "Cold Call — Meeting Booked",
    "completed":     "Cold Call — Completed",
}


def _run_sf(args: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "sf CLI timed out after 60s"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout


def _today_mst() -> str:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BUSINESS_TZ)).date().isoformat()
    return datetime.now(timezone(timedelta(hours=-7))).date().isoformat()


def _escape_soql(value: str) -> str:
    return value.replace("'", "\\'")


def _lookup_account(account_name: str) -> Optional[str]:
    soql = f"SELECT Id, Name FROM Account WHERE Name = '{_escape_soql(account_name)}' LIMIT 1"
    ok, out = _run_sf(["sf", "data", "query", "--query", soql, "--json", "--target-org", SF_ALIAS])
    if not ok:
        print(f"Query failed: {out}")
        return None
    try:
        records = json.loads(out).get("result", {}).get("records", [])
        return records[0].get("Id") if records else None
    except Exception as exc:
        print(f"Parse error: {exc}")
        return None


def _create_task(account_id: str, subject: str, note: str, date: str) -> Tuple[bool, str]:
    """Create a Completed Task (Activity) on the Account — this auto-updates LastActivityDate."""
    values = (
        f"WhatId={account_id} "
        f"Subject='{subject}' "
        f"Status=Completed "
        f"ActivityDate={date} "
        f"Description='{_escape_soql(note)}'"
    )
    return _run_sf([
        "sf", "data", "create", "record",
        "--sobject", "Task",
        "--values", values,
        "--target-org", SF_ALIAS,
        "--json",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Log AI call outcome to Salesforce via Task")
    parser.add_argument("account_name", help="Exact Salesforce Account Name")
    parser.add_argument("outcome", nargs="?", default="completed",
                        choices=list(OUTCOME_SUBJECTS.keys()) + ["completed"],
                        help="Call outcome")
    parser.add_argument("--note", default="", help="Optional call note")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen, no writes")
    args = parser.parse_args()

    account_name = args.account_name.strip()
    outcome = args.outcome or "completed"
    subject = OUTCOME_SUBJECTS.get(outcome, f"Cold Call — {outcome.title()}")
    note = args.note or f"Cold call — outcome: {outcome}"
    date = _today_mst()

    if args.dry_run:
        print(f"DRY RUN")
        print(f"  Account:  {account_name}")
        print(f"  Action:   Create Task on Account")
        print(f"  Subject:  {subject}")
        print(f"  Date:     {date}")
        print(f"  Note:     {note}")
        print(f"  Effect:   LastActivityDate auto-updated by Salesforce")
        return 0

    print(f"Looking up account: {account_name}...")
    account_id = _lookup_account(account_name)
    if not account_id:
        print(f"No Account found: {account_name}")
        return 1

    print(f"Found: {account_id} — creating Task...")
    ok, out = _create_task(account_id, subject, note, date)
    if not ok:
        print(f"Task creation failed: {out}")
        return 1

    try:
        result = json.loads(out)
        task_id = result.get("result", {}).get("id", "?")
    except Exception:
        task_id = "created"

    print(f"✅ Task {task_id} created on {account_name} (outcome={outcome})")
    print(f"   Subject: {subject}")
    print(f"   LastActivityDate will auto-update in Salesforce")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
