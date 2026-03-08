"""
Unit tests for execution/account_db.py

Run from project root:
    python -m pytest tests/test_account_db.py -v
"""

import csv
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make sure execution/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))

from account_db import AccountDB, _normalize_phone, _parse_notes, COOLDOWN_DAYS


# ── helpers ──────────────────────────────────────────────────────────────────

def make_db(tmp_dir: str) -> AccountDB:
    """Create a fresh in-memory-ish DB in a temp directory."""
    return AccountDB(db_path=os.path.join(tmp_dir, "test_accounts.db"))


def seed_csv(tmp_dir: str, rows: list) -> str:
    """Write a test CSV file and return its path."""
    path = os.path.join(tmp_dir, "test_seed.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["phone", "name", "account", "notes"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return path


SAMPLE_ROWS = [
    {
        "phone": "16052257440",
        "name": "Aberdeen Catholic School System",
        "account": "Aberdeen Catholic School System",
        "notes": "Aberdeen, South Dakota | Education | aberdeenroncalli.org",
    },
    {
        "phone": "+1.605.225.2053",
        "name": "Aberdeen Christian School",
        "account": "Aberdeen Christian School",
        "notes": "Aberdeen, South Dakota | Education: Lower Education | http://www.school.com/",
    },
    {
        "phone": "16413225229",
        "name": "Adams Community",
        "account": "Adams Community",
        "notes": "Corning, Iowa | Business Services | adamscountyiowa.com",
    },
    {
        "phone": "+1.402.387.2494",
        "name": "Ainsworth NE",
        "account": "Ainsworth NE",
        "notes": "Ainsworth, Nebraska | Government: Local | www.ainsworth.com",
    },
]


# ── phone normalization tests ─────────────────────────────────────────────────

class TestNormalizePhone(unittest.TestCase):

    def test_plain_digits(self):
        self.assertEqual(_normalize_phone("16052257440"), "16052257440")

    def test_dots(self):
        self.assertEqual(_normalize_phone("+1.605.225.2053"), "16052252053")

    def test_dashes(self):
        self.assertEqual(_normalize_phone("605-225-2053"), "6052252053")

    def test_parens(self):
        self.assertEqual(_normalize_phone("(605) 225-2053"), "6052252053")

    def test_e164(self):
        self.assertEqual(_normalize_phone("+16052257440"), "16052257440")


# ── notes parsing tests ───────────────────────────────────────────────────────

class TestParseNotes(unittest.TestCase):

    def test_south_dakota(self):
        r = _parse_notes("Aberdeen, South Dakota | Education | example.com")
        self.assertEqual(r["state"], "SD")
        self.assertEqual(r["vertical"], "Education")

    def test_iowa(self):
        r = _parse_notes("Corning, Iowa | Business Services | test.com")
        self.assertEqual(r["state"], "IA")
        self.assertEqual(r["vertical"], "Business Services")

    def test_nebraska(self):
        r = _parse_notes("Ainsworth, Nebraska | Government: Local | test.com")
        self.assertEqual(r["state"], "NE")
        self.assertEqual(r["vertical"], "Government: Local")

    def test_unknown_state(self):
        r = _parse_notes("Dallas, Texas | Technology | example.com")
        self.assertEqual(r["state"], "")

    def test_missing_vertical(self):
        r = _parse_notes("Aberdeen, South Dakota")
        self.assertEqual(r["state"], "SD")
        self.assertEqual(r["vertical"], "")


# ── DB creation and seed tests ────────────────────────────────────────────────

class TestAccountDBSeed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = make_db(self.tmp)

    def test_seed_inserts_rows(self):
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        n = self.db.seed_from_csv(csv_path)
        self.assertEqual(n, 4)

    def test_seed_skips_duplicates(self):
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        first  = self.db.seed_from_csv(csv_path)
        second = self.db.seed_from_csv(csv_path)
        self.assertEqual(first, 4)
        self.assertEqual(second, 0)

    def test_seed_status_is_new(self):
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)
        stats = self.db.get_stats()
        self.assertEqual(stats.get("new", 0), 4)

    def test_seed_parses_state(self):
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)
        due = self.db.get_due(limit=100)
        states = {a["state"] for a in due}
        self.assertIn("SD", states)
        self.assertIn("IA", states)
        self.assertIn("NE", states)

    def test_seed_normalizes_phone(self):
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)
        due = self.db.get_due(limit=100)
        for a in due:
            # All phones should be digits-only
            self.assertTrue(a["phone"].isdigit(), f"Phone not normalized: {a['phone']}")

    def test_seed_missing_phone_skipped(self):
        rows = SAMPLE_ROWS.copy() + [{"phone": "", "name": "Bad Row", "account": "Bad Row", "notes": ""}]
        csv_path = seed_csv(self.tmp, rows)
        n = self.db.seed_from_csv(csv_path)
        self.assertEqual(n, 4)  # blank phone row skipped

    def test_seed_real_csv(self):
        """Integration test against the actual SLED CSV."""
        real_csv = Path(__file__).parent.parent / "campaigns" / "sled-territory-832.csv"
        if real_csv.exists():
            db2 = AccountDB(db_path=os.path.join(self.tmp, "real_test.db"))
            n = db2.seed_from_csv(str(real_csv))
            self.assertGreater(n, 800, "Should import most of the 816-row CSV")
            stats = db2.get_stats()
            self.assertIn("new", stats)


