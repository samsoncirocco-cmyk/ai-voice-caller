#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

SF_ALIAS = "fortinet"
SUMMARIES_PATH = "logs/call_summaries.jsonl"
STATE_PATH = "logs/sfdc-push-state.json"


def _run_sf(args: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "sf CLI timed out after 30s"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout


def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D+", "", s or "")


def _last10(s: Optional[str]) -> Optional[str]:
    digits = _digits(s)
    if len(digits) < 10:
        return None
    return digits[-10:]


def _extract_date(ts: Optional[str]) -> str:
    if not ts:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        # expected format: 2026-03-03T17:08:36Z
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _load_jsonl(path: str) -> List[Dict]:
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                items.append({"_raw": line, "_parse_error": True})
    return items


def _write_jsonl(path: str, items: List[Dict]) -> None:
    with open(path, "w") as f:
        for item in items:
            if item.get("_parse_error") and "_raw" in item:
                f.write(item["_raw"].rstrip("\n") + "\n")
            else:
                f.write(json.dumps(item, ensure_ascii=True) + "\n")


def _query_account_by_phone(last10: str) -> Optional[Dict[str, str]]:
    soql = f"SELECT Id, Name FROM Account WHERE Phone LIKE '%{last10}%' LIMIT 1"
    cmd = [
        "sf",
        "data",
        "query",
        "--query",
        soql,
        "--json",
        "--target-org",
        SF_ALIAS,
    ]
    ok, out = _run_sf(cmd)
    if not ok:
        print(f"Account lookup failed for {last10}: {out}")
        return None
    try:
        payload = json.loads(out)
        records = payload.get("result", {}).get("records", [])
        if not records:
            return None
        return {"Id": records[0].get("Id"), "Name": records[0].get("Name")}
    except Exception as exc:
        print(f"Account lookup parse error for {last10}: {exc}")
        return None


def _parse_disposition(summary: str) -> str:
    """Extract Call outcome line and map to SF CallDisposition picklist."""
    valid = {
        "connected": "Connected",
        "left voicemail": "Left Voicemail",
        "voicemail": "Left Voicemail",
        "no answer": "No Answer",
        "wrong number": "Wrong Number",
        "not interested": "Not Interested",
        "meeting booked": "Meeting Booked",
    }
    for line in summary.splitlines():
        if line.lower().startswith("- call outcome:"):
            raw = line.split(":", 1)[-1].strip().lower()
            for key, val in valid.items():
                if key in raw:
                    return val
    return "Connected"  # default


def _create_task(account_id: str, date_str: str, summary: str,
                 account_name: str = "") -> Optional[str]:
    disposition = _parse_disposition(summary)
    label = f" - {account_name}" if account_name else ""
    subject = f"Paul (AI) - {disposition}{label} - {date_str}"
    values = (
        f"Subject='{subject}' "
        "Status='Completed' "
        f"ActivityDate='{date_str}' "
        f"WhatId='{account_id}' "
        "Type='Call' "
        f"CallType='Outbound' "
        f"CallDisposition='{disposition}' "
        f"Description='{summary.replace(chr(39), chr(92)+chr(39))}'"
    )
    cmd = [
        "sf",
        "data",
        "create",
        "record",
        "--sobject",
        "Task",
        "--values",
        values,
        "--json",
        "--target-org",
        SF_ALIAS,
    ]
    ok, out = _run_sf(cmd)
    if not ok:
        print(f"Task create failed for account {account_id}: {out}")
        return None
    try:
        payload = json.loads(out)
        return payload.get("result", {}).get("id")
    except Exception as exc:
        print(f"Task create parse error for account {account_id}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Push call summaries to Salesforce as Tasks.")
    parser.add_argument("--call-id", help="Process a specific call_id")
    parser.add_argument("--all", action="store_true", help="Process all missing sf_task_id")
    parser.add_argument("--dry-run", action="store_true", help="Do not create tasks or write file")
    args = parser.parse_args()

    items = _load_jsonl(SUMMARIES_PATH)
    if not items:
        print(f"No call summaries found at {SUMMARIES_PATH}")
        return 1

    processed = 0
    created = 0
    skipped = 0
    errors = 0

    for item in items:
        if item.get("_parse_error"):
            skipped += 1
            continue

        call_id = item.get("call_id")
        if args.call_id and call_id != args.call_id:
            continue

        if item.get("sf_task_id"):
            skipped += 1
            continue

        if not args.all and not args.call_id:
            # Default behavior: process missing sf_task_id
            pass

        # Use sf_account_id directly if present (fast path — no phone lookup needed)
        if item.get("sf_account_id"):
            account = {"Id": item["sf_account_id"], "Name": item.get("sf_account_name", "")}
        else:
            phone_last10 = _last10(item.get("to") or item.get("from"))
            if not phone_last10:
                skipped += 1
                continue
            account = _query_account_by_phone(phone_last10)
            if not account or not account.get("Id"):
                skipped += 1
                continue

        processed += 1
        date_str = _extract_date(item.get("timestamp"))
        summary = item.get("summary") or ""

        if args.dry_run:
            disposition = _parse_disposition(summary)
            print(f"Dry-run: {disposition} | {account.get('Name','?')} ({account.get('Id')}) | call_id={call_id}")
            continue

        task_id = _create_task(account["Id"], date_str, summary, account.get("Name", ""))
        if not task_id:
            errors += 1
            continue

        item["sf_task_id"] = task_id
        item["sf_account_id"] = account["Id"]
        created += 1

    if not args.dry_run:
        _write_jsonl(SUMMARIES_PATH, items)

    state = {
        "last_run": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "processed": processed,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "dry_run": bool(args.dry_run),
    }
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=True, indent=2)

    print(f"Processed: {processed}")
    print(f"Created: {created}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
