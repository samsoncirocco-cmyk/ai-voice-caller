"""
account_db.py — SQLite-backed account state machine for the AI Voice Caller SDR system.

Database: campaigns/accounts.db
Seed:     campaigns/sled-territory-832.csv

State machine transitions:
  new → queued → {voicemail, no_answer, interested, not_interested, dnc, referral_given, converted}

Cooldown rules:
  voicemail      → retry in 2 days
  no_answer      → retry in 1 day
  not_interested → retry in 30 days
  interested     → never re-queue automatically (human takes over)
  dnc            → never re-queue
  referral_given → never re-queue
  converted      → never re-queue

Usage:
  db = AccountDB()                        # opens/creates campaigns/accounts.db
  db.seed_from_csv("campaigns/sled-territory-832.csv")
  account = db.checkout("agent-1")       # atomically grab next due account
  db.complete(account["account_id"], "voicemail", "Left VM at 2pm")
  due = db.get_due(limit=10)
"""

import csv
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── constants ────────────────────────────────────────────────────────────────

VALID_STATUSES = {
    "new", "queued", "voicemail", "no_answer",
    "interested", "not_interested", "dnc", "referral_given", "converted",
}

# Days until next_call_at after each outcome (None = never re-queue)
COOLDOWN_DAYS: Dict[str, Optional[int]] = {
    "voicemail":       2,
    "no_answer":       1,
    "not_interested":  30,
    "interested":      None,   # human takes over
    "dnc":             None,
    "referral_given":  None,
    "converted":       None,
}

# State abbreviation lookup
STATE_MAP = {
    "Iowa":        "IA",
    "Nebraska":    "NE",
    "South Dakota":"SD",
}

DEFAULT_DB_PATH = Path(__file__).parent.parent / "campaigns" / "accounts.db"


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _normalize_phone(raw: str) -> str:
    """Strip all non-digit chars, keep leading 1 if present → 10+ digits."""
    digits = re.sub(r"\D", "", raw)
    return digits


def _parse_notes(notes: str) -> Dict[str, str]:
    """
    Parse 'City, State | Vertical | url' into state abbrev and vertical.
    Returns dict with keys 'state' and 'vertical'.
    """
    parts = [p.strip() for p in notes.split("|")]
    state = ""
    vertical = ""
    if len(parts) >= 1:
        # 'City, State'
        location = parts[0]
        for full, abbrev in STATE_MAP.items():
            if full.lower() in location.lower():
                state = abbrev
                break
    if len(parts) >= 2:
        vertical = parts[1].strip()
    return {"state": state, "vertical": vertical}


# ── main class ────────────────────────────────────────────────────────────────

