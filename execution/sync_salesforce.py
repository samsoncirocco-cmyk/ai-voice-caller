#!/usr/bin/env python3
"""
sync_salesforce.py — Push AI voice caller data to Salesforce CRM.

Source of truth: logs/call_summaries.jsonl (flat JSONL, NOT Firestore).

For each unsynced call:
  1. Look up account name via campaigns CSV (phone → account)
  2. Resolve Salesforce AccountId (ID from CSV > name lookup > skip)
  3. Log call as a completed Task on the Account
  4. If --with-contacts: read research cache, apply confidence gates,
     create/update Contact (high) or create verify-Task (medium)

Usage:
  python3 execution/sync_salesforce.py --dry-run          # preview only
  python3 execution/sync_salesforce.py                    # sync unprocessed
  python3 execution/sync_salesforce.py --with-contacts    # include contacts
  python3 execution/sync_salesforce.py --since 2026-03-01 # date filter
  python3 execution/sync_salesforce.py --account "Name"   # single account
  python3 execution/sync_salesforce.py --dry-run -v       # verbose dry run
"""

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
SUMMARIES_FILE   = BASE_DIR / "logs" / "call_summaries.jsonl"
SYNC_STATE_FILE  = BASE_DIR / "logs" / "sf_sync_state.json"
CAMPAIGN_CSV     = BASE_DIR / "campaigns" / "sled-territory-832.csv"
RESEARCH_CACHE   = BASE_DIR / "campaigns" / ".research_cache"

# ─── Logging ─────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sf-sync")

# ─── Helpers ─────────────────────────────────────────────────────

def normalize_phone(raw):
    """Strip everything except digits, return 10-digit US number."""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def load_sync_state():
    if SYNC_STATE_FILE.exists():
        with open(SYNC_STATE_FILE) as f:
            return json.load(f)
    return {"synced_call_ids": []}