# ── checkout tests ────────────────────────────────────────────────────────────

class TestCheckout(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = make_db(self.tmp)
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)

    def test_checkout_returns_account(self):
        a = self.db.checkout("agent-1")
        self.assertIsNotNone(a)
        self.assertIn("account_id", a)
        self.assertEqual(a["call_status"], "queued")

    def test_checkout_assigns_agent(self):
        a = self.db.checkout("agent-007")
        self.assertEqual(a["agent_id"], "agent-007")

    def test_checkout_exclusive(self):
        """Two checkouts should return different accounts."""
        a1 = self.db.checkout("agent-1")
        a2 = self.db.checkout("agent-2")
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertNotEqual(a1["account_id"], a2["account_id"])

    def test_checkout_exhausts_queue(self):
        for i in range(4):
            self.db.checkout(f"agent-{i}")
        a = self.db.checkout("agent-extra")
        self.assertIsNone(a)

    def test_checkout_empty_db(self):
        db2 = AccountDB(db_path=os.path.join(self.tmp, "empty.db"))
        self.assertIsNone(db2.checkout("agent-1"))

    def test_checkout_respects_next_call_at(self):
        """Accounts with future next_call_at should NOT be checked out."""
        from account_db import _now_utc
        future = (_now_utc() + timedelta(days=5)).isoformat()
        # Manually set all accounts to voicemail w/ future next_call_at
        import sqlite3
        conn = sqlite3.connect(str(self.db.db_path))
        conn.execute(
            "UPDATE accounts SET call_status='voicemail', next_call_at=?, agent_id=NULL",
            (future,)
        )
        conn.commit()
        conn.close()

        result = self.db.checkout("agent-1")
        self.assertIsNone(result)


# ── complete tests ────────────────────────────────────────────────────────────

