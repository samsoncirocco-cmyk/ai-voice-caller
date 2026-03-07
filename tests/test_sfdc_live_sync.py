"""
Unit tests for execution/sfdc_live_sync.py

Tests use mocking throughout — no real Salesforce connection required.

Run from project root:
    python -m pytest tests/test_sfdc_live_sync.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

# ── path setup ────────────────────────────────────────────────────────────────

EXEC_DIR = Path(__file__).parent.parent / "execution"
sys.path.insert(0, str(EXEC_DIR))
sys.path.insert(0, str(Path(__file__).parent.parent))

from account_db import AccountDB  # noqa: E402
import sfdc_live_sync as sync_mod  # noqa: E402
from sfdc_live_sync import (  # noqa: E402
    SalesforceREST,
    _accounts_soql,
    _normalize_phone,
    _opportunities_soql,
    _apply_stage_to_caller,
    _get_sf_credentials,
    sync,
    STAGE_TO_CALLER_STATE,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_db(tmp_dir: str) -> AccountDB:
    return AccountDB(db_path=os.path.join(tmp_dir, "test_sync.db"))


def _sf_org_display_payload(token: str = "tok123", url: str = "https://sf.example.com") -> str:
    return json.dumps({"status": 0, "result": {"accessToken": token, "instanceUrl": url}})


def _mock_query_response(records: list, next_url: str = None) -> Mock:
    """Build a mock requests.Response for a SOQL query."""
    resp = Mock()
    resp.raise_for_status = Mock()
    payload: dict = {"totalSize": len(records), "done": True, "records": records}
    if next_url:
        payload["nextRecordsUrl"] = next_url
        payload["done"] = False
    resp.json.return_value = payload
    return resp


SAMPLE_ACCOUNT_RECORDS = [
    {
        "Id":           "001000000000001AAA",
        "Name":         "Lincoln Public Schools",
        "Phone":        "+1-402-436-1000",
        "BillingState": "NE",
        "Industry":     "Education",
        "Type":         "K-12",
        "attributes":   {"type": "Account"},
    },
    {
        "Id":           "001000000000002AAA",
        "Name":         "Sioux Falls School District",
        "Phone":        "605-367-7900",
        "BillingState": "SD",
        "Industry":     "Education",
        "Type":         "K-12",
        "attributes":   {"type": "Account"},
    },
    {
        "Id":           "001000000000003AAA",
        "Name":         "No Phone Account",
        "Phone":        None,
        "BillingState": "IA",
        "Industry":     "Government",
        "Type":         None,
        "attributes":   {"type": "Account"},
    },
]

SAMPLE_OPP_RECORDS = [
    {
        "Id":           "006000000000001AAA",
        "Name":         "LPS FortiGate Refresh",
        "AccountId":    "001000000000001AAA",
        "StageName":    "Proposal/Price Quote",
        "Amount":       45000.0,
        "CloseDate":    "2026-04-30",
        "Probability":  60.0,
        "Account": {
            "Name":         "Lincoln Public Schools",
            "BillingState": "NE",
            "Phone":        "+1-402-436-1000",
        },
        "attributes": {"type": "Opportunity"},
    },
    {
        "Id":           "006000000000002AAA",
        "Name":         "SFSD FortiSwitch Upgrade",
        "AccountId":    "001000000000002AAA",
        "StageName":    "Closed Won",
        "Amount":       22000.0,
        "CloseDate":    "2026-03-05",
        "Probability":  100.0,
        "Account": {
            "Name":         "Sioux Falls School District",
            "BillingState": "SD",
            "Phone":        "605-367-7900",
        },
        "attributes": {"type": "Opportunity"},
    },
    {
        "Id":           "006000000000003AAA",
        "Name":         "Stale Renewal",
        "AccountId":    "001000000000099AAA",
        "StageName":    "Closed Lost",
        "Amount":       5000.0,
        "CloseDate":    "2026-02-01",
        "Probability":  0.0,
        "Account": {
            "Name":         "Nowhere County",
            "BillingState": "IA",
            "Phone":        "5151110000",
        },
        "attributes": {"type": "Opportunity"},
    },
]


# ── SOQL builder tests ────────────────────────────────────────────────────────

class TestSOQLBuilders(unittest.TestCase):

    def test_accounts_soql_contains_last_n_hours(self):
        soql = _accounts_soql(24, ["IA", "NE"])
        self.assertIn("LAST_N_HOURS:24", soql)
        self.assertIn("'IA'", soql)
        self.assertIn("'NE'", soql)

    def test_accounts_soql_zero_hours_no_filter(self):
        soql = _accounts_soql(0, ["IA"])
        self.assertNotIn("LAST_N_HOURS", soql)

    def test_accounts_soql_single_state(self):
        soql = _accounts_soql(24, ["SD"])
        self.assertIn("'SD'", soql)
        self.assertIn("BillingState IN", soql)

    def test_opps_soql_contains_last_n_hours(self):
        soql = _opportunities_soql(24, ["NE"])
        self.assertIn("LAST_N_HOURS:24", soql)
        # Note: opps SOQL uses OwnerId filter (not BillingState) because
        # cross-object WHERE on Account.BillingState is not supported via REST API
        self.assertIn("OwnerId", soql)

    def test_opps_soql_selects_stage(self):
        soql = _opportunities_soql(24, ["IA"])
        self.assertIn("StageName", soql)
        self.assertIn("Amount", soql)
        self.assertIn("CloseDate", soql)

    def test_opps_soql_48h(self):
        soql = _opportunities_soql(48, ["SD"])
        self.assertIn("LAST_N_HOURS:48", soql)


# ── phone normalisation tests ─────────────────────────────────────────────────

class TestNormalizePhone(unittest.TestCase):

    def test_plus_dashes(self):
        self.assertEqual(_normalize_phone("+1-402-436-1000"), "14024361000")

    def test_dots(self):
        self.assertEqual(_normalize_phone("+1.605.225.2053"), "16052252053")

    def test_parens(self):
        self.assertEqual(_normalize_phone("(605) 367-7900"), "6053677900")

    def test_plain_digits(self):
        self.assertEqual(_normalize_phone("6053677900"), "6053677900")

    def test_none_or_empty(self):
        self.assertEqual(_normalize_phone(""), "")
        self.assertEqual(_normalize_phone(None), "")  # type: ignore[arg-type]


# ── credential helper tests ───────────────────────────────────────────────────

class TestGetSFCredentials(unittest.TestCase):

    @patch("sfdc_live_sync._run_sf")
    def test_happy_path(self, mock_run):
        mock_run.return_value = (True, _sf_org_display_payload())
        creds = _get_sf_credentials()
        self.assertIsNotNone(creds)
        self.assertEqual(creds["access_token"], "tok123")
        self.assertEqual(creds["instance_url"], "https://sf.example.com")

    @patch("sfdc_live_sync._run_sf")
    def test_cli_failure_returns_none(self, mock_run):
        mock_run.return_value = (False, "error: org not found")
        creds = _get_sf_credentials()
        self.assertIsNone(creds)

    @patch("sfdc_live_sync._run_sf")
    def test_missing_token_returns_none(self, mock_run):
        mock_run.return_value = (True, json.dumps({"result": {"instanceUrl": "https://x.com"}}))
        creds = _get_sf_credentials()
        self.assertIsNone(creds)

    @patch("sfdc_live_sync._run_sf")
    def test_invalid_json_returns_none(self, mock_run):
        mock_run.return_value = (True, "not json at all")
        creds = _get_sf_credentials()
        self.assertIsNone(creds)


# ── SalesforceREST client tests ───────────────────────────────────────────────

class TestSalesforceREST(unittest.TestCase):

    def _make_client(self) -> SalesforceREST:
        return SalesforceREST("mytoken", "https://sf.example.com")

    def test_query_returns_records(self):
        client = self._make_client()
        mock_session = Mock()
        mock_session.get.return_value = _mock_query_response(SAMPLE_ACCOUNT_RECORDS[:2])
        client._session = mock_session

        results = client.query("SELECT Id FROM Account")
        self.assertEqual(len(results), 2)

    def test_query_pagination(self):
        """Query should follow nextRecordsUrl until done."""
        client = self._make_client()
        mock_session = Mock()

        page1 = Mock()
        page1.raise_for_status = Mock()
        page1.json.return_value = {
            "records": SAMPLE_ACCOUNT_RECORDS[:1],
            "nextRecordsUrl": "/services/data/v59.0/query/next",
        }
        page2 = Mock()
        page2.raise_for_status = Mock()
        page2.json.return_value = {
            "records": SAMPLE_ACCOUNT_RECORDS[1:2],
        }
        mock_session.get.side_effect = [page1, page2]
        client._session = mock_session

        results = client.query("SELECT Id FROM Account")
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_session.get.call_count, 2)

    def test_authorization_header_set(self):
        client = self._make_client()
        # Trigger session creation
        sess = client._session_get()
        self.assertIn("Authorization", sess.headers)
        self.assertIn("mytoken", sess.headers["Authorization"])

    @patch("sfdc_live_sync._get_sf_credentials")
    def test_from_sf_cli_returns_none_on_auth_fail(self, mock_creds):
        mock_creds.return_value = None
        result = SalesforceREST.from_sf_cli()
        self.assertIsNone(result)

    @patch("sfdc_live_sync._get_sf_credentials")
    def test_from_sf_cli_returns_client_on_success(self, mock_creds):
        mock_creds.return_value = {"access_token": "tok", "instance_url": "https://sf.example.com"}
        result = SalesforceREST.from_sf_cli()
        self.assertIsNotNone(result)
        self.assertEqual(result.access_token, "tok")


# ── stage-to-caller-state mapping ─────────────────────────────────────────────

class TestApplyStageToCallerState(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = make_db(self.tmp)
        # Insert a test account linked to a SFDC Id
        import uuid, sqlite3
        now = "2026-03-06T03:00:00+00:00"
        conn = sqlite3.connect(str(self.db.db_path))
        conn.execute("""
            INSERT INTO accounts
              (account_id,account_name,phone,state,vertical,sfdc_id,
               call_status,call_count,last_called_at,next_call_at,
               agent_id,outcome_notes,referral_source,created_at)
            VALUES (?,?,?,?,?,?,'new',0,NULL,NULL,NULL,NULL,NULL,?)
        """, (str(uuid.uuid4()), "Test School", "4025550001",
              "NE", "Education", "001000000000001AAA", now))
        conn.commit()
        conn.close()

    def test_closed_won_returns_converted(self):
        result = _apply_stage_to_caller(self.db, "001000000000001AAA", "Closed Won", dry_run=True)
        self.assertEqual(result, "converted")

    def test_closed_lost_returns_not_interested(self):
        result = _apply_stage_to_caller(self.db, "001000000000001AAA", "Closed Lost", dry_run=True)
        self.assertEqual(result, "not_interested")

    def test_open_stage_returns_none(self):
        result = _apply_stage_to_caller(self.db, "001000000000001AAA", "Proposal/Price Quote", dry_run=True)
        self.assertIsNone(result)

    def test_closed_won_updates_db(self):
        _apply_stage_to_caller(self.db, "001000000000001AAA", "Closed Won", dry_run=False)
        stats = self.db.get_stats()
        self.assertEqual(stats.get("converted", 0), 1)

    def test_closed_lost_updates_db(self):
        _apply_stage_to_caller(self.db, "001000000000001AAA", "Closed Lost", dry_run=False)
        stats = self.db.get_stats()
        self.assertEqual(stats.get("not_interested", 0), 1)

    def test_dry_run_does_not_update_db(self):
        _apply_stage_to_caller(self.db, "001000000000001AAA", "Closed Won", dry_run=True)
        stats = self.db.get_stats()
        self.assertEqual(stats.get("new", 0), 1, "dry_run should not write to DB")

    def test_terminal_account_not_overwritten(self):
        """An already-converted account should not be set to not_interested."""
        import sqlite3
        conn = sqlite3.connect(str(self.db.db_path))
        conn.execute("UPDATE accounts SET call_status='converted' WHERE sfdc_id=?",
                     ("001000000000001AAA",))
        conn.commit()
        conn.close()

        updated = self.db.update_state_from_opportunity("001000000000001AAA", "not_interested")
        self.assertEqual(updated, 0, "Terminal account should not be overwritten")
        stats = self.db.get_stats()
        self.assertEqual(stats.get("converted", 0), 1)


# ── opportunities table tests ─────────────────────────────────────────────────

class TestUpsertOpportunity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db  = make_db(self.tmp)

    def test_insert_new_opportunity(self):
        status = self.db.upsert_opportunity(
            sfdc_opp_id="006000000000001AAA",
            opp_name="LPS FortiGate Refresh",
            sfdc_account_id="001000000000001AAA",
            account_name="Lincoln Public Schools",
            stage="Proposal/Price Quote",
            amount=45000.0,
            close_date="2026-04-30",
            probability=60.0,
            state="NE",
        )
        self.assertEqual(status, "inserted")

    def test_update_existing_opportunity(self):
        self.db.upsert_opportunity(
            sfdc_opp_id="006000000000001AAA",
            opp_name="LPS FortiGate Refresh",
            sfdc_account_id="001000000000001AAA",
            account_name="Lincoln Public Schools",
            stage="Proposal/Price Quote",
            amount=45000.0,
            close_date="2026-04-30",
            probability=60.0,
        )
        status = self.db.upsert_opportunity(
            sfdc_opp_id="006000000000001AAA",
            opp_name="LPS FortiGate Refresh",
            sfdc_account_id="001000000000001AAA",
            account_name="Lincoln Public Schools",
            stage="Closed Won",         # stage changed
            amount=45000.0,
            close_date="2026-04-30",
            probability=100.0,
        )
        self.assertEqual(status, "updated")

    def test_get_opportunity_returns_record(self):
        self.db.upsert_opportunity(
            sfdc_opp_id="006000000000001AAA",
            opp_name="Test Opp",
            sfdc_account_id="001AAA",
            account_name="Test Account",
            stage="Prospecting",
            amount=10000.0,
            close_date="2026-06-30",
        )
        opp = self.db.get_opportunity("006000000000001AAA")
        self.assertIsNotNone(opp)
        self.assertEqual(opp["opp_name"], "Test Opp")
        self.assertEqual(opp["stage"], "Prospecting")
        self.assertEqual(opp["amount"], 10000.0)

    def test_get_opportunity_returns_none_for_unknown(self):
        self.assertIsNone(self.db.get_opportunity("006DOESNOTEXIST"))

    def test_get_opportunities_for_account(self):
        for i, stage in enumerate(["Prospecting", "Closed Won"]):
            self.db.upsert_opportunity(
                sfdc_opp_id=f"006{i:015d}",
                opp_name=f"Opp {i}",
                sfdc_account_id="001AAA",
                account_name="Test",
                stage=stage,
                amount=1000.0 * (i + 1),
                close_date="2026-06-30",
            )
        opps = self.db.get_opportunities_for_account("001AAA")
        self.assertEqual(len(opps), 2)

    def test_upsert_preserves_opp_id_on_update(self):
        self.db.upsert_opportunity(
            sfdc_opp_id="006AAA",
            opp_name="Opp",
            sfdc_account_id="001AAA",
            account_name="Test",
            stage="Prospecting",
            amount=1000.0,
            close_date="2026-06-30",
        )
        opp_before = self.db.get_opportunity("006AAA")
        self.db.upsert_opportunity(
            sfdc_opp_id="006AAA",
            opp_name="Opp Updated",
            sfdc_account_id="001AAA",
            account_name="Test",
            stage="Closed Won",
            amount=1000.0,
            close_date="2026-06-30",
        )
        opp_after = self.db.get_opportunity("006AAA")
        self.assertEqual(opp_before["opp_id"], opp_after["opp_id"],
                         "opp_id (local PK) must be stable across updates")

    def test_null_amount_allowed(self):
        status = self.db.upsert_opportunity(
            sfdc_opp_id="006NULL",
            opp_name="Zero Amount",
            sfdc_account_id="001AAA",
            account_name="Test",
            stage="Prospecting",
            amount=None,
            close_date="2026-06-30",
        )
        self.assertEqual(status, "inserted")
        opp = self.db.get_opportunity("006NULL")
        self.assertIsNone(opp["amount"])


# ── full sync() integration tests (mocked REST) ────────────────────────────────

class TestSyncFunction(unittest.TestCase):

    def _make_mock_sf(self, acc_records=None, opp_records=None):
        """Return a mock SalesforceREST whose .query() returns the given records."""
        mock_sf = Mock(spec=SalesforceREST)

        def _query(soql):
            if "FROM Account" in soql:
                return acc_records or []
            if "FROM Opportunity" in soql:
                return opp_records or []
            return []

        mock_sf.query.side_effect = _query
        return mock_sf

    def test_auth_failure_returns_error(self):
        with patch.object(SalesforceREST, "from_sf_cli", return_value=None):
            result = sync(hours=24, states=["IA"])
        self.assertIn("SFDC auth failed", result["errors"][0])
        self.assertEqual(result["accounts_queried"], 0)

    def test_accounts_inserted(self):
        mock_sf = self._make_mock_sf(acc_records=SAMPLE_ACCOUNT_RECORDS, opp_records=[])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["IA", "NE", "SD"],
                              db_path=os.path.join(tmp, "test.db"))
        # 3 records but 1 has no phone — 2 inserted, 1 skipped
        self.assertEqual(result["accounts_queried"], 3)
        self.assertEqual(result["accounts_inserted"], 2)
        self.assertEqual(result["accounts_skipped"], 1)
        self.assertEqual(result["errors"], [])

    def test_opportunities_inserted(self):
        mock_sf = self._make_mock_sf(acc_records=[], opp_records=SAMPLE_OPP_RECORDS)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["IA", "NE", "SD"],
                              db_path=os.path.join(tmp, "test.db"))
        self.assertEqual(result["opps_queried"], 3)
        self.assertEqual(result["opps_inserted"], 3)

    def test_closed_won_transitions_account_state(self):
        """Closed Won opportunity → account in DB should become 'converted'."""
        mock_sf = self._make_mock_sf(
            acc_records=SAMPLE_ACCOUNT_RECORDS[:2],
            opp_records=[SAMPLE_OPP_RECORDS[1]],   # SFSD = Closed Won
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["SD", "NE"], db_path=db_path)

            db = AccountDB(db_path=db_path)
            stats = db.get_stats()
            self.assertEqual(result["state_updates"], 1)
            self.assertEqual(stats.get("converted", 0), 1)

    def test_closed_lost_transitions_account_state(self):
        """Closed Lost opportunity → account in DB should become 'not_interested'."""
        mock_sf = self._make_mock_sf(
            acc_records=SAMPLE_ACCOUNT_RECORDS[2:3],   # No Phone Account (IA)
            opp_records=[SAMPLE_OPP_RECORDS[2]],        # Closed Lost (IA)
        )
        # Manually seed the account with a phone so it gets inserted
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = AccountDB(db_path=db_path)
            import sqlite3, uuid
            now = "2026-03-06T03:00:00+00:00"
            conn = sqlite3.connect(db_path)
            conn.execute("""
                INSERT INTO accounts
                  (account_id,account_name,phone,state,vertical,sfdc_id,
                   call_status,call_count,last_called_at,next_call_at,
                   agent_id,outcome_notes,referral_source,created_at)
                VALUES (?,'Nowhere County','5151110000','IA','Government',
                        '001000000000099AAA','new',0,NULL,NULL,NULL,NULL,NULL,?)
            """, (str(uuid.uuid4()), now))
            conn.commit()
            conn.close()

            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["IA"], db_path=db_path)

            stats = db.get_stats()
            self.assertEqual(result["state_updates"], 1)
            self.assertEqual(stats.get("not_interested", 0), 1)

    def test_dry_run_writes_nothing(self):
        mock_sf = self._make_mock_sf(
            acc_records=SAMPLE_ACCOUNT_RECORDS[:2],
            opp_records=SAMPLE_OPP_RECORDS[:2],
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["NE", "SD"],
                              db_path=db_path, dry_run=True)

            db = AccountDB(db_path=db_path)
            stats = db.get_stats()
            # DB should be empty — no writes
            self.assertEqual(sum(stats.values()), 0)
            self.assertTrue(result["dry_run"])

    def test_account_query_exception_returns_error(self):
        mock_sf = Mock(spec=SalesforceREST)
        mock_sf.query.side_effect = Exception("network timeout")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["IA"],
                              db_path=os.path.join(tmp, "test.db"))
        self.assertTrue(len(result["errors"]) > 0)
        self.assertIn("Account query failed", result["errors"][0])

    def test_opp_query_exception_does_not_abort_accounts(self):
        """Opp query failure is non-fatal: accounts should still be written."""
        mock_sf = Mock(spec=SalesforceREST)

        call_count = [0]
        def side_effect(soql):
            call_count[0] += 1
            if "FROM Account" in soql:
                return SAMPLE_ACCOUNT_RECORDS[:2]
            raise Exception("Opp query blew up")

        mock_sf.query.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["NE", "SD"],
                              db_path=os.path.join(tmp, "test.db"))

        self.assertEqual(result["accounts_inserted"], 2)
        self.assertIn("Opportunity query failed", result["errors"][0])

    def test_upsert_deduplication(self):
        """Running sync twice should not double-insert accounts."""
        mock_sf = self._make_mock_sf(
            acc_records=SAMPLE_ACCOUNT_RECORDS[:2],
            opp_records=[],
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                r1 = sync(hours=24, states=["NE", "SD"], db_path=db_path)
                r2 = sync(hours=24, states=["NE", "SD"], db_path=db_path)

            db = AccountDB(db_path=db_path)
            stats = db.get_stats()
            total = sum(stats.values())
            self.assertEqual(total, 2, "Second sync should not duplicate accounts")
            self.assertEqual(r1["accounts_inserted"], 2)
            self.assertEqual(r2["accounts_updated"], 2)

    def test_summary_keys_present(self):
        mock_sf = self._make_mock_sf(acc_records=[], opp_records=[])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SalesforceREST, "from_sf_cli", return_value=mock_sf):
                result = sync(hours=24, states=["IA"],
                              db_path=os.path.join(tmp, "test.db"))
        for key in ("accounts_queried", "accounts_inserted", "accounts_updated",
                    "accounts_skipped", "opps_queried", "opps_inserted",
                    "opps_updated", "state_updates", "errors", "dry_run"):
            self.assertIn(key, result, f"Missing summary key: {key}")


# ── stage_to_caller_state mapping completeness ────────────────────────────────

class TestStageMapping(unittest.TestCase):

    def test_closed_won_maps_to_converted(self):
        self.assertEqual(STAGE_TO_CALLER_STATE.get("Closed Won"), "converted")

    def test_closed_lost_maps_to_not_interested(self):
        self.assertEqual(STAGE_TO_CALLER_STATE.get("Closed Lost"), "not_interested")

    def test_open_stages_not_mapped(self):
        for stage in ("Prospecting", "Proposal/Price Quote", "Negotiation/Review",
                      "Value Proposition", "Perception Analysis", "Needs Analysis"):
            self.assertNotIn(stage, STAGE_TO_CALLER_STATE,
                             f"Open stage should not be in transition map: {stage}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