class AccountDB:
    """
    SQLite-backed state machine for SDR account management.

    Thread-safe via SQLite's WAL mode + BEGIN IMMEDIATE transactions.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── private ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id      TEXT PRIMARY KEY,
                    account_name    TEXT NOT NULL,
                    phone           TEXT NOT NULL,
                    state           TEXT,           -- IA / NE / SD
                    vertical        TEXT,
                    sfdc_id         TEXT,
                    call_status     TEXT NOT NULL DEFAULT 'new',
                    call_count      INTEGER NOT NULL DEFAULT 0,
                    last_called_at  TEXT,           -- ISO-8601 UTC
                    next_call_at    TEXT,           -- ISO-8601 UTC (NULL = due now)
                    agent_id        TEXT,           -- who's actively working it
                    outcome_notes   TEXT,
                    referral_source TEXT,
                    created_at      TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_next_call
                ON accounts (next_call_at, call_status)
            """)

    # ── public API ────────────────────────────────────────────────────────────

    def seed_from_csv(self, csv_path: Optional[str] = None, skip_existing: bool = True) -> int:
        """
        Import sled-territory-832.csv (or any compatible CSV) into the DB.

        Columns expected: phone, name/account_name, account, notes
        All imported rows get call_status='new' and next_call_at=NULL (due immediately).

        Returns: number of rows inserted.
        """
        if csv_path is None:
            csv_path = self.db_path.parent / "sled-territory-832.csv"
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        inserted = 0
        now = _now_utc().isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Normalize field names (CSV has 'name', 'account', 'notes')
                    phone    = _normalize_phone(row.get("phone", ""))
                    name     = (row.get("name") or row.get("account_name") or "").strip()
                    account  = (row.get("account") or name).strip()
                    notes    = row.get("notes", "")
                    sfdc_id  = row.get("sfdc_id", "").strip() or None

                    if not phone or not name:
                        continue

                    parsed   = _parse_notes(notes)
                    state    = parsed["state"]
                    vertical = parsed["vertical"]

                    if skip_existing:
                        existing = conn.execute(
                            "SELECT account_id FROM accounts WHERE phone=? AND account_name=?",
                            (phone, name)
                        ).fetchone()
                        if existing:
                            continue

                    account_id = str(uuid.uuid4())
                    conn.execute("""
                        INSERT INTO accounts
                            (account_id, account_name, phone, state, vertical, sfdc_id,
                             call_status, call_count, last_called_at, next_call_at,
                             agent_id, outcome_notes, referral_source, created_at)
                        VALUES
                            (?, ?, ?, ?, ?, ?,
                             'new', 0, NULL, NULL,
                             NULL, NULL, NULL, ?)
                    """, (account_id, name, phone, state, vertical, sfdc_id, now))
                    inserted += 1
            conn.execute("COMMIT")

        return inserted

    def checkout(self, agent_id: str) -> Optional[Dict]:
        """
        Atomically assign the next due account to agent_id.

        'Due' means:
          - call_status IN ('new', 'voicemail', 'no_answer', 'not_interested')
          - next_call_at IS NULL OR next_call_at <= NOW
          - agent_id IS NULL (not currently checked out)

        Returns the account dict, or None if nothing is available.
        """
        now_iso = _now_utc().isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute("""
                SELECT * FROM accounts
                WHERE call_status IN ('new', 'voicemail', 'no_answer', 'not_interested')
                  AND (next_call_at IS NULL OR next_call_at <= ?)
                  AND agent_id IS NULL
                ORDER BY
                    CASE call_status
                        WHEN 'new'           THEN 1
                        WHEN 'no_answer'     THEN 2
                        WHEN 'voicemail'     THEN 3
                        WHEN 'not_interested'THEN 4
                    END,
                    next_call_at ASC NULLS FIRST
                LIMIT 1
            """, (now_iso,)).fetchone()

            if row is None:
                conn.execute("COMMIT")
                return None

            conn.execute("""
                UPDATE accounts
                SET agent_id    = ?,
                    call_status = 'queued'
                WHERE account_id = ?
            """, (agent_id, row["account_id"]))

            # Re-fetch the updated row so returned dict reflects changes
            updated = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (row["account_id"],)
            ).fetchone()
            conn.execute("COMMIT")

        return dict(updated) if updated else None

    def complete(
        self,
        account_id: str,
        outcome: str,
        notes: str = "",
        referral_source: Optional[str] = None,
    ) -> bool:
        """
        Mark a call complete, set the outcome status, and schedule next_call_at.

        outcome: one of VALID_STATUSES (excluding 'new'/'queued')
        Returns True if the update succeeded.
        """
        if outcome not in VALID_STATUSES or outcome in ("new", "queued"):
            raise ValueError(
                f"Invalid outcome '{outcome}'. Must be one of: "
                + ", ".join(VALID_STATUSES - {"new", "queued"})
            )

        now = _now_utc()
        cooldown = COOLDOWN_DAYS.get(outcome)

        if cooldown is not None:
            next_call = now + timedelta(days=cooldown)
            next_call_iso = next_call.isoformat()
        else:
            next_call_iso = None  # never re-queue automatically

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("""
                UPDATE accounts
                SET call_status    = ?,
                    call_count     = call_count + 1,
                    last_called_at = ?,
                    next_call_at   = ?,
                    agent_id       = NULL,
                    outcome_notes  = ?,
                    referral_source = COALESCE(?, referral_source)
                WHERE account_id = ?
            """, (
                outcome,
                now.isoformat(),
                next_call_iso,
                notes,
                referral_source,
                account_id,
            ))
            conn.execute("COMMIT")
            return cur.rowcount > 0

    def get_due(self, limit: int = 50) -> List[Dict]:
        """
        Return accounts where next_call_at <= now (or IS NULL), ordered by priority.

        Does NOT assign agent_id — use checkout() for exclusive assignment.
        """
        now_iso = _now_utc().isoformat()

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM accounts
                WHERE call_status IN ('new', 'voicemail', 'no_answer', 'not_interested')
                  AND (next_call_at IS NULL OR next_call_at <= ?)
                  AND agent_id IS NULL
                ORDER BY
                    CASE call_status
                        WHEN 'new'           THEN 1
                        WHEN 'no_answer'     THEN 2
                        WHEN 'voicemail'     THEN 3
                        WHEN 'not_interested'THEN 4
                    END,
                    next_call_at ASC NULLS FIRST
                LIMIT ?
            """, (now_iso, limit)).fetchall()

        return [dict(r) for r in rows]

    def get_by_id(self, account_id: str) -> Optional[Dict]:
        """Fetch a single account by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_stats(self) -> Dict[str, int]:
        """Return count of accounts by call_status."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT call_status, COUNT(*) as cnt
                FROM accounts
                GROUP BY call_status
            """).fetchall()
        return {r["call_status"]: r["cnt"] for r in rows}

    def release_stale_checkouts(self, older_than_minutes: int = 60) -> int:
        """
        Return 'queued' accounts back to their prior-state pool if they've been
        checked out for too long without a complete() call.
        Sets status back to 'new' so they get re-queued.
        """
        cutoff = (_now_utc() - timedelta(minutes=older_than_minutes)).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("""
                UPDATE accounts
                SET call_status = 'new',
                    agent_id    = NULL,
                    next_call_at = NULL
                WHERE call_status = 'queued'
                  AND last_called_at < ?
            """, (cutoff,))
            conn.execute("COMMIT")
        return cur.rowcount


# ── CLI seed entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Account DB manager")
    sub = parser.add_subparsers(dest="cmd")

    p_seed = sub.add_parser("seed", help="Seed DB from CSV")
    p_seed.add_argument("--csv", default=None)
    p_seed.add_argument("--db",  default=None)

    p_stats = sub.add_parser("stats", help="Print status counts")
    p_stats.add_argument("--db", default=None)

    p_due = sub.add_parser("due", help="List due accounts")
    p_due.add_argument("--limit", type=int, default=10)
    p_due.add_argument("--db", default=None)

    args = parser.parse_args()

    db = AccountDB(db_path=args.db)

    if args.cmd == "seed":
        n = db.seed_from_csv(args.csv)
        print(f"Inserted {n} accounts.")
        print("Stats:", db.get_stats())

    elif args.cmd == "stats":
        print(json.dumps(db.get_stats(), indent=2))

    elif args.cmd == "due":
        accounts = db.get_due(limit=args.limit)
        print(f"{len(accounts)} due accounts:")
        for a in accounts:
            print(f"  [{a['call_status']:15}] {a['account_name']} ({a['phone']}) [{a['state']}]")

    else:
        parser.print_help()