class TestComplete(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = make_db(self.tmp)
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)
        self.account = self.db.checkout("agent-test")

    def _aid(self):
        return self.account["account_id"]

    def test_complete_sets_status(self):
        self.db.complete(self._aid(), "voicemail", "Left VM")
        a = self.db.get_by_id(self._aid())
        self.assertEqual(a["call_status"], "voicemail")

    def test_complete_increments_call_count(self):
        self.db.complete(self._aid(), "no_answer")
        a = self.db.get_by_id(self._aid())
        self.assertEqual(a["call_count"], 1)

    def test_complete_clears_agent(self):
        self.db.complete(self._aid(), "voicemail")
        a = self.db.get_by_id(self._aid())
        self.assertIsNone(a["agent_id"])

    def test_complete_sets_last_called_at(self):
        self.db.complete(self._aid(), "voicemail")
        a = self.db.get_by_id(self._aid())
        self.assertIsNotNone(a["last_called_at"])

    def test_complete_voicemail_cooldown(self):
        """voicemail → next_call_at ~2 days from now."""
        self.db.complete(self._aid(), "voicemail")
        a = self.db.get_by_id(self._aid())
        self.assertIsNotNone(a["next_call_at"])
        next_dt = datetime.fromisoformat(a["next_call_at"])
        now = datetime.now(timezone.utc)
        delta = next_dt - now
        self.assertAlmostEqual(delta.total_seconds(), 2 * 86400, delta=120)

    def test_complete_no_answer_cooldown(self):
        """no_answer → next_call_at ~1 day from now."""
        self.db.complete(self._aid(), "no_answer")
        a = self.db.get_by_id(self._aid())
        next_dt = datetime.fromisoformat(a["next_call_at"])
        now = datetime.now(timezone.utc)
        delta = next_dt - now
        self.assertAlmostEqual(delta.total_seconds(), 1 * 86400, delta=120)

    def test_complete_not_interested_cooldown(self):
        """not_interested → next_call_at ~30 days from now."""
        self.db.complete(self._aid(), "not_interested")
        a = self.db.get_by_id(self._aid())
        next_dt = datetime.fromisoformat(a["next_call_at"])
        now = datetime.now(timezone.utc)
        delta = next_dt - now
        self.assertAlmostEqual(delta.total_seconds(), 30 * 86400, delta=120)

    def test_complete_interested_no_reschedule(self):
        """interested → next_call_at is NULL (human takes over)."""
        self.db.complete(self._aid(), "interested", "Wants demo")
        a = self.db.get_by_id(self._aid())
        self.assertIsNone(a["next_call_at"])

    def test_complete_dnc_no_reschedule(self):
        self.db.complete(self._aid(), "dnc")
        a = self.db.get_by_id(self._aid())
        self.assertIsNone(a["next_call_at"])

    def test_complete_converted_no_reschedule(self):
        self.db.complete(self._aid(), "converted")
        a = self.db.get_by_id(self._aid())
        self.assertIsNone(a["next_call_at"])

    def test_complete_stores_notes(self):
        self.db.complete(self._aid(), "voicemail", "Left message with receptionist")
        a = self.db.get_by_id(self._aid())
        self.assertEqual(a["outcome_notes"], "Left message with receptionist")

    def test_complete_stores_referral_source(self):
        self.db.complete(self._aid(), "referral_given", "Gave ref to Lincoln SD", "Westside District")
        a = self.db.get_by_id(self._aid())
        self.assertEqual(a["referral_source"], "Westside District")

    def test_complete_invalid_outcome_raises(self):
        with self.assertRaises(ValueError):
            self.db.complete(self._aid(), "totally_made_up")

    def test_complete_queued_raises(self):
        with self.assertRaises(ValueError):
            self.db.complete(self._aid(), "queued")

    def test_complete_returns_true(self):
        result = self.db.complete(self._aid(), "voicemail")
        self.assertTrue(result)

    def test_complete_nonexistent_returns_false(self):
        result = self.db.complete("nonexistent-id-999", "voicemail")
        self.assertFalse(result)


# ── get_due tests ─────────────────────────────────────────────────────────────

