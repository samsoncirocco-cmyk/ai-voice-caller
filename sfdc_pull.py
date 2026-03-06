#!/usr/bin/env python3
"""
sfdc_pull.py — Salesforce → AI Voice Caller pipeline.

MODES
─────
CSV (default / legacy):
    python3 sfdc_pull.py
    python3 sfdc_pull.py --output campaigns/custom.csv --states IA,NE,SD

Live sync to accounts.db:
    python3 sfdc_pull.py --sync
    python3 sfdc_pull.py --sync --dry-run
    python3 sfdc_pull.py --sync --states IA,NE,SD --db campaigns/accounts.db

SYNC LOGIC
──────────
1. Pull all Accounts in territory (IA/NE/SD) where:
       • No open Opportunity  OR
       • Last activity > 30 days ago (or never)
2. Upsert into accounts.db:
       • New accounts  → call_status='new', call_count=0
       • Existing      → update name/phone/state/sfdc_id only; preserve call_status, call_count
3. Pull SFDC Contacts with LeadSource IN ('Referral', 'AI Caller Referral', 'Word of mouth')
       created since last sync → upsert as call_status='new' referral accounts
4. Print summary and post to Slack #activity-log
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Paths / constants ─────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "campaigns" / "accounts.db"
LOG_DIR = HERE / "logs"
SYNC_STATE_FILE = LOG_DIR / "sfdc-sync-state.json"

SF_ALIAS = "fortinet"
DEFAULT_STATES = ["IA", "NE", "SD"]
DEFAULT_OUTPUT = "campaigns/sfdc-accounts.csv"
ACTIVITY_DAYS = 30  # accounts inactive longer than this are eligible

SLACK_CHANNEL = "C0AG2ML0C57"  # #activity-log


# ── Environment loading ───────────────────────────────────────────────────────

def _load_env() -> None:
    """Load .env files — project first, then workspace fallback."""
    search_paths = [
        HERE / ".env",
        HERE.parent.parent / ".env",  # ~/.openclaw/workspace/.env
    ]
    for p in search_paths:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")


# ── sf CLI wrapper ────────────────────────────────────────────────────────────

def _run_sf(args: List[str], timeout: int = 120) -> Tuple[bool, str]:
    """Run an sf CLI command. Returns (success, stdout_or_error_string)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"sf CLI timed out after {timeout}s"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout


def _auth_ok() -> bool:
    ok, out = _run_sf(["sf", "org", "display", "--target-org", SF_ALIAS, "--json"])
    if not ok:
        print(f"  ✗ SFDC auth check failed for alias '{SF_ALIAS}': {out[:300]}")
        return False
    try:
        payload = json.loads(out)
        if payload.get("status") != 0:
            print(f"  ✗ SFDC returned non-zero status for org display.")
            return False
    except Exception:
        pass  # if JSON parse fails but returncode was 0, treat as ok
    return True


# ── Phone / state normalisation ───────────────────────────────────────────────

def _normalize_state(raw: Optional[str]) -> str:
    return (raw or "").strip().upper()


def _normalize_phone_e164(raw: Optional[str]) -> Optional[str]:
    """Return E.164 (+1XXXXXXXXXX) or None if not normalizable."""
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def _normalize_phone_digits(raw: Optional[str]) -> str:
    """Return bare 10-digit string for DB storage (strips leading 1)."""
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _state_variants(states: List[str]) -> List[str]:
    """Return upper/lower/title variants for each state abbrev."""
    variants: List[str] = []
    seen: set = set()
    for s in states:
        s = s.strip()
        if not s:
            continue
        for v in [s.upper(), s.lower(), s.title()]:
            if v not in seen:
                seen.add(v)
                variants.append(v)
    return variants


# ── SOQL builders ─────────────────────────────────────────────────────────────

def _build_soql_csv(states: List[str]) -> str:
    """Legacy CSV pull — basic account query, no filtering."""
    state_list = ",".join(f"'{s}'" for s in _state_variants(states))
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry "
        "FROM Account "
        "WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        "AND IsDeleted = false "
        "ORDER BY Name"
    )


