#!/usr/bin/env python3
"""
call_outcome_sfdc.py — Update Salesforce Account LastActivityDate after a call.

Usage:
  python3 execution/call_outcome_sfdc.py "Account Name" interested
  python3 execution/call_outcome_sfdc.py "Account Name" --dry-run
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

SF_ALIAS = "fortinet"
BUSINESS_TZ = "America/Phoenix"


def _run_sf(args: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Update SFDC Account LastActivityDate")
    parser.add_argument("account_name", help="Exact Salesforce Account Name")
    parser.add_argument("outcome", nargs="?", default="completed", help="Call outcome label")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    args = parser.parse_args()

    account_name = args.account_name.strip()
    if not account_name:
        print("Account name required.")
        return 1

    soql = (
        "SELECT Id, Name FROM Account "
        f"WHERE Name = '{_escape_soql(account_name)}' "
        "LIMIT 1"
    )

    query_cmd = ["sf", "data", "query", "--query", soql, "--json", "--target-org", SF_ALIAS]
    if args.dry_run:
        print("DRY RUN — would execute:")
        print(" ".join(query_cmd))
        print(f"Then update LastActivityDate to {_today_mst()}")
        return 0

    ok, out = _run_sf(query_cmd)
    if not ok:
        print(f"Salesforce query failed: {out}")
        return 1

    try:
        payload = json.loads(out)
        records = payload.get("result", {}).get("records", [])
    except Exception as exc:
        print(f"Failed to parse Salesforce output: {exc}")
        return 1

    if not records:
        print(f"No Account found for name: {account_name}")
        return 1

    account_id = records[0].get("Id")
    if not account_id:
        print("Account Id missing from query result.")
        return 1

    date_value = _today_mst()
    update_cmd = [
        "sf",
        "data",
        "update",
        "record",
        "--sobject",
        "Account",
        "--record-id",
        account_id,
        "--values",
        f"LastActivityDate={date_value}",
        "--target-org",
        SF_ALIAS,
    ]

    ok, out = _run_sf(update_cmd)
    if not ok:
        print(f"Salesforce update failed: {out}")
        return 1

    print(f"Updated {account_name} LastActivityDate={date_value} (outcome={args.outcome})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