class TestGetDue(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = make_db(self.tmp)
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)

    def test_get_due_returns_new_accounts(self):
        due = self.db.get_due()
        self.assertEqual(len(due), 4)

    def test_get_due_limit(self):
        due = self.db.get_due(limit=2)
        self.assertEqual(len(due), 2)

    def test_get_due_excludes_checked_out(self):
        self.db.checkout("agent-1")
        due = self.db.get_due()
        self.assertEqual(len(due), 3)

    def test_get_due_excludes_future_next_call(self):
        a = self.db.checkout("agent-1")
        self.db.complete(a["account_id"], "voicemail")  # next_call_at = 2 days
        due = self.db.get_due()
        ids = [d["account_id"] for d in due]
        self.assertNotIn(a["account_id"], ids)

    def test_get_due_excludes_terminal_statuses(self):
        a1 = self.db.checkout("agent-1")
        self.db.complete(a1["account_id"], "dnc")
        a2 = self.db.checkout("agent-2")
        self.db.complete(a2["account_id"], "converted")
        due = self.db.get_due()
        ids = [d["account_id"] for d in due]
        self.assertNotIn(a1["account_id"], ids)
        self.assertNotIn(a2["account_id"], ids)

    def test_get_due_priority_new_first(self):
        """'new' accounts should sort before 'voicemail' etc."""
        # Complete one as voicemail (future cooldown), then seed a new one separately
        # Actually with our 4 accounts all new, let's modify DB directly to test ordering
        import sqlite3
        from account_db import _now_utc
        conn = sqlite3.connect(str(self.db.db_path))
        past = (_now_utc() - timedelta(hours=1)).isoformat()
        # Set first 2 to voicemail past due
        rows = conn.execute("SELECT account_id FROM accounts LIMIT 2").fetchall()
        for r in rows:
            conn.execute(
                "UPDATE accounts SET call_status='voicemail', next_call_at=?, agent_id=NULL WHERE account_id=?",
                (past, r[0])
            )
        conn.commit()
        conn.close()

        due = self.db.get_due()
        # First items should be 'new', then 'voicemail'
        statuses = [d["call_status"] for d in due]
        new_idx = [i for i, s in enumerate(statuses) if s == "new"]
        vm_idx  = [i for i, s in enumerate(statuses) if s == "voicemail"]
        if new_idx and vm_idx:
            self.assertLess(max(new_idx), min(vm_idx))


# ── stats tests ───────────────────────────────────────────────────────────────

class TestGetStats(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = make_db(self.tmp)
        csv_path = seed_csv(self.tmp, SAMPLE_ROWS)
        self.db.seed_from_csv(csv_path)

    def test_stats_all_new(self):
        stats = self.db.get_stats()
        self.assertEqual(stats["new"], 4)

    def test_stats_after_checkout(self):
        self.db.checkout("agent-1")
        stats = self.db.get_stats()
        self.assertEqual(stats.get("new", 0), 3)
        self.assertEqual(stats.get("queued", 0), 1)

    def test_stats_after_complete(self):
        a = self.db.checkout("agent-1")
        self.db.complete(a["account_id"], "interested", "Hot lead!")
        stats = self.db.get_stats()
        self.assertEqual(stats.get("interested", 0), 1)


# ── full round-trip test ──────────────────────────────────────────────────────

class TestFullRoundTrip(unittest.TestCase):

    def test_full_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AccountDB(db_path=os.path.join(tmp, "rt.db"))
            rows = [
                {"phone": "5555550001", "name": "Acme Schools", "account": "Acme Schools",
                 "notes": "Des Moines, Iowa | Education | acme.edu"},
                {"phone": "5555550002", "name": "Beta District", "account": "Beta District",
                 "notes": "Omaha, Nebraska | Government: Local | beta.gov"},
            ]
            csv_path = seed_csv(tmp, rows)
            db.seed_from_csv(csv_path)

            # Both accounts should be due
            self.assertEqual(len(db.get_due()), 2)

            # Checkout first
            a1 = db.checkout("agent-1")
            self.assertIsNotNone(a1)
            self.assertEqual(len(db.get_due()), 1)

            # Complete as voicemail
            db.complete(a1["account_id"], "voicemail", "Left VM at front desk")
            self.assertEqual(len(db.get_due()), 1)  # a1 is now on 2-day cooldown

            # Checkout second
            a2 = db.checkout("agent-2")
            self.assertIsNotNone(a2)
            self.assertEqual(len(db.get_due()), 0)

            # Complete as interested
            db.complete(a2["account_id"], "interested", "Wants quote asap")
            stats = db.get_stats()
            self.assertEqual(stats["voicemail"], 1)
            self.assertEqual(stats["interested"], 1)

            # Verify interested is NOT in due queue
            self.assertEqual(len(db.get_due()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
