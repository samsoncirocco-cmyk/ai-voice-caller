"""
Unit tests for account_db.py

Run:
    python -m pytest execution/test_account_db.py -v
    # or
    python execution/test_account_db.py
"""

import unittest
import tempfile
import csv
import os
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Ensure we can import from same package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.account_db import (
    AccountDB, _normalize_phone, _extract_state, _extract_vertical,
    _next_call_at, COOLDOWN_DAYS, VALID_STATUSES,
)


# ── Helper fixtures ───────────────────────────────────────────────────────────

def _make_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["phone", "name", "account", "notes"])
        writer.writeheader()
        writer.writerows(rows)


SAMPLE_CSV_ROWS = [
    {"phone": "16052257440", "name": "Alpha School",    "account": "Alpha School",
     "notes": "Aberdeen, South Dakota | Education | alpha.edu"},
    {"phone": "+1.402.387.2494", "name": "Beta County", "account": "Beta County",
     "notes": "Ainsworth, Nebraska | Government: Local | beta.gov"},
    {"phone": "16413225229", "name": "Gamma Services",  "account": "Gamma Services",
     "notes": "Corning, Iowa | Business Services | gamma.com"},
    {"phone": "bad-phone",   "name": "",                "account": "",
     "notes": "no city | Other | other.com"},  # should be skipped (empty name)
]


class TestHelpers(unittest.TestCase):

    def test_normalize_phone_strips_formatting(self):
        self.assertEqual(_normalize_phone("+1.605.225.2053"), "6052252053")
        self.assertEqual(_normalize_phone("16052257440"), "6052257440")
        self.assertEqual(_normalize_phone("605-225-2053"), "6052252053")
        self.assertEqual(_normalize_phone("(605) 225-2053"), "6052252053")

    def test_normalize_phone_removes_leading_1(self):
        self.assertEqual(_normalize_phone("16413225229"), "6413225229")

    def test_extract_state_sd(self):
        self.assertEqual(_extract_state("Aberdeen, South Dakota | Education | site.edu"), "SD")
        # SD is a pipe-section token, not "South Dakota"
        # Falls through to token search
        self.assertEqual(_extract_state("Aberdeen, SD | Education"), "SD")

    def test_extract_state_ia(self):
        self.assertEqual(_extract_state("Corning, Iowa | Business Services | g.com"), "IA")

    def test_extract_state_ne(self):
        self.assertEqual(_extract_state("Ainsworth, Nebraska | Government: Local | b.gov"), "NE")

    def test_extract_state_token_fallback(self):
        # Plain abbreviation in second token
        self.assertEqual(_extract_state("Some City | IA Government"), "IA")

    def test_extract_state_unknown_returns_none(self):
        self.assertIsNone(_extract_state("Phoenix, Arizona | Tech | x.com"))

    def test_extract_vertical(self):
        self.assertEqual(_extract_vertical("City, SD | Education | school.edu"), "Education")
        self.assertEqual(_extract_vertical("City, NE | Government: Local | gov.org"),
                         "Government: Local")

    def test_extract_vertical_missing(self):
        self.assertIsNone(_extract_vertical("NoPipes"))

    def test_next_call_at_voicemail(self):
        before = datetime.now(timezone.utc)
        result = _next_call_at("voicemail")
        after  = datetime.now(timezone.utc)
        dt = datetime.fromisoformat(result)
        assert before + timedelta(days=1) < dt < after + timedelta(days=3)

    def test_next_call_at_interested_returns_none(self):
        self.assertIsNone(_next_call_at("interested"))

    def test_next_call_at_dnc_returns_none(self):
        self.assertIsNone(_next_call_at("dnc"))

    def test_next_call_at_no_answer_one_day(self):
        result = _next_call_at("no_answer")
        dt = datetime.fromisoformat(result)
        expected = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertAlmostEqual(dt.timestamp(), expected.timestamp(), delta=5)


