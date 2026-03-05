"""
account_db.py — SQLite-backed account state machine for the AI Voice Caller SDR system.

DB: campaigns/accounts.db
State machine controls which accounts get called, by whom, and when.

Usage:
    from execution.account_db import AccountDB
    db = AccountDB()
    account = db.checkout("agent-1")
    db.complete(account["account_id"], "voicemail", "Left message about Fortinet SD-WAN")

CLI:
    python execution/account_db.py seed          # Import CSV into DB
    python execution/account_db.py status        # Print queue stats
    python execution/account_db.py due           # List due accounts
    python execution/account_db.py reset-db      # Wipe and reseed
"""

import sqlite3
import csv
import uuid
import os
import re
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "campaigns" / "accounts.db"
CSV_PATH     = PROJECT_ROOT / "campaigns" / "sled-territory-832.csv"

# ── Valid enumerations ────────────────────────────────────────────────────────
VALID_STATES   = {"IA", "NE", "SD"}
VALID_STATUSES = {
    "new", "queued", "voicemail", "no_answer",
    "interested", "not_interested", "dnc",
    "referral_given", "converted",
}

# ── Cooldown rules (None = never reschedule) ─────────────────────────────────
COOLDOWN_DAYS: dict[str, int | None] = {
    "voicemail":       2,
    "no_answer":       1,
    "not_interested":  30,
    "interested":      None,   # never auto-reschedule; human decides
    "dnc":             None,
    "referral_given":  None,
    "converted":       None,
    "new":             0,
    "queued":          0,
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _normalize_phone(raw: str) -> str:
    """Strip everything except digits. Return 10-digit or 11-digit string."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


_STATE_NAME_MAP: dict[str, str] = {
    # Full names used in the CSV
    "iowa":         "IA",
    "nebraska":     "NE",
    "south dakota": "SD",
    # Abbreviations
    "ia": "IA",
    "ne": "NE",
    "sd": "SD",
}


def _extract_state(notes: str) -> str | None:
    """
    Notes column looks like: 'City, State | Vertical | URL'
    Handles both full state names ('South Dakota') and abbreviations ('SD').
    """
    # 1. Try multi-word full state names first (e.g. "South Dakota")
    lower_notes = notes.lower()
    for name, abbrev in _STATE_NAME_MAP.items():
        if len(name) > 2 and name in lower_notes:
            return abbrev

    # 2. Try "City, ST" abbreviated pattern
    m = re.search(r",\s+([A-Z]{2})\b", notes)
    if m and m.group(1) in VALID_STATES:
        return m.group(1)

    # 3. Fallback: standalone 2-letter abbreviation in any pipe-section token
    for tok in notes.split("|"):
        tok = tok.strip()
        m2 = re.search(r"\b(IA|NE|SD)\b", tok)
        if m2:
            return m2.group(1)

    return None


def _extract_vertical(notes: str) -> str | None:
    """Notes column: 'City, State | Vertical | URL'. Second pipe-section is vertical."""
    parts = [p.strip() for p in notes.split("|")]
    if len(parts) >= 2:
        return parts[1].strip()
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_call_at(status: str) -> str | None:
    days = COOLDOWN_DAYS.get(status)
    if days is None:
        return None
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.isoformat()


# ── Database class ────────────────────────────────────────────────────────────
class AccountDB:
    """
    SQLite-backed account state machine.

    Thread-safe via WAL mode + exclusive transactions on checkout.
    """

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Connection ────────────────────────────────────────────────────────────
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema ────────────────────────────────────────────────────────────────
    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
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
                    next_call_at    TEXT,           -- ISO-8601 UTC  (NULL = never)
                    agent_id        TEXT,           -- currently checked out by
                    outcome_notes   TEXT,
                    referral_source TEXT,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_next_call
                    ON accounts (next_call_at, call_status);

                CREATE INDEX IF NOT EXISTS idx_state
                    ON accounts (state);

                CREATE INDEX IF NOT EXISTS idx_status
                    ON accounts (call_status);
            """)

    # ── Seed from CSV ─────────────────────────────────────────────────────────
    def seed_from_csv(self, csv_path: str | Path = CSV_PATH, skip_existing: bool = True) -> int:
        """
        Import sled-territory-832.csv into the DB.
        Returns number of rows inserted.
        Skips rows whose phone already exists if skip_existing=True.
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        inserted = 0
        now = _now_iso()
        next_call = _next_call_at("new")  # immediately due

        with self._conn() as conn:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_phone = (row.get("phone") or "").strip()
                    name      = (row.get("name") or row.get("account") or "").strip()
                    notes     = (row.get("notes") or "").strip()

                    if not raw_phone or not name:
                        continue

                    phone    = _normalize_phone(raw_phone)
                    state    = _extract_state(notes)
                    vertical = _extract_vertical(notes)

                    if skip_existing:
                        existing = conn.execute(
                            "SELECT account_id FROM accounts WHERE phone = ?", (phone,)
                        ).fetchone()
                        if existing:
                            continue

                    conn.execute("""
                        INSERT INTO accounts (
                            account_id, account_name, phone, state, vertical,
                            sfdc_id, call_status, call_count,
                            last_called_at, next_call_at,
                            agent_id, outcome_notes, referral_source,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, NULL, 'new', 0, NULL, ?, NULL, NULL, NULL, ?, ?)
                    """, (
                        str(uuid.uuid4()), name, phone, state, vertical,
                        next_call, now, now,
                    ))
                    inserted += 1

        return inserted

    # ── Core state machine methods ────────────────────────────────────────────

    def checkout(self, agent_id: str, state_filter: str | None = None,
                 vertical_filter: str | None = None) -> dict | None:
        """
        Atomically assigns the next due account to agent_id.

        Priority: new > no_answer > voicemail > not_interested (cooldown expired).
        Returns account dict or None if nothing is due.
        """
        now = _now_iso()

        with sqlite3.connect(str(self.db_path), timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")

            # Exclusive transaction to prevent two agents grabbing the same row
            conn.execute("BEGIN EXCLUSIVE")
            try:
                where_clauses = [
                    "agent_id IS NULL",
                    "call_status NOT IN ('dnc', 'converted', 'interested', 'referral_given')",
                    "(next_call_at IS NULL OR next_call_at <= ?)",
                ]
                params: list = [now]

                if state_filter:
                    where_clauses.append("state = ?")
                    params.append(state_filter)

                if vertical_filter:
                    where_clauses.append("vertical LIKE ?")
                    params.append(f"%{vertical_filter}%")

                where_sql = " AND ".join(where_clauses)
                priority_sql = """
                    CASE call_status
                        WHEN 'new'            THEN 0
                        WHEN 'no_answer'      THEN 1
                        WHEN 'voicemail'      THEN 2
                        WHEN 'not_interested' THEN 3
                        WHEN 'queued'         THEN 4
                        ELSE 5
                    END
                """

                row = conn.execute(f"""
                    SELECT * FROM accounts
                    WHERE {where_sql}
                    ORDER BY {priority_sql}, next_call_at ASC
                    LIMIT 1
                """, params).fetchone()

                if not row:
                    conn.commit()
                    return None

                account_id = row["account_id"]
                conn.execute("""
                    UPDATE accounts
                    SET agent_id   = ?,
                        call_status = CASE WHEN call_status = 'new' THEN 'queued' ELSE call_status END,
                        updated_at  = ?
                    WHERE account_id = ?
                """, (agent_id, now, account_id))

                conn.commit()
                # Re-fetch to return final state
                updated = conn.execute(
                    "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
                ).fetchone()
                return dict(updated)

            except Exception:
                conn.rollback()
                raise

    def complete(self, account_id: str, outcome: str,
                 notes: str = "", referral_source: str | None = None) -> dict:
        """
        Record call outcome, increment call_count, set next_call_at per cooldown rules.

        outcome must be one of VALID_STATUSES.
        Returns updated account dict.
        """
        if outcome not in VALID_STATUSES:
            raise ValueError(f"Invalid outcome '{outcome}'. Must be one of {VALID_STATUSES}")

        now          = _now_iso()
        next_call    = _next_call_at(outcome)

        with self._conn() as conn:
            conn.execute("""
                UPDATE accounts
                SET call_status    = ?,
                    call_count     = call_count + 1,
                    last_called_at = ?,
                    next_call_at   = ?,
                    agent_id       = NULL,
                    outcome_notes  = ?,
                    referral_source = COALESCE(?, referral_source),
                    updated_at     = ?
                WHERE account_id = ?
            """, (outcome, now, next_call, notes, referral_source, now, account_id))

            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Account {account_id} not found")
            return dict(row)

    def get_due(self, limit: int = 50, state_filter: str | None = None) -> list[dict]:
        """
        Return up to `limit` accounts where next_call_at <= now and not checked out.
        Ordered by priority (new first) then by next_call_at ascending.
        """
        now = _now_iso()
        params: list = [now]
        state_clause = ""
        if state_filter:
            state_clause = "AND state = ?"
            params.append(state_filter)

        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM accounts
                WHERE agent_id IS NULL
                  AND call_status NOT IN ('dnc', 'converted', 'interested', 'referral_given')
                  AND (next_call_at IS NULL OR next_call_at <= ?)
                  {state_clause}
                ORDER BY
                    CASE call_status
                        WHEN 'new'            THEN 0
                        WHEN 'no_answer'      THEN 1
                        WHEN 'voicemail'      THEN 2
                        WHEN 'not_interested' THEN 3
                        WHEN 'queued'         THEN 4
                        ELSE 5
                    END,
                    next_call_at ASC
                LIMIT ?
            """, params).fetchall()
            return [dict(r) for r in rows]

    def release(self, account_id: str) -> None:
        """Release an account back to the queue without recording an outcome (e.g., agent crash)."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE accounts
                SET agent_id   = NULL,
                    call_status = CASE WHEN call_status = 'queued' THEN 'new' ELSE call_status END,
                    updated_at  = ?
                WHERE account_id = ?
            """, (_now_iso(), account_id))

    def get_by_id(self, account_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_by_phone(self, phone: str) -> dict | None:
        phone = _normalize_phone(phone)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE phone = ?", (phone,)
            ).fetchone()
            return dict(row) if row else None

    def upsert(self, account_name: str, phone: str, state: str | None = None,
               vertical: str | None = None, sfdc_id: str | None = None,
               referral_source: str | None = None) -> dict:
        """Insert or update an account. If phone exists, update metadata only."""
        phone_norm = _normalize_phone(phone)
        existing = self.get_by_phone(phone_norm)
        now = _now_iso()

        if existing:
            with self._conn() as conn:
                conn.execute("""
                    UPDATE accounts
                    SET account_name    = ?,
                        state           = COALESCE(?, state),
                        vertical        = COALESCE(?, vertical),
                        sfdc_id         = COALESCE(?, sfdc_id),
                        referral_source = COALESCE(?, referral_source),
                        updated_at      = ?
                    WHERE phone = ?
                """, (account_name, state, vertical, sfdc_id, referral_source, now, phone_norm))
            return self.get_by_phone(phone_norm)

        with self._conn() as conn:
            account_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO accounts (
                    account_id, account_name, phone, state, vertical,
                    sfdc_id, call_status, call_count,
                    last_called_at, next_call_at,
                    agent_id, outcome_notes, referral_source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'new', 0, NULL, ?, NULL, NULL, ?, ?, ?)
            """, (account_id, account_name, phone_norm, state, vertical,
                  sfdc_id, _next_call_at("new"), referral_source, now, now))
        return self.get_by_phone(phone_norm)

    def stats(self) -> dict:
        """Return status counts and total."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT call_status, COUNT(*) as cnt
                FROM accounts
                GROUP BY call_status
                ORDER BY cnt DESC
            """).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            checked_out = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE agent_id IS NOT NULL"
            ).fetchone()[0]

        return {
            "total": total,
            "checked_out": checked_out,
            "by_status": {r["call_status"]: r["cnt"] for r in rows},
        }


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cli():
    db = AccountDB()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "seed":
        n = db.seed_from_csv()
        print(f"✅ Seeded {n} accounts from {CSV_PATH.name}")

    elif cmd == "status":
        s = db.stats()
        print(f"📊 Total accounts: {s['total']}")
        print(f"   Checked out   : {s['checked_out']}")
        print("   By status:")
        for status, cnt in s["by_status"].items():
            print(f"     {status:<18} {cnt}")

    elif cmd == "due":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        rows = db.get_due(limit=limit)
        print(f"📋 {len(rows)} due accounts:")
        for r in rows:
            print(f"  [{r['state']}] {r['account_name']} ({r['phone']}) — {r['call_status']}")

    elif cmd == "reset-db":
        if DB_PATH.exists():
            DB_PATH.unlink()
            print("🗑  Deleted existing DB")
        db2 = AccountDB()
        n = db2.seed_from_csv()
        print(f"✅ Fresh DB seeded with {n} accounts")

    elif cmd == "checkout":
        agent = sys.argv[2] if len(sys.argv) > 2 else "cli-agent"
        acct = db.checkout(agent)
        if acct:
            print(json.dumps(acct, indent=2))
        else:
            print("Nothing due.")

    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