def _build_soql_inactive(states: List[str], cutoff_date: str) -> str:
    """
    Accounts that haven't had any activity in the last ACTIVITY_DAYS days
    (or have never had activity recorded).

    NOTE: SOQL semi-join subqueries are only allowed at the top-level WHERE —
    they cannot be nested inside OR.  We therefore split the "no open opp OR
    inactive" logic into two separate queries and merge client-side.

    cutoff_date: YYYY-MM-DD string (e.g. '2026-02-04')
    """
    state_list = ",".join(f"'{s}'" for s in _state_variants(states))
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry, LastActivityDate "
        "FROM Account "
        "WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        "AND IsDeleted = false "
        f"AND (LastActivityDate = null OR LastActivityDate <= {cutoff_date}) "
        "ORDER BY Name"
    )


def _build_soql_no_open_opp(states: List[str]) -> str:
    """
    Accounts in territory that have NO open (IsClosed = false) Opportunity.
    Semi-join at the top level is valid SOQL.
    """
    state_list = ",".join(f"'{s}'" for s in _state_variants(states))
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry, LastActivityDate "
        "FROM Account "
        "WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        "AND IsDeleted = false "
        "AND Id NOT IN (SELECT AccountId FROM Opportunity WHERE IsClosed = false AND AccountId != null) "
        "ORDER BY Name"
    )


def _build_soql_referral_contacts(since_date: str) -> str:
    """
    Pull Contacts flagged as referrals created after since_date.

    Matches:
      - LeadSource = 'Referral'           (standard SFDC value)
      - LeadSource = 'AI Caller Referral' (set by referral_processor.py)
      - LeadSource = 'Word of mouth'      (common synonym)

    since_date: YYYY-MM-DD string
    """
    since_iso = f"{since_date}T00:00:00Z"
    return (
        "SELECT Id, FirstName, LastName, Phone, AccountId, Account.Name, "
        "Title, LeadSource, Description, CreatedDate "
        "FROM Contact "
        "WHERE ("
        "LeadSource = 'Referral' "
        "OR LeadSource = 'AI Caller Referral' "
        "OR LeadSource = 'Word of mouth'"
        ") "
        "AND Phone != null "
        "AND IsDeleted = false "
        f"AND CreatedDate > {since_iso} "
        "ORDER BY CreatedDate DESC"
    )


# ── Slack ─────────────────────────────────────────────────────────────────────

def _post_slack(text: str) -> bool:
    if not SLACK_TOKEN:
        print("  ⚠  SLACK_BOT_TOKEN not set — skipping Slack.")
        return False
    try:
        import requests
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_TOKEN}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=20,
        )
        data = r.json()
        if not data.get("ok"):
            print(f"  ⚠  Slack error: {data.get('error')}")
            return False
        return True
    except Exception as exc:
        print(f"  ⚠  Slack post failed: {exc}")
        return False


# ── Sync state ────────────────────────────────────────────────────────────────

def _load_sync_state() -> Dict:
    if SYNC_STATE_FILE.exists():
        try:
            return json.loads(SYNC_STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "last_sync": None,
        "last_contact_created_date": "2020-01-01",
    }


def _save_sync_state(state: Dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2))


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _upsert_account(conn: sqlite3.Connection, record: Dict, is_referral: bool = False) -> str:
    """
    Upsert one account row.

    Match order:
      1. sfdc_id  (most reliable)
      2. phone + account_name  (fallback)

    Rules:
      • New rows  → call_status='new', call_count=0
      • Existing  → update name/phone/state/vertical/sfdc_id only;
                    PRESERVE call_status and call_count
    Returns: 'inserted' | 'updated' | 'skipped'
    """
    name = (record.get("account_name") or "").strip()
    phone = (record.get("phone") or "").strip()
    state = (record.get("state") or None)
    vertical = (record.get("vertical") or None)
    sfdc_id = (record.get("sfdc_id") or None)

    if not name or not phone:
        return "skipped"

    now = datetime.now(timezone.utc).isoformat()

    # ── Look up existing row ──────────────────────────────────────────────────
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

    # ── Update existing — preserve call_status and call_count ─────────────────
    if row:
        conn.execute(
            """
            UPDATE accounts
            SET account_name = ?,
                phone        = ?,
                state        = COALESCE(?, state),
                vertical     = COALESCE(?, vertical),
                sfdc_id      = COALESCE(?, sfdc_id)
            WHERE account_id = ?
            """,
            (name, phone, state, vertical, sfdc_id, row["account_id"]),
        )
        return "updated"

    # ── Insert new ────────────────────────────────────────────────────────────
    account_id = str(uuid.uuid4())
    referral_source = "sfdc_referral_contact" if is_referral else None
    conn.execute(
        """
        INSERT INTO accounts
            (account_id, account_name, phone, state, vertical, sfdc_id,
             call_status, call_count, last_called_at, next_call_at,
             agent_id, outcome_notes, referral_source, created_at)
        VALUES
            (?, ?, ?, ?, ?, ?,
             'new', 0, NULL, NULL,
             NULL, NULL, ?, ?)
        """,
        (account_id, name, phone, state, vertical, sfdc_id, referral_source, now),
    )
    return "inserted"


