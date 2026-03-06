#!/usr/bin/env python3
"""
sfdc_live_sync.py — Pull Salesforce Accounts and upsert into accounts.db.

Usage:
  python3 execution/sfdc_live_sync.py --dry-run
  python3 execution/sfdc_live_sync.py --states IA,NE,SD
"""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from account_db import AccountDB  # noqa: E402

SF_ALIAS = "fortinet"
SLACK_CHANNEL = "C0AJWRGBW3B"  # #ai-caller
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

DEFAULT_STATES = ["IA", "NE", "SD"]


def _post_slack(text: str) -> bool:
    if not SLACK_TOKEN:
        print("SLACK_BOT_TOKEN not set; skipping Slack post.")
        return False
    try:
        import requests

        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=20,
        )
        data = r.json()
        if not data.get("ok"):
            print(f"Slack error: {data}")
            return False
        return True
    except Exception as exc:
        print(f"Slack post failed: {exc}")
        return False


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


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _ensure_upsert():
    if hasattr(AccountDB, "upsert"):
        return

    def upsert(self, record: Dict) -> str:
        name = (record.get("account_name") or "").strip()
        phone = (record.get("phone") or "").strip()
        state = (record.get("state") or "").strip() or None
        vertical = (record.get("vertical") or "").strip() or None
        sfdc_id = (record.get("sfdc_id") or "").strip() or None
        now = datetime.now(timezone.utc).isoformat()

        if not name or not phone:
            return "skipped"

        with self._connect() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            row = None
            if sfdc_id:
                row = conn.execute(
                    "SELECT account_id FROM accounts WHERE sfdc_id = ?",
                    (sfdc_id,),
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT account_id FROM accounts WHERE phone = ? AND account_name = ?",
                    (phone, name),
                ).fetchone()

            if row:
                conn.execute(
                    """
                    UPDATE accounts
                    SET account_name = ?,
                        phone = ?,
                        state = ?,
                        vertical = ?,
                        sfdc_id = COALESCE(?, sfdc_id)
                    WHERE account_id = ?
                    """,
                    (name, phone, state, vertical, sfdc_id, row["account_id"]),
                )
                conn.execute("COMMIT")
                return "updated"

            account_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO accounts
                    (account_id, account_name, phone, state, vertical, sfdc_id,
                     call_status, call_count, last_called_at, next_call_at,
                     agent_id, outcome_notes, referral_source, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?,
                     'new', 0, NULL, NULL,
                     NULL, NULL, NULL, ?)
                """,
                (account_id, name, phone, state, vertical, sfdc_id, now),
            )
            conn.execute("COMMIT")
            return "inserted"

    AccountDB.upsert = upsert  # type: ignore[method-assign]


def _build_soql(states: List[str]) -> str:
    state_list = ",".join([f"'{s}'" for s in states])
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry "
        "FROM Account "
        "WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        "AND IsDeleted = false "
        "ORDER BY Name"
    )


def _auth_ok() -> bool:
    ok, out = _run_sf(["sf", "org", "display", "--target-org", SF_ALIAS, "--json"])
    if not ok:
        _post_slack(f"SFDC auth expired for `{SF_ALIAS}` — re-login required. Error: {out}")
        return False
    try:
        payload = json.loads(out)
        if payload.get("status") != 0:
            _post_slack(f"SFDC auth check failed for `{SF_ALIAS}`.")
            return False
    except Exception:
        pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="SFDC live sync for AI Voice Caller")
    parser.add_argument("--states", default=",".join(DEFAULT_STATES), help="Comma-separated states")
    parser.add_argument("--db", default=None, help="Override DB path")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    args = parser.parse_args()

    if not _auth_ok():
        return 1

    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    if not states:
        print("No states provided; aborting.")
        return 1

    soql = _build_soql(states)
    ok, out = _run_sf(
        ["sf", "data", "query", "--query", soql, "--json", "--target-org", SF_ALIAS]
    )
    if not ok:
        print(f"Salesforce query failed: {out}")
        return 1

    try:
        payload = json.loads(out)
        records = payload.get("result", {}).get("records", [])
    except Exception as exc:
        print(f"Failed to parse Salesforce output: {exc}")
        return 1

    _ensure_upsert()
    db = AccountDB(db_path=args.db)

    counts = {"inserted": 0, "updated": 0, "skipped": 0}

    for rec in records:
        phone = _normalize_phone(rec.get("Phone", ""))
        name = rec.get("Name") or ""
        state = (rec.get("BillingState") or "").strip().upper()
        vertical = rec.get("Industry") or rec.get("Type") or ""
        sfdc_id = rec.get("Id") or ""

        row = {
            "account_name": name,
            "phone": phone,
            "state": state,
            "vertical": vertical,
            "sfdc_id": sfdc_id,
        }

        if args.dry_run:
            counts["skipped"] += 1
            continue

        status = db.upsert(row)  # type: ignore[attr-defined]
        if status in counts:
            counts[status] += 1
        else:
            counts["skipped"] += 1

    print(f"Total queried: {len(records)}")
    print(f"Inserted: {counts['inserted']}")
    print(f"Updated: {counts['updated']}")
    print(f"Skipped: {counts['skipped']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
