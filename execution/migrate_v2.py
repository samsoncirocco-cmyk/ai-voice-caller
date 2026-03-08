#!/usr/bin/env python3
"""
migrate_v2.py — Zero-downtime migration from V1 schema to V2 state-machine schema.

Safe to run multiple times (idempotent).  All operations use "IF NOT EXISTS"
and column-existence checks before altering tables.

What this migration does
------------------------
1.  Creates the V2 tables: accounts_v2, call_attempts, campaigns, agents, referrals
    (opportunities already exists from V1 — preserved as-is)
2.  Migrates every row from `accounts` (V1) → `accounts_v2` (V2)
    - Maps V1.call_status → V2.account_state  (enum values are identical)
    - Maps V1.agent_id    → V2.checked_out_by
    - Copies all other columns with NULL-safe defaults
3.  Writes a migration_log entry so the script skips data migration on re-runs
4.  Optionally seeds `agents` from a list of active agent IDs

Usage
-----
    python3 execution/migrate_v2.py                         # migrate campaigns/accounts.db
    python3 execution/migrate_v2.py --db /path/to/db       # custom db path
    python3 execution/migrate_v2.py --dry-run              # print plan, no writes
    python3 execution/migrate_v2.py --seed-agents agent-1,agent-2
"""

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_v2")

# ── path defaults ─────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
ROOT    = HERE.parent
DEFAULT_DB = ROOT / "campaigns" / "accounts.db"