def save_sync_state(state):
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def build_phone_to_account_map():
    """Build {normalized_phone: {account_name, sf_account_id}} from CSV."""
    phone_map = {}
    if not CAMPAIGN_CSV.exists():
        log.warning("Campaign CSV not found: %s", CAMPAIGN_CSV)
        return phone_map
    with open(CAMPAIGN_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone = normalize_phone(row.get("phone", ""))
            if phone:
                phone_map[phone] = {
                    "account_name": row.get("account", "").strip(),
                    "sf_account_id": row.get("sf_account_id", "").strip() or None,
                }
    log.info("Phone map loaded: %d entries from CSV", len(phone_map))
    return phone_map


# ─── Salesforce via sf CLI ────────────────────────────────────────

_account_id_cache = {}  # account_name → AccountId (or None)


def sf_query(soql, dry_run=False):
    """Run a SOQL query via sf CLI, return list of records."""
    if dry_run:
        log.debug("[dry-run] sf query: %s", soql)
        return []
    try:
        result = subprocess.run(
            ["sf", "data", "query", "--query", soql,
             "--target-org", "production", "--json"],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        if data.get("status") != 0:
            log.warning("sf query failed: %s", data.get("message", result.stderr))
            return []
        return data.get("result", {}).get("records", [])
    except Exception as e:
        log.error("sf_query error: %s", e)
        return []


def sf_create(sobject, fields, dry_run=False):
    """Create a Salesforce record via sf CLI. Returns new Id or None."""
    if dry_run:
        log.info("[dry-run] CREATE %s: %s", sobject, json.dumps(fields))
        return "DRY_RUN_ID"
    try:
        values_args = []
        for k, v in fields.items():
            values_args += ["--values", f"{k}={v}"]
        result = subprocess.run(
            ["sf", "data", "create", "record",
             "--sobject", sobject,
             "--target-org", "production",
             "--json"] + values_args,
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        if data.get("status") != 0:
            log.warning("sf create failed for %s: %s", sobject, data.get("message", result.stderr))
            return None
        return data.get("result", {}).get("id")
    except Exception as e:
        log.error("sf_create error: %s", e)
        return None


def sf_upsert_contact(account_id, contact, dry_run=False):
    """Create or update a Contact under an Account. Uses Email as external ID if available."""
    name_parts = (contact.get("name") or "").strip().split(" ", 1)
    first = name_parts[0] if name_parts else "Unknown"
    last  = name_parts[1] if len(name_parts) > 1 else "Unknown"

    fields = {
        "FirstName": first,
        "LastName": last,
        "Title": contact.get("title") or "",
        "AccountId": account_id,
        "LeadSource": "AI Research",
        "Description": f"Source: {contact.get('source_url','')} | Confidence: {contact.get('confidence','')}",
    }
    if contact.get("email"):
        fields["Email"] = contact["email"]
    if contact.get("phone"):
        fields["Phone"] = contact["phone"]

    if dry_run:
        log.info("[dry-run] UPSERT Contact: %s | %s", contact.get("name"), account_id)
        return "DRY_RUN_ID"

    # Check if contact already exists on this account
    email = contact.get("email")
    if email:
        existing = sf_query(
            f"SELECT Id FROM Contact WHERE Email = '{email}' AND AccountId = '{account_id}'",
            dry_run=False
        )
        if existing:
            rec_id = existing[0]["Id"]
            log.info("  Contact already exists (Id=%s), skipping create", rec_id)
            return rec_id

    return sf_create("Contact", fields, dry_run=dry_run)


def get_account_id(account_name, sf_account_id=None, dry_run=False):
    """Resolve SF AccountId. Use explicit ID first, then name lookup, then None."""
    if sf_account_id:
        return sf_account_id

    if account_name in _account_id_cache:
        return _account_id_cache[account_name]

    # Escape single quotes
    safe_name = account_name.replace("'", "\\'")
    records = sf_query(
        f"SELECT Id FROM Account WHERE Name = '{safe_name}'",
        dry_run=dry_run
    )

    if dry_run:
        _account_id_cache[account_name] = f"DRY_RUN_ACCT_{account_name[:10]}"
        return _account_id_cache[account_name]

    if not records:
        log.warning("  Account not found in SFDC: '%s' — skipping", account_name)
        _account_id_cache[account_name] = None
        return None

    acct_id = records[0]["Id"]
    _account_id_cache[account_name] = acct_id
    log.debug("  Account resolved: %s → %s", account_name, acct_id)
    return acct_id


# ─── Research Cache ───────────────────────────────────────────────

def load_research_contacts(account_name):
    """Load research contacts from cache for an account."""
    if not RESEARCH_CACHE.exists():
        return []
    safe_name = re.sub(r"[^\w\-]", "_", account_name)[:80]
    cache_file = RESEARCH_CACHE / f"{safe_name}.json"
    if not cache_file.exists():
        return []
    try:
        with open(cache_file) as f:
            data = json.load(f)
        return data.get("contacts", [])
    except Exception as e:
        log.warning("  Could not load research cache for %s: %s", account_name, e)
        return []


# ─── Core Sync Logic ──────────────────────────────────────────────

def sync_call(call, account_info, account_id, args, stats):
    """Sync a single call record to Salesforce."""
    call_id    = call.get("call_id", "unknown")
    summary    = call.get("summary", "").strip()
    timestamp  = call.get("timestamp", "")
    account_name = account_info.get("account_name", "Unknown")

    log.info("Processing call %s | %s", call_id, account_name)

    # ── 1. Log call as Task ───────────────────────────────────────
    # Parse outcome from summary
    outcome = "Completed"
    if summary:
        if any(w in summary.lower() for w in ["voicemail", "no answer", "left message"]):
            outcome = "No Answer"
        elif any(w in summary.lower() for w in ["callback", "call back", "follow-up"]):
            outcome = "Callback Requested"
        elif any(w in summary.lower() for w in ["not interested", "do not call", "remove"]):
            outcome = "Not Interested"

    activity_date = timestamp[:10] if timestamp else datetime.now().strftime("%Y-%m-%d")
    desc = summary[:500] if summary else f"AI outbound call | call_id: {call_id}"

    task_fields = {
        "Subject": f"AI Call - {outcome}",
        "Status": "Completed",
        "ActivityDate": activity_date,
        "Description": desc,
        "WhatId": account_id,
        "CallType": "Outbound",
    }

    task_id = sf_create("Task", task_fields, dry_run=args.dry_run)
    if task_id:
        log.info("  ✓ Task created: %s (outcome: %s)", task_id, outcome)
        stats["tasks_created"] += 1
    else:
        stats["errors"] += 1

    # ── 2. Contact candidates (if --with-contacts) ────────────────
    if args.with_contacts:
        contacts = load_research_contacts(account_name)
        if not contacts:
            log.debug("  No research contacts found for %s", account_name)

        for c in contacts:
            conf = c.get("confidence", "low").lower()
            name = c.get("name") or "Unknown"

            if conf == "high":
                contact_id = sf_upsert_contact(account_id, c, dry_run=args.dry_run)
                if contact_id:
                    log.info("  ✓ Contact created/updated: %s (%s)", name, contact_id)
                    stats["contacts_created"] += 1
                else:
                    stats["errors"] += 1

            elif conf == "medium":
                verify_task = {
                    "Subject": f"Verify IT contact: {name}",
                    "Status": "Not Started",
                    "Priority": "Normal",
                    "Description": (
                        f"Research candidate: {name} | {c.get('title','')} | "
                        f"Source: {c.get('source_url','')} | Confidence: medium"
                    ),
                    "WhatId": account_id,
                }
                tid = sf_create("Task", verify_task, dry_run=args.dry_run)
                if tid:
                    log.info("  ✓ Verify-task for %s (medium confidence)", name)
                    stats["verify_tasks_created"] += 1

            else:  # low or unknown
                log.debug("  Skipping low-confidence contact: %s", name)
                stats["contacts_skipped"] += 1


# ─── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync AI voice caller logs to Salesforce")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no SF writes")
    parser.add_argument("--with-contacts", action="store_true",
                        help="Also sync research contact candidates (confidence-gated)")
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only sync calls on or after this date")
    parser.add_argument("--account", metavar="NAME",
                        help="Only sync calls for this account name")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    if args.dry_run:
        log.info("=== DRY RUN — no SF writes will occur ===")

    # Load state + data
    state = load_sync_state()
    synced_ids = set(state.get("synced_call_ids", []))
    phone_map = build_phone_to_account_map()

    if not SUMMARIES_FILE.exists():
        log.error("No call summaries found at %s", SUMMARIES_FILE)
        sys.exit(1)

    # Parse date filter
    since_dt = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except ValueError:
            log.error("Invalid --since date: %s (use YYYY-MM-DD)", args.since)
            sys.exit(1)

    stats = {
        "processed": 0,
        "skipped_already_synced": 0,
        "skipped_no_account": 0,
        "tasks_created": 0,
        "contacts_created": 0,
        "verify_tasks_created": 0,
        "contacts_skipped": 0,
        "errors": 0,
    }

    newly_synced = []

    with open(SUMMARIES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                call = json.loads(line)
            except json.JSONDecodeError:
                continue

            call_id = call.get("call_id", "")
            if not call_id:
                continue

            # Skip already synced
            if call_id in synced_ids:
                stats["skipped_already_synced"] += 1
                continue

            # Date filter
            if since_dt and call.get("timestamp"):
                try:
                    call_dt = datetime.fromisoformat(call["timestamp"])
                    if call_dt < since_dt:
                        continue
                except ValueError:
                    pass

            # Resolve account
            to_phone = normalize_phone(call.get("to", ""))
            account_info = phone_map.get(to_phone, {})

            if not account_info:
                log.debug("  No account found for phone %s — skipping", to_phone)
                stats["skipped_no_account"] += 1
                continue

            account_name = account_info.get("account_name", "")

            # Account name filter
            if args.account and args.account.lower() not in account_name.lower():
                continue

            if not account_name:
                stats["skipped_no_account"] += 1
                continue

            # Resolve SFDC AccountId
            account_id = get_account_id(
                account_name,
                sf_account_id=account_info.get("sf_account_id"),
                dry_run=args.dry_run
            )

            if not account_id:
                stats["skipped_no_account"] += 1
                continue

            # Sync it
            sync_call(call, account_info, account_id, args, stats)
            stats["processed"] += 1
            newly_synced.append(call_id)

    # Persist sync state
    if not args.dry_run and newly_synced:
        state["synced_call_ids"] = list(synced_ids) + newly_synced
        save_sync_state(state)
        log.info("Sync state updated: %d total synced call_ids", len(state["synced_call_ids"]))

    # Summary
    print("\n=== Sync Summary ===")
    print(f"  Processed:               {stats['processed']}")
    print(f"  Already synced (skipped):{stats['skipped_already_synced']}")
    print(f"  No account match:        {stats['skipped_no_account']}")
    print(f"  Tasks created:           {stats['tasks_created']}")
    if args.with_contacts:
        print(f"  Contacts created:        {stats['contacts_created']}")
        print(f"  Verify-tasks created:    {stats['verify_tasks_created']}")
        print(f"  Low-conf skipped:        {stats['contacts_skipped']}")
    print(f"  Errors:                  {stats['errors']}")
    if args.dry_run:
        print("\n[DRY RUN] No changes were written to Salesforce.")

    sys.exit(1 if stats["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