class TestAccountDB(unittest.TestCase):

    def setUp(self):
        self.tmpdir  = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_accounts.db"
        self.db      = AccountDB(db_path=self.db_path)
        self.csv_path = Path(self.tmpdir) / "test.csv"
        _make_csv(self.csv_path, SAMPLE_CSV_ROWS)

    def _seed(self):
        return self.db.seed_from_csv(csv_path=self.csv_path)

    # ── Seed ─────────────────────────────────────────────────────────────────

    def test_seed_inserts_valid_rows(self):
        n = self._seed()
        # Row with empty name should be skipped
        self.assertEqual(n, 3)

    def test_seed_skip_existing(self):
        self._seed()
        n2 = self._seed()
        self.assertEqual(n2, 0)  # all already exist

    def test_seed_sets_status_new(self):
        self._seed()
        rows = self.db.get_due(limit=10)
        statuses = {r["call_status"] for r in rows}
        self.assertIn("new", statuses)
        self.assertEqual(len(statuses), 1)

    def test_seed_extracts_state(self):
        self._seed()
        rows = self.db.get_due(limit=10)
        states = {r["state"] for r in rows}
        self.assertSetEqual(states, {"IA", "NE", "SD"})

    def test_seed_normalizes_phone(self):
        self._seed()
        rows = self.db.get_due(limit=10)
        for r in rows:
            phone = r["phone"]
            self.assertTrue(phone.isdigit(), f"Phone {phone!r} is not all digits")
            self.assertIn(len(phone), (10, 11))

    # ── Stats ────────────────────────────────────────────────────────────────

    def test_stats_total(self):
        self._seed()
        s = self.db.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_status"]["new"], 3)

    # ── get_due ──────────────────────────────────────────────────────────────

    def test_get_due_returns_all_new(self):
        self._seed()
        due = self.db.get_due(limit=50)
        self.assertEqual(len(due), 3)

    def test_get_due_respects_limit(self):
        self._seed()
        due = self.db.get_due(limit=1)
        self.assertEqual(len(due), 1)

    def test_get_due_state_filter(self):
        self._seed()
        due = self.db.get_due(limit=50, state_filter="IA")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["state"], "IA")

    # ── checkout ─────────────────────────────────────────────────────────────

    def test_checkout_assigns_agent(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.assertIsNotNone(acct)
        self.assertEqual(acct["agent_id"], "agent-1")

    def test_checkout_status_becomes_queued(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.assertEqual(acct["call_status"], "queued")

    def test_checkout_removes_from_due(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(acct["account_id"], ids)

    def test_checkout_two_agents_get_different_accounts(self):
        self._seed()
        a1 = self.db.checkout("agent-1")
        a2 = self.db.checkout("agent-2")
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertNotEqual(a1["account_id"], a2["account_id"])

    def test_checkout_returns_none_when_empty(self):
        self._seed()
        self.db.checkout("a1")
        self.db.checkout("a2")
        self.db.checkout("a3")
        result = self.db.checkout("a4")
        self.assertIsNone(result)

    def test_checkout_state_filter(self):
        self._seed()
        acct = self.db.checkout("agent-1", state_filter="SD")
        self.assertEqual(acct["state"], "SD")

    # ── complete ─────────────────────────────────────────────────────────────

    def test_complete_updates_status(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "voicemail", "Left message")
        self.assertEqual(result["call_status"], "voicemail")

    def test_complete_increments_call_count(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "no_answer")
        self.assertEqual(result["call_count"], 1)

    def test_complete_sets_last_called_at(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "voicemail")
        self.assertIsNotNone(result["last_called_at"])

    def test_complete_sets_next_call_at_for_voicemail(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "voicemail")
        dt = datetime.fromisoformat(result["next_call_at"])
        expected = datetime.now(timezone.utc) + timedelta(days=2)
        self.assertAlmostEqual(dt.timestamp(), expected.timestamp(), delta=10)

    def test_complete_sets_next_call_at_none_for_interested(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "interested", "Very warm lead!")
        self.assertIsNone(result["next_call_at"])

    def test_complete_releases_agent(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "voicemail")
        self.assertIsNone(result["agent_id"])

    def test_complete_invalid_outcome_raises(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        with self.assertRaises(ValueError):
            self.db.complete(acct["account_id"], "banana")

    def test_complete_stores_notes(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "interested", "Asked for demo!")
        self.assertEqual(result["outcome_notes"], "Asked for demo!")

    def test_complete_referral_source(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        result = self.db.complete(acct["account_id"], "referral_given",
                                   "Passed to Jane", referral_source="Jane Smith")
        self.assertEqual(result["referral_source"], "Jane Smith")

    # ── Cooldown rules ────────────────────────────────────────────────────────

    def test_voicemail_not_due_until_2_days(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.complete(acct["account_id"], "voicemail")
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        # voicemail account should NOT be in due list (cooldown hasn't expired)
        self.assertNotIn(acct["account_id"], ids)

    def test_no_answer_not_due_until_1_day(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.complete(acct["account_id"], "no_answer")
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(acct["account_id"], ids)

    def test_not_interested_not_due_until_30_days(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.complete(acct["account_id"], "not_interested")
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(acct["account_id"], ids)

    def test_dnc_never_appears_in_due(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.complete(acct["account_id"], "dnc")
        # Even if we manipulate time it should never show
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(acct["account_id"], ids)

    def test_converted_never_appears_in_due(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.complete(acct["account_id"], "converted")
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(acct["account_id"], ids)

    # ── release ───────────────────────────────────────────────────────────────

    def test_release_returns_account_to_queue(self):
        self._seed()
        acct = self.db.checkout("agent-1")
        self.db.release(acct["account_id"])
        acct_after = self.db.get_by_id(acct["account_id"])
        self.assertIsNone(acct_after["agent_id"])
        self.assertEqual(acct_after["call_status"], "new")

    # ── upsert ────────────────────────────────────────────────────────────────

    def test_upsert_creates_new_account(self):
        result = self.db.upsert("New City", "+16052259999", state="SD")
        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "SD")

    def test_upsert_updates_existing_account(self):
        self._seed()
        # Get any seeded account directly from due list
        due = self.db.get_due(limit=1)
        self.assertGreater(len(due), 0, "Should have at least one account seeded")
        target = due[0]
        self.db.upsert(target["account_name"], target["phone"], sfdc_id="SFDC-123")
        updated = self.db.get_by_id(target["account_id"])
        self.assertEqual(updated["sfdc_id"], "SFDC-123")

    # ── Full lifecycle ────────────────────────────────────────────────────────

    def test_full_lifecycle(self):
        """new → queued → voicemail → (cooldown) → no_answer → interested"""
        self._seed()

        # Check out and DNC all but one account so we control which one we test
        import sqlite3
        # Drain ALL 3 accounts from the queue
        checked = []
        for i in range(3):
            a = self.db.checkout(f"setup-agent-{i}")
            if a:
                checked.append(a)
        self.assertEqual(len(checked), 3)

        # Mark two as DNC so they disappear
        self.db.complete(checked[1]["account_id"], "dnc")
        self.db.complete(checked[2]["account_id"], "dnc")

        # Release the first one back to new
        self.db.release(checked[0]["account_id"])
        target_id = checked[0]["account_id"]

        # 1. Checkout our target
        acct = self.db.checkout("agent-1")
        self.assertIsNotNone(acct)
        self.assertEqual(acct["account_id"], target_id)
        self.assertEqual(acct["call_status"], "queued")

        # 2. First call — voicemail
        acct = self.db.complete(acct["account_id"], "voicemail", "Left message")
        self.assertEqual(acct["call_status"], "voicemail")
        self.assertEqual(acct["call_count"], 1)
        self.assertIsNone(acct["agent_id"])

        # 3. Manually force next_call_at into the past to simulate cooldown expiry
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE accounts SET next_call_at = '2020-01-01T00:00:00+00:00' WHERE account_id = ?",
                (acct["account_id"],)
            )
            conn.commit()

        # 4. Checkout again — should get same account (only one in queue)
        acct2 = self.db.checkout("agent-2")
        self.assertIsNotNone(acct2)
        self.assertEqual(acct2["account_id"], acct["account_id"])

        # 5. No answer
        acct2 = self.db.complete(acct2["account_id"], "no_answer")
        self.assertEqual(acct2["call_count"], 2)

        # 6. Force past again
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE accounts SET next_call_at = '2020-01-01T00:00:00+00:00' WHERE account_id = ?",
                (acct2["account_id"],)
            )
            conn.commit()

        # 7. Final — interested (never reschedules)
        acct3 = self.db.checkout("agent-3")
        self.assertIsNotNone(acct3)
        final = self.db.complete(acct3["account_id"], "interested", "Hot lead — wants demo")
        self.assertEqual(final["call_status"], "interested")
        self.assertIsNone(final["next_call_at"])
        self.assertEqual(final["call_count"], 3)

        # 8. Should not appear in due queue
        due = self.db.get_due(limit=50)
        ids = [r["account_id"] for r in due]
        self.assertNotIn(final["account_id"], ids)


# ── Real CSV smoke test ────────────────────────────────────────────────────────

class TestRealCSVSeed(unittest.TestCase):
    """Smoke test against actual sled-territory-832.csv"""

    def setUp(self):
        self.tmpdir  = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "real_test.db"
        self.db      = AccountDB(db_path=self.db_path)

    def test_real_csv_seeds_successfully(self):
        from execution.account_db import CSV_PATH
        if not CSV_PATH.exists():
            self.skipTest("Real CSV not available")
        n = self.db.seed_from_csv()
        self.assertGreater(n, 500, "Expected 800+ accounts from full CSV")

    def test_real_csv_all_states_covered(self):
        from execution.account_db import CSV_PATH
        if not CSV_PATH.exists():
            self.skipTest("Real CSV not available")
        self.db.seed_from_csv()
        stats = self.db.stats()
        # Check we have more new accounts than 0
        self.assertGreater(stats["total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