# ── V1 → V2 state mapping ─────────────────────────────────────────────────────
# V1 used 'call_status'; V2 uses 'account_state' with identical string values
# EXCEPT: 'new' stays 'new', 'queued' → back to 'new' if no active agent
STATE_MAP = {
    "new":            "new",
    "queued":         "new",          # stale queued rows reset to new
    "voicemail":      "voicemail",
    "no_answer":      "no_answer",
    "interested":     "interested",
    "not_interested": "not_interested",
    "dnc":            "dnc",
    "referral_given": "referral_given",
    "converted":      "converted",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _migration_done(conn: sqlite3.Connection, tag: str) -> bool:
    if not _table_exists(conn, "migration_log"):
        return False
    return conn.execute(
        "SELECT 1 FROM migration_log WHERE tag=?", (tag,)
    ).fetchone() is not None


def _mark_migration_done(conn: sqlite3.Connection, tag: str, notes: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO migration_log (tag, applied_at, notes) VALUES (?,?,?)",
        (tag, _now_iso(), notes),
    )


# ── DDL ───────────────────────────────────────────────────────────────────────

CREATE_MIGRATION_LOG = """
CREATE TABLE IF NOT EXISTS migration_log (
    tag        TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    notes      TEXT
)
"""

CREATE_AGENTS = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id          TEXT PRIMARY KEY,
    hostname          TEXT,
    pid               INTEGER,
    status            TEXT NOT NULL DEFAULT 'idle',
    calls_made_today  INTEGER NOT NULL DEFAULT 0,
    calls_made_total  INTEGER NOT NULL DEFAULT 0,
    meetings_booked   INTEGER NOT NULL DEFAULT 0,
    last_call_at      TEXT,
    last_heartbeat_at TEXT,
    registered_at     TEXT NOT NULL
)
"""

CREATE_CAMPAIGNS = """
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id          TEXT PRIMARY KEY,
    campaign_name        TEXT NOT NULL,
    description          TEXT,
    vertical             TEXT,
    state_filter         TEXT,
    prompt_file          TEXT,
    caller_id            TEXT,
    voice_model          TEXT,
    status               TEXT NOT NULL DEFAULT 'draft',
    started_at           TEXT,
    completed_at         TEXT,
    accounts_total       INTEGER NOT NULL DEFAULT 0,
    accounts_called      INTEGER NOT NULL DEFAULT 0,
    accounts_interested  INTEGER NOT NULL DEFAULT 0,
    accounts_voicemail   INTEGER NOT NULL DEFAULT 0,
    accounts_dnc         INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
)
"""

CREATE_ACCOUNTS_V2 = """
CREATE TABLE IF NOT EXISTS accounts_v2 (
    account_id             TEXT PRIMARY KEY,
    account_name           TEXT NOT NULL,
    phone                  TEXT NOT NULL,
    state                  TEXT,
    vertical               TEXT,
    sfdc_id                TEXT,
    website                TEXT,
    account_state          TEXT NOT NULL DEFAULT 'new',
    last_outcome_code      TEXT,
    last_interest_score    INTEGER,
    call_count             INTEGER NOT NULL DEFAULT 0,
    last_called_at         TEXT,
    next_call_at           TEXT,
    callback_requested_at  TEXT,
    checked_out_by         TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
    checked_out_at         TEXT,
    current_call_sid       TEXT,
    referral_source        TEXT,
    referral_parent_id     TEXT REFERENCES accounts_v2(account_id) ON DELETE SET NULL,
    do_not_call            INTEGER NOT NULL DEFAULT 0,
    metadata_json          TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
)
"""

CREATE_CALL_ATTEMPTS = """
CREATE TABLE IF NOT EXISTS call_attempts (
    attempt_id        TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES accounts_v2(account_id) ON DELETE CASCADE,
    campaign_id       TEXT REFERENCES campaigns(campaign_id) ON DELETE SET NULL,
    agent_id          TEXT,
    call_sid          TEXT,
    caller_id         TEXT,
    prompt_file       TEXT,
    voice_model       TEXT,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    duration_secs     INTEGER,
    outcome_code      TEXT,
    interest_score    INTEGER,
    summary_text      TEXT,
    callback_at       TEXT,
    raw_payload_json  TEXT,
    created_at        TEXT NOT NULL
)
"""

CREATE_REFERRALS = """
CREATE TABLE IF NOT EXISTS referrals (
    referral_id             TEXT PRIMARY KEY,
    source_account_id       TEXT REFERENCES accounts_v2(account_id) ON DELETE SET NULL,
    source_call_attempt_id  TEXT REFERENCES call_attempts(attempt_id) ON DELETE SET NULL,
    target_account_id       TEXT REFERENCES accounts_v2(account_id) ON DELETE SET NULL,
    referred_name           TEXT,
    referred_phone          TEXT,
    referred_account        TEXT,
    referred_title          TEXT,
    referred_state          TEXT,
    notes                   TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    created_at              TEXT NOT NULL,
    processed_at            TEXT
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_accounts_v2_state        ON accounts_v2 (account_state)",
    "CREATE INDEX IF NOT EXISTS ix_accounts_v2_next_call    ON accounts_v2 (next_call_at)",
    "CREATE INDEX IF NOT EXISTS ix_accounts_v2_checkout     ON accounts_v2 (checked_out_by)",
    "CREATE INDEX IF NOT EXISTS ix_accounts_v2_sfdc         ON accounts_v2 (sfdc_id)",
    "CREATE INDEX IF NOT EXISTS ix_accounts_v2_schedule     ON accounts_v2 (account_state, next_call_at, checked_out_by)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_v2_phone_name ON accounts_v2 (phone, account_name)",
    "CREATE INDEX IF NOT EXISTS ix_call_attempts_account    ON call_attempts (account_id, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_call_attempts_call_sid   ON call_attempts (call_sid)",
]


# ── migration steps ───────────────────────────────────────────────────────────

def step_create_tables(conn: sqlite3.Connection, dry_run: bool) -> None:
    log.info("Step 1: Creating V2 tables (if not exist)…")
    for ddl in [
        CREATE_MIGRATION_LOG,
        CREATE_AGENTS,
        CREATE_CAMPAIGNS,
        CREATE_ACCOUNTS_V2,
        CREATE_CALL_ATTEMPTS,
        CREATE_REFERRALS,
    ]:
        table_name = ddl.split("CREATE TABLE IF NOT EXISTS")[1].split("(")[0].strip()
        if not dry_run:
            conn.execute(ddl)
        log.info("  ✓ %s", table_name)

    log.info("Step 2: Creating indexes…")
    for idx in INDEXES:
        if not dry_run:
            conn.execute(idx)
    log.info("  ✓ %d indexes", len(INDEXES))