# ── Main sync mode ────────────────────────────────────────────────────────────

def run_sync(states: List[str], db_path: Optional[str] = None, dry_run: bool = False) -> int:
    """
    Full SFDC → accounts.db sync.

    1. Pull accounts (no open opp OR inactive > 30 days)
    2. Upsert into accounts.db
    3. Pull referral contacts and queue as new accounts
    4. Post summary to Slack #activity-log

    Returns shell exit code (0 = success).
    """
    _db_path = Path(db_path) if db_path else DB_PATH
    ts_start = datetime.now(timezone.utc)
    prefix = "[DRY RUN] " if dry_run else ""

    print(f"{prefix}SFDC Sync — {ts_start.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Territory : {', '.join(states)}")
    print(f"  Org alias : {SF_ALIAS}")
    print(f"  DB path   : {_db_path}")
    print()

    # ── Auth check ────────────────────────────────────────────────────────────
    if not _auth_ok():
        msg = f"❌ SFDC Sync FAILED — auth expired for alias `{SF_ALIAS}`. Re-login required."
        print(msg)
        _post_slack(msg)
        return 1

    sync_state = _load_sync_state()
    cutoff_dt = ts_start - timedelta(days=ACTIVITY_DAYS)
    cutoff_date = cutoff_dt.strftime("%Y-%m-%d")

    # ════════════════════════════════════════════════════════════════════════
    # STEP 1: Pull accounts (two queries, merged by Id)
    #
    # SOQL semi-join subqueries cannot be nested inside OR expressions, so we
    # run two separate queries and union them client-side:
    #   A) Accounts with no open Opportunity
    #   B) Accounts inactive > ACTIVITY_DAYS days (or never active)
    # ════════════════════════════════════════════════════════════════════════
    print(f"📥  Pulling accounts (no open opp OR last activity > {ACTIVITY_DAYS} days)…")

    # ── Query A: no open opp ─────────────────────────────────────────────
    soql_a = _build_soql_no_open_opp(states)
    ok_a, out_a = _run_sf(
        ["sf", "data", "query", "--query", soql_a, "--json", "--target-org", SF_ALIAS],
        timeout=180,
    )
    if not ok_a:
        msg = f"❌ SFDC no-open-opp query failed: {out_a[:400]}"
        print(msg)
        _post_slack(f"❌ SFDC Sync error: {msg[:300]}")
        return 1

    # ── Query B: inactive accounts ───────────────────────────────────────
    soql_b = _build_soql_inactive(states, cutoff_date)
    ok_b, out_b = _run_sf(
        ["sf", "data", "query", "--query", soql_b, "--json", "--target-org", SF_ALIAS],
        timeout=180,
    )
    if not ok_b:
        msg = f"❌ SFDC inactive-accounts query failed: {out_b[:400]}"
        print(msg)
        _post_slack(f"❌ SFDC Sync error: {msg[:300]}")
        return 1

    # ── Merge by Id (union, deduped) ─────────────────────────────────────
    try:
        recs_a = json.loads(out_a).get("result", {}).get("records", [])
        recs_b = json.loads(out_b).get("result", {}).get("records", [])
    except Exception as exc:
        print(f"Failed to parse Salesforce output: {exc}")
        return 1

    seen_ids: set = set()
    records: List[Dict] = []
    for rec in recs_a + recs_b:
        rid = rec.get("Id")
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            records.append(rec)

    print(
        f"  → Query A (no open opp): {len(recs_a)} | "
        f"Query B (inactive): {len(recs_b)} | "
        f"Merged unique: {len(records)}\n"
    )

    # ════════════════════════════════════════════════════════════════════════
    # STEP 2: Upsert accounts
    # ════════════════════════════════════════════════════════════════════════
    acct_counts: Dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0}

    if dry_run:
        print(f"[DRY RUN] Would upsert {len(records)} account(s) into {_db_path}")
        for rec in records:
            phone = _normalize_phone_digits(rec.get("Phone"))
            name = rec.get("Name") or ""
            state = _normalize_state(rec.get("BillingState"))
            print(f"   {name[:50]:<52} {state}  {phone}")
            acct_counts["skipped"] += 1
    else:
        conn = sqlite3.connect(str(_db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")

        for rec in records:
            phone = _normalize_phone_digits(rec.get("Phone"))
            name = rec.get("Name") or ""
            state = _normalize_state(rec.get("BillingState"))
            vertical = rec.get("Industry") or rec.get("Type") or ""
            sfdc_id = rec.get("Id") or ""

            result = _upsert_account(
                conn,
                {
                    "account_name": name,
                    "phone": phone,
                    "state": state,
                    "vertical": vertical,
                    "sfdc_id": sfdc_id,
                },
            )
            acct_counts[result] = acct_counts.get(result, 0) + 1

        conn.execute("COMMIT")
        conn.close()

    print(f"  ✔  Inserted : {acct_counts['inserted']}")
    print(f"  ✔  Updated  : {acct_counts['updated']}")
    print(f"  —  Skipped  : {acct_counts['skipped']}")
    print()

    # ════════════════════════════════════════════════════════════════════════
    # STEP 3: Referral contacts
    # ════════════════════════════════════════════════════════════════════════
    last_contact_date = sync_state.get("last_contact_created_date", "2020-01-01")
    print(f"📥  Pulling referral contacts created since {last_contact_date}…")

    ref_soql = _build_soql_referral_contacts(last_contact_date)
    ok2, out2 = _run_sf(
        ["sf", "data", "query", "--query", ref_soql, "--json", "--target-org", SF_ALIAS],
        timeout=60,
    )

    ref_counts: Dict[str, int] = {"inserted": 0, "updated": 0, "no_phone": 0, "skipped": 0}
    newest_contact_date = last_contact_date

    if not ok2:
        print(f"  ⚠  Referral contact query failed (non-fatal): {out2[:300]}")
        print("     Continuing without referral contacts…")
        ref_records: List[Dict] = []
    else:
        try:
            ref_payload = json.loads(out2)
            ref_records = ref_payload.get("result", {}).get("records", [])
        except Exception as exc:
            print(f"  ⚠  Failed to parse referral contact response: {exc}")
            ref_records = []

    print(f"  → {len(ref_records)} referral contact(s) found\n")

    if ref_records:
        if dry_run:
            for ref in ref_records:
                fname = ref.get("FirstName") or ""
                lname = ref.get("LastName") or ""
                acct_info = ref.get("Account") or {}
                org = acct_info.get("Name") if isinstance(acct_info, dict) else ""
                phone = _normalize_phone_digits(ref.get("Phone"))
                lead = ref.get("LeadSource") or ""
                print(f"  [DRY RUN] {fname} {lname} @ {org or '—'}  phone={phone}  source={lead}")
                ref_counts["skipped"] += 1
        else:
            conn = sqlite3.connect(str(_db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")

            for ref in ref_records:
                phone = _normalize_phone_digits(ref.get("Phone"))
                fname = ref.get("FirstName") or ""
                lname = ref.get("LastName") or ""
                contact_name = f"{fname} {lname}".strip()

                # Use Account.Name as the org name; fall back to contact name
                acct_info = ref.get("Account") or {}
                org_name = (
                    acct_info.get("Name")
                    if isinstance(acct_info, dict)
                    else None
                ) or contact_name or "Unknown"

                sfdc_account_id = ref.get("AccountId") or ""
                lead_source = ref.get("LeadSource") or ""
                created_date = (ref.get("CreatedDate") or "")[:10]

                if created_date > newest_contact_date:
                    newest_contact_date = created_date

                if not phone:
                    ref_counts["no_phone"] += 1
                    print(f"  ⚠  No phone for {contact_name} @ {org_name} — skipped")
                    continue

                result = _upsert_account(
                    conn,
                    {
                        "account_name": org_name,
                        "phone": phone,
                        "state": None,  # SFDC Contacts don't carry territory state reliably
                        "vertical": "Referral",
                        "sfdc_id": sfdc_account_id,
                    },
                    is_referral=True,
                )
                ref_counts[result] = ref_counts.get(result, 0) + 1

                if result == "inserted":
                    print(f"  ✅ Queued referral : {contact_name} @ {org_name} [{lead_source}]")
                elif result == "updated":
                    print(f"  ↺  Already exists  : {contact_name} @ {org_name}")

            conn.execute("COMMIT")
            conn.close()

    print(f"  ✔  Referral inserts : {ref_counts['inserted']}")
    print(f"  —  No phone         : {ref_counts['no_phone']}")
    print()

    # ════════════════════════════════════════════════════════════════════════
    # STEP 4: Save sync state
    # ════════════════════════════════════════════════════════════════════════
    if not dry_run:
        sync_state["last_sync"] = ts_start.isoformat()
        sync_state["last_contact_created_date"] = newest_contact_date
        _save_sync_state(sync_state)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 5: Summary + Slack
    # ════════════════════════════════════════════════════════════════════════
    ts_end = datetime.now(timezone.utc)
    elapsed = round((ts_end - ts_start).total_seconds())

    summary_lines = [
        f"{prefix}🔄 *SFDC Nightly Sync* — {ts_start.strftime('%Y-%m-%d %H:%M UTC')} ({elapsed}s)",
        f"*Territory:* {', '.join(states)}   *Cutoff:* {cutoff_date}",
        f"",
        f"*Accounts pulled from SFDC:* {len(records)}",
        f"  • New in DB : {acct_counts['inserted']}",
        f"  • Updated   : {acct_counts['updated']}",
        f"  • Skipped   : {acct_counts['skipped']}",
        f"",
        f"*Referral contacts:* {ref_counts['inserted']} queued, "
        f"{ref_counts['no_phone']} skipped (no phone)",
    ]
    summary = "\n".join(summary_lines)

    print("─" * 60)
    print(summary)
    print("─" * 60)

    if not dry_run:
        _post_slack(summary)

    return 0


# ── Legacy CSV mode ───────────────────────────────────────────────────────────

def run_csv(states: List[str], output: str) -> int:
    """Original CSV pull — unchanged behaviour."""
    soql = _build_soql_csv(states)
    cmd = ["sf", "data", "query", "--query", soql, "--json", "--target-org", SF_ALIAS]

    ok, out = _run_sf(cmd)
    if not ok:
        print(f"Salesforce query failed: {out}")
        return 1

    try:
        payload = json.loads(out)
        records = payload.get("result", {}).get("records", [])
    except Exception as exc:
        print(f"Failed to parse Salesforce output: {exc}")
        return 1

    total = len(records)
    valid = 0
    skipped = 0
    rows = []

    for rec in records:
        phone = _normalize_phone_e164(rec.get("Phone"))
        if not phone:
            skipped += 1
            continue
        name = rec.get("Name") or ""
        state = _normalize_state(rec.get("BillingState"))
        industry = rec.get("Industry") or rec.get("Type") or ""
        notes = f"{name} | {state} | {industry}".strip()
        rows.append(
            {
                "phone": phone,
                "name": name,
                "account": name,
                "state": state,
                "type": rec.get("Type") or "",
                "sf_account_id": rec.get("Id") or "",
                "notes": notes,
            }
        )
        valid += 1

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["phone", "name", "account", "state", "type", "sf_account_id", "notes"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Total queried : {total}")
    print(f"Valid         : {valid}")
    print(f"Skipped       : {skipped}")
    print(f"Output        : {output}")
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pull Salesforce accounts for the AI Voice Caller.\n"
            "Default: write CSV. Use --sync to upsert into accounts.db."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Live-sync mode: upsert SFDC data into accounts.db and post to Slack",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing to DB or Slack (sync mode only)",
    )
    parser.add_argument(
        "--states",
        default=",".join(DEFAULT_STATES),
        help=f"Comma-separated state abbreviations (default: {','.join(DEFAULT_STATES)})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"CSV output path (legacy/CSV mode, default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override accounts.db path (sync mode only)",
    )
    args = parser.parse_args()

    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    if not states:
        print("ERROR: No states provided. Aborting.")
        return 1

    if args.sync:
        return run_sync(states=states, db_path=args.db, dry_run=args.dry_run)
    else:
        return run_csv(states=states, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