def step_migrate_accounts(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Copy rows from V1 accounts → accounts_v2. Returns migrated count."""
    TAG = "migrate_accounts_v1_to_v2"

    if _migration_done(conn, TAG):
        log.info("Step 3: Account migration already done — skipping.")
        return 0

    if not _table_exists(conn, "accounts"):
        log.info("Step 3: No V1 accounts table — skipping data migration.")
        return 0

    v1_count = _row_count(conn, "accounts")
    log.info("Step 3: Migrating %d V1 accounts → accounts_v2…", v1_count)

    if dry_run:
        log.info("  (dry-run) Would migrate %d rows.", v1_count)
        return v1_count

    rows = conn.execute(
        """
        SELECT account_id, account_name, phone, state, vertical, sfdc_id,
               call_status, call_count, last_called_at, next_call_at,
               agent_id, outcome_notes, referral_source, created_at
        FROM accounts
        """
    ).fetchall()

    now = _now_iso()
    inserted = 0

    for r in rows:
        (account_id, account_name, phone, state, vertical, sfdc_id,
         call_status, call_count, last_called_at, next_call_at,
         agent_id, outcome_notes, referral_source, created_at) = r

        new_state = STATE_MAP.get(call_status, "new")

        # Pack old outcome_notes into metadata_json
        meta = {}
        if outcome_notes:
            meta["v1_outcome_notes"] = outcome_notes
        metadata_json = str(meta) if meta else None

        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO accounts_v2 (
                    account_id, account_name, phone, state, vertical, sfdc_id,
                    account_state, call_count, last_called_at, next_call_at,
                    referral_source, do_not_call, metadata_json, created_at, updated_at
                ) VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?)
                """,
                (
                    account_id, account_name, phone, state, vertical, sfdc_id,
                    new_state, call_count or 0, last_called_at, next_call_at,
                    referral_source, 1 if new_state == "dnc" else 0,
                    metadata_json, created_at or now, now,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError as e:
            log.debug("  Skipping duplicate account %s: %s", account_id, e)

    _mark_migration_done(
        conn, TAG,
        f"Migrated {inserted}/{v1_count} accounts from V1 accounts table"
    )
    log.info("  ✓ Migrated %d / %d accounts", inserted, v1_count)
    return inserted


def step_migrate_call_logs(conn: sqlite3.Connection, dry_run: bool) -> int:
    """
    Synthesise CallAttempt rows from call_summaries.jsonl if it exists.

    Each JSONL entry becomes one call_attempt row. This gives the V2 dashboard
    historical data immediately rather than starting from zero.
    """
    TAG = "migrate_jsonl_to_call_attempts"

    if _migration_done(conn, TAG):
        log.info("Step 4: JSONL → call_attempts migration already done — skipping.")
        return 0

    jsonl_path = ROOT / "logs" / "call_summaries.jsonl"
    if not jsonl_path.exists():
        log.info("Step 4: No call_summaries.jsonl found — skipping.")
        _mark_migration_done(conn, TAG, "No JSONL file found")
        return 0

    import json
    import re

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    log.info("Step 4: Synthesising call_attempts from %d JSONL lines…", len(lines))

    if dry_run:
        log.info("  (dry-run) Would process %d lines.", len(lines))
        return len(lines)

    now = _now_iso()
    inserted = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Resolve account_id from phone number
        to_number = entry.get("to_number", "")
        phone_digits = re.sub(r"\D", "", to_number)

        row = conn.execute(
            "SELECT account_id FROM accounts_v2 WHERE phone=? LIMIT 1",
            (phone_digits,),
        ).fetchone()
        if row is None:
            continue

        account_id = row[0]

        # Map disposition to outcome_code
        disp_map = {
            "voicemail":       "voicemail",
            "no_answer":       "no_answer",
            "interested":      "interested",
            "not_interested":  "not_interested",
            "dnc":             "dnc",
            "meeting_booked":  "meeting_booked",
            "referral_given":  "referral_given",
            "converted":       "converted",
            "error":           "error_swml",
        }
        raw_disp   = entry.get("disposition", "")
        outcome    = disp_map.get(raw_disp.lower(), None)
        call_sid   = entry.get("call_id") or entry.get("call_sid")
        ts_raw     = entry.get("timestamp", now)

        # Handle integer epoch timestamps from SignalWire
        if isinstance(ts_raw, (int, float)):
            ts_raw = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc).isoformat()

        summary    = entry.get("summary", "") or entry.get("call_summary", "")
        interest   = entry.get("interest_score") or entry.get("interest")

        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO call_attempts (
                    attempt_id, account_id, agent_id, call_sid,
                    started_at, ended_at, outcome_code,
                    interest_score, summary_text, raw_payload_json, created_at
                ) VALUES (?,?,?,?, ?,?,?, ?,?,?,?)
                """,
                (
                    str(uuid.uuid4()), account_id, "migrated", call_sid,
                    ts_raw, ts_raw, outcome,
                    interest, summary, json.dumps(entry), now,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass

    _mark_migration_done(
        conn, TAG,
        f"Synthesised {inserted} call_attempt rows from call_summaries.jsonl"
    )
    log.info("  ✓ Inserted %d call_attempt rows from JSONL", inserted)
    return inserted


def step_seed_agents(conn: sqlite3.Connection, agent_ids: list[str], dry_run: bool) -> None:
    if not agent_ids:
        return
    now = _now_iso()
    log.info("Step 5: Seeding %d agents…", len(agent_ids))
    for aid in agent_ids:
        if dry_run:
            log.info("  (dry-run) Would insert agent %s", aid)
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO agents (agent_id, status, registered_at)
            VALUES (?, 'idle', ?)
            """,
            (aid, now),
        )
        log.info("  ✓ Agent %s", aid)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate AI Voice Caller DB to V2 schema")
    parser.add_argument("--db",          default=str(DEFAULT_DB), help="Path to accounts.db")
    parser.add_argument("--dry-run",     action="store_true",     help="Print plan, no writes")
    parser.add_argument("--seed-agents", default="",              help="Comma-sep agent IDs to seed")
    parser.add_argument("--no-backup",   action="store_true",     help="Skip backup step")
    args = parser.parse_args()

    db_path    = Path(args.db)
    dry_run    = args.dry_run
    agent_ids  = [a.strip() for a in args.seed_agents.split(",") if a.strip()]

    if not db_path.exists():
        log.info("Database not found — will create at %s", db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    elif not dry_run and not args.no_backup:
        # Safety backup before any migration
        backup = db_path.with_suffix(f".pre-v2-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
        shutil.copy2(db_path, backup)
        log.info("📦 Backed up %s → %s", db_path.name, backup.name)

    if dry_run:
        log.info("🔍 DRY RUN — no changes will be written")

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        conn.execute("BEGIN")

        step_create_tables(conn, dry_run)
        migrated = step_migrate_accounts(conn, dry_run)
        calls    = step_migrate_call_logs(conn, dry_run)
        step_seed_agents(conn, agent_ids, dry_run)

        if not dry_run:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")

        log.info("")
        log.info("═══════════════════════════════════════")
        log.info("  Migration %s", "plan (dry-run)" if dry_run else "COMPLETE ✅")
        log.info("  Accounts migrated : %d", migrated)
        log.info("  Call attempts seeded: %d", calls)
        log.info("═══════════════════════════════════════")

    except Exception as e:
        conn.execute("ROLLBACK")
        log.exception("Migration FAILED — rolled back: %s", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
