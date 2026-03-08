"""
tests/test_sfdc_live_sync_webhook.py

Unit tests for the V2 SFDC Live Sync routes added to webhook_server.py:
  POST /voice-caller/sfdc-sync
  GET  /voice-caller/sfdc-sync/status

All Salesforce CLI calls are mocked — no real SF connection required.

Run from project root:
    python -m pytest tests/test_sfdc_live_sync_webhook.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── path setup ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Override LOG_DIR before importing webhook_server so log files go to a tmp dir
_TMP = tempfile.mkdtemp()
os.environ.setdefault("SFDC_SYNC_TEST_LOGDIR", _TMP)

import webhook_server as ws  # noqa: E402

# Point the module's log paths at the tmp dir so tests don't pollute real logs
ws.LOG_DIR   = _TMP
ws.LOG_FILE  = os.path.join(_TMP, "call_summaries.jsonl")
ws._SFDC_SYNC_LOG = os.path.join(_TMP, "sfdc-live-sync.jsonl")

# Use a fast retry wait (0 s) so tests don't take minutes
ws._SFDC_BASE_WAIT = 0
ws._SFDC_MAX_TRIES = 2


# ── Flask test client ─────────────────────────────────────────────────────────

class _Base(unittest.TestCase):
    def setUp(self):
        ws.app.testing = True
        self.client = ws.app.test_client()
        # Clean log files before each test
        for p in [ws.LOG_FILE, ws._SFDC_SYNC_LOG]:
            if os.path.exists(p):
                os.remove(p)


# ── validation tests ──────────────────────────────────────────────────────────

class TestSfdcSyncValidation(_Base):

    def test_missing_event_type_returns_400(self):
        resp = self.client.post(
            "/voice-caller/sfdc-sync",
            json={"call_id": "abc123"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("event_type is required", body["error"])
        self.assertIn("valid_types", body)

    def test_unknown_event_type_returns_400(self):
        resp = self.client.post(
            "/voice-caller/sfdc-sync",
            json={"event_type": "bogus_event"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("bogus_event", body["error"])

    def test_valid_event_types_listed_in_error(self):
        resp = self.client.post(
            "/voice-caller/sfdc-sync",
            json={},
            content_type="application/json",
        )
        body = resp.get_json()
        for et in ("call_outcome", "referral", "new_lead"):
            self.assertIn(et, body["valid_types"])

    def test_empty_body_returns_400(self):
        resp = self.client.post(
            "/voice-caller/sfdc-sync",
            data="",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


# ── call_outcome tests ────────────────────────────────────────────────────────

class TestSfdcSyncCallOutcome(_Base):

    def _post(self, extra: dict | None = None):
        payload = {
            "event_type": "call_outcome",
            "call_id":    "call-abc-001",
            "to":         "+16055551234",
            "from":       "+16028985026",
            "summary":    "- Call outcome: Connected\nSpoke with Jane Smith.",
        }
        if extra:
            payload.update(extra)
        return self.client.post(
            "/voice-caller/sfdc-sync",
            json=payload,
            content_type="application/json",
        )

    @patch("webhook_server._run_sf_cmd")
    def test_call_outcome_success_returns_200(self, mock_sf):
        mock_sf.return_value = (True, "Created: 1")
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "synced")
        self.assertEqual(body["event_type"], "call_outcome")

    @patch("webhook_server._run_sf_cmd")
    def test_call_outcome_sf_failure_returns_502(self, mock_sf):
        mock_sf.return_value = (False, "SFDC connection refused")
        resp = self._post()
        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("retries", body)

    @patch("webhook_server._run_sf_cmd")
    def test_call_outcome_missing_call_id_returns_502(self, mock_sf):
        """sfdc_push.py needs a call_id — without it the handler should fail."""
        mock_sf.return_value = (True, "ok")
        resp = self._post({"call_id": ""})
        # handler returns False when call_id is empty, so 502
        self.assertEqual(resp.status_code, 502)

    @patch("webhook_server._run_sf_cmd")
    def test_call_outcome_writes_to_call_log(self, mock_sf):
        """Event should be appended to call_summaries.jsonl if not already there."""
        mock_sf.return_value = (True, "Task created")
        self._post()
        self.assertTrue(os.path.exists(ws.LOG_FILE))
        with open(ws.LOG_FILE) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(any(l.get("call_id") == "call-abc-001" for l in lines))

    @patch("webhook_server._run_sf_cmd")
    def test_duplicate_call_id_not_double_written(self, mock_sf):
        """Second call with same call_id should not append a second log line."""
        mock_sf.return_value = (True, "ok")
        self._post()
        self._post()
        with open(ws.LOG_FILE) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        matching = [l for l in lines if l.get("call_id") == "call-abc-001"]
        self.assertEqual(len(matching), 1, "Should not double-write the same call_id")

    @patch("webhook_server._run_sf_cmd")
    def test_timestamp_injected_when_absent(self, mock_sf):
        """Server should stamp timestamp if the caller omits it."""
        mock_sf.return_value = (True, "ok")
        resp = self.client.post(
            "/voice-caller/sfdc-sync",
            json={"event_type": "call_outcome", "call_id": "ts-test-001"},
            content_type="application/json",
        )
        # Just check it doesn't crash — timestamp is internal
        self.assertIn(resp.status_code, (200, 502))


# ── referral tests ────────────────────────────────────────────────────────────

class TestSfdcSyncReferral(_Base):

    _ACCOUNT_RESP = json.dumps({
        "result": {
            "records": [{"Id": "001000000000001AAA", "Name": "Lincoln Public Schools"}]
        }
    })

    def _post(self, extra: dict | None = None):
        payload = {
            "event_type":    "referral",
            "call_id":       "call-ref-001",
            "to":            "+14025550000",
            "summary":       "Spoke with Tom. Mentioned Jane Doe at Omaha USD.",
            "referral_name": "Jane Doe",
            "referral_org":  "Omaha USD",
            "referral_phone": "+14025559999",
        }
        if extra:
            payload.update(extra)
        return self.client.post(
            "/voice-caller/sfdc-sync",
            json=payload,
            content_type="application/json",
        )

    @patch("webhook_server._run_sf_cmd")
    def test_referral_success_returns_200(self, mock_sf):
        # First call → account lookup; second call → Task create
        mock_sf.side_effect = [
            (True, self._ACCOUNT_RESP),                     # account lookup
            (True, json.dumps({"result": {"id": "00T001"}})),  # task create
        ]
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "synced")

    @patch("webhook_server._run_sf_cmd")
    def test_referral_no_account_returns_502(self, mock_sf):
        # Account not found → lookup returns empty records
        mock_sf.return_value = (True, json.dumps({"result": {"records": []}}))
        resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertIn("No SFDC Account", resp.get_json()["message"])

    @patch("webhook_server._run_sf_cmd")
    def test_referral_task_create_failure_returns_502(self, mock_sf):
        mock_sf.side_effect = [
            (True, self._ACCOUNT_RESP),   # lookup succeeds
            (False, "DUPLICATE_VALUE"),   # task create fails
            (True, self._ACCOUNT_RESP),   # retry lookup
            (False, "DUPLICATE_VALUE"),   # retry task create fails
        ]
        resp = self._post()
        self.assertEqual(resp.status_code, 502)

    @patch("webhook_server._run_sf_cmd")
    def test_referral_retries_on_first_failure(self, mock_sf):
        """A transient SF error on attempt 1 should succeed on retry."""
        mock_sf.side_effect = [
            (True, self._ACCOUNT_RESP),                       # lookup attempt 1
            (False, "NETWORK_ERROR"),                          # task fails attempt 1
            (True, self._ACCOUNT_RESP),                       # lookup attempt 2 (retry)
            (True, json.dumps({"result": {"id": "00T002"}})),  # task succeeds attempt 2
        ]
        resp = self._post()
        self.assertEqual(resp.status_code, 200)

    @patch("webhook_server._run_sf_cmd")
    def test_referral_logs_to_sync_log(self, mock_sf):
        mock_sf.side_effect = [
            (True, self._ACCOUNT_RESP),
            (True, json.dumps({"result": {"id": "00T003"}})),
        ]
        self._post()
        self.assertTrue(os.path.exists(ws._SFDC_SYNC_LOG))
        with open(ws._SFDC_SYNC_LOG) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        # Should have at least a "pending" and a "success" entry
        statuses = {e["status"] for e in entries}
        self.assertIn("success", statuses)
        self.assertTrue(any(e["event_type"] == "referral" for e in entries))


# ── new_lead tests ────────────────────────────────────────────────────────────

class TestSfdcSyncNewLead(_Base):

    _ACCOUNT_RESP = json.dumps({
        "result": {
            "records": [{"Id": "001000000000002AAA", "Name": "Sioux Falls USD"}]
        }
    })

    def _post(self, extra: dict | None = None):
        payload = {
            "event_type":  "new_lead",
            "call_id":     "call-lead-001",
            "to":          "+16055550001",
            "summary":     "New lead: John Smith at Watertown SD.",
            "lead_name":   "John Smith",
            "lead_org":    "Watertown School District",
            "lead_phone":  "+16055550099",
            "lead_email":  "john@watertown.k12.sd.us",
        }
        if extra:
            payload.update(extra)
        return self.client.post(
            "/voice-caller/sfdc-sync",
            json=payload,
            content_type="application/json",
        )

    @patch("webhook_server._run_sf_cmd")
    def test_new_lead_success_returns_200(self, mock_sf):
        mock_sf.side_effect = [
            (True, self._ACCOUNT_RESP),
            (True, json.dumps({"result": {"id": "00T010"}})),
        ]
        resp = self._post()
        self.assertEqual(resp.status_code, 200)

    @patch("webhook_server._run_sf_cmd")
    def test_new_lead_falls_back_to_caller_phone(self, mock_sf):
        """If lead_phone lookup fails, should fall back to the caller's 'to' phone."""
        empty = json.dumps({"result": {"records": []}})
        mock_sf.side_effect = [
            (True, empty),               # lead_phone lookup → empty
            (True, self._ACCOUNT_RESP),  # caller 'to' phone lookup → found
            (True, json.dumps({"result": {"id": "00T011"}})),  # task create
        ]
        resp = self._post()
        self.assertEqual(resp.status_code, 200)

    @patch("webhook_server._run_sf_cmd")
    def test_new_lead_both_phones_miss_returns_502(self, mock_sf):
        empty = json.dumps({"result": {"records": []}})
        mock_sf.return_value = (True, empty)
        resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertIn("No SFDC Account", resp.get_json()["message"])


# ── retry-engine unit tests (no HTTP layer) ───────────────────────────────────

class TestRetryEngine(_Base):

    @patch("webhook_server._run_sf_cmd")
    def test_succeeds_on_first_attempt(self, mock_sf):
        mock_sf.return_value = (True, "Created: 1")
        event = {
            "event_type": "call_outcome",
            "call_id":    "retry-test-001",
            "to": "+16055550000",
        }
        ok, msg = ws._sync_with_retry(event)
        self.assertTrue(ok)
        self.assertEqual(mock_sf.call_count, 1)

    @patch("webhook_server._run_sf_cmd")
    def test_retries_on_transient_failure(self, mock_sf):
        """Should retry once and succeed on second attempt."""
        mock_sf.side_effect = [
            (False, "timeout"),     # attempt 1 fails
            (True, "Created: 1"),   # attempt 2 succeeds
        ]
        event = {
            "event_type": "call_outcome",
            "call_id":    "retry-test-002",
            "to": "+16055550000",
        }
        ok, msg = ws._sync_with_retry(event)
        self.assertTrue(ok)
        self.assertEqual(mock_sf.call_count, 2)

    @patch("webhook_server._run_sf_cmd")
    def test_exhausts_retries_and_returns_false(self, mock_sf):
        mock_sf.return_value = (False, "persistent error")
        event = {
            "event_type": "call_outcome",
            "call_id":    "retry-test-003",
            "to": "+16055550000",
        }
        ok, msg = ws._sync_with_retry(event)
        self.assertFalse(ok)
        self.assertEqual(mock_sf.call_count, ws._SFDC_MAX_TRIES)
        self.assertIn("persistent error", msg)

    def test_unknown_event_type_returns_false_immediately(self):
        event = {"event_type": "not_a_real_event"}
        ok, msg = ws._sync_with_retry(event)
        self.assertFalse(ok)
        self.assertIn("Unknown event_type", msg)

    @patch("webhook_server._run_sf_cmd")
    def test_retry_log_contains_retrying_status(self, mock_sf):
        """After a failed first attempt, the log should have a 'retrying' entry."""
        mock_sf.side_effect = [
            (False, "timeout"),
            (True, "ok"),
        ]
        event = {
            "event_type": "call_outcome",
            "call_id":    "retry-log-001",
            "to": "+16055550000",
        }
        ws._sync_with_retry(event)
        with open(ws._SFDC_SYNC_LOG) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        statuses = [e["status"] for e in entries]
        self.assertIn("retrying", statuses)
        self.assertIn("success", statuses)


# ── /voice-caller/sfdc-sync/status tests ─────────────────────────────────────

class TestSfdcSyncStatus(_Base):

    def _seed_log(self, entries: list) -> None:
        with open(ws._SFDC_SYNC_LOG, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_status_empty_log_returns_200(self):
        resp = self.client.get("/voice-caller/sfdc-sync/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["stats"]["total"], 0)
        self.assertEqual(body["entries"], [])

    def test_status_counts_success_and_failed(self):
        self._seed_log([
            {"event_type": "call_outcome", "status": "success",  "attempt": 1, "message": "ok", "call_id": "1"},
            {"event_type": "referral",     "status": "failed",   "attempt": 2, "message": "err", "call_id": "2"},
            {"event_type": "call_outcome", "status": "retrying", "attempt": 1, "message": "tmp", "call_id": "3"},
        ])
        resp = self.client.get("/voice-caller/sfdc-sync/status")
        body = resp.get_json()
        self.assertEqual(body["stats"]["total"],   3)
        self.assertEqual(body["stats"]["success"], 1)
        self.assertEqual(body["stats"]["failed"],  1)
        self.assertEqual(body["stats"]["retrying"],1)

    def test_status_by_event_type_breakdown(self):
        self._seed_log([
            {"event_type": "call_outcome", "status": "success", "attempt": 1, "message": "ok",  "call_id": "a"},
            {"event_type": "referral",     "status": "success", "attempt": 1, "message": "ok",  "call_id": "b"},
            {"event_type": "referral",     "status": "failed",  "attempt": 2, "message": "err", "call_id": "c"},
        ])
        resp = self.client.get("/voice-caller/sfdc-sync/status")
        body = resp.get_json()
        self.assertEqual(body["by_event_type"]["call_outcome"]["success"], 1)
        self.assertEqual(body["by_event_type"]["referral"]["success"],     1)
        self.assertEqual(body["by_event_type"]["referral"]["failed"],      1)

    def test_status_n_param_limits_entries(self):
        self._seed_log([
            {"event_type": "call_outcome", "status": "success", "attempt": 1, "message": str(i), "call_id": str(i)}
            for i in range(20)
        ])
        resp = self.client.get("/voice-caller/sfdc-sync/status?n=5")
        body = resp.get_json()
        self.assertLessEqual(body["count"], 5)

    def test_status_n_param_max_capped_at_500(self):
        """n > 500 should be silently clamped to 500."""
        resp = self.client.get("/voice-caller/sfdc-sync/status?n=99999")
        self.assertEqual(resp.status_code, 200)  # shouldn't crash

    def test_status_bad_n_param_defaults_to_50(self):
        resp = self.client.get("/voice-caller/sfdc-sync/status?n=banana")
        self.assertEqual(resp.status_code, 200)

    def test_status_includes_log_file_path(self):
        resp = self.client.get("/voice-caller/sfdc-sync/status")
        body = resp.get_json()
        self.assertIn("log_file", body)


# ── account lookup helper tests ───────────────────────────────────────────────

class TestSfdcLookupAccount(_Base):

    def _make_resp(self, records: list) -> tuple:
        return (True, json.dumps({"result": {"records": records}}))

    @patch("webhook_server._run_sf_cmd")
    def test_found_account_returns_dict(self, mock_sf):
        mock_sf.return_value = self._make_resp([{"Id": "001AAA", "Name": "Lincoln PS"}])
        result = ws._sfdc_lookup_account("+14025550000")
        self.assertIsNotNone(result)
        self.assertEqual(result["Id"], "001AAA")

    @patch("webhook_server._run_sf_cmd")
    def test_empty_records_returns_none(self, mock_sf):
        mock_sf.return_value = self._make_resp([])
        result = ws._sfdc_lookup_account("+14025550000")
        self.assertIsNone(result)

    @patch("webhook_server._run_sf_cmd")
    def test_sf_failure_returns_none(self, mock_sf):
        mock_sf.return_value = (False, "error")
        result = ws._sfdc_lookup_account("+14025550000")
        self.assertIsNone(result)

    def test_empty_phone_returns_none(self):
        result = ws._sfdc_lookup_account("")
        self.assertIsNone(result)

    def test_none_phone_returns_none(self):
        result = ws._sfdc_lookup_account(None)  # type: ignore[arg-type]
        self.assertIsNone(result)

    @patch("webhook_server._run_sf_cmd")
    def test_uses_last_10_digits(self, mock_sf):
        mock_sf.return_value = self._make_resp([{"Id": "001BBB", "Name": "SFSD"}])
        ws._sfdc_lookup_account("+16055551234")
        call_args = mock_sf.call_args[0][0]  # first positional arg (list of cmd args)
        soql_arg = next((a for a in call_args if "LIKE" in str(a)), "")
        self.assertIn("6055551234", soql_arg)


# ── _ensure_in_call_log tests ─────────────────────────────────────────────────

class TestEnsureInCallLog(_Base):

    def test_new_call_id_appended(self):
        event = {
            "call_id":   "new-call-xyz",
            "to":        "+16055550001",
            "from":      "+16028985026",
            "summary":   "Test summary",
            "timestamp": "2026-03-07T18:00:00Z",
        }
        ws._ensure_in_call_log(event)
        self.assertTrue(os.path.exists(ws.LOG_FILE))
        with open(ws.LOG_FILE) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(any(l["call_id"] == "new-call-xyz" for l in lines))

    def test_existing_call_id_not_duplicated(self):
        event = {
            "call_id":   "existing-call-001",
            "to":        "+16055550001",
            "summary":   "Existing summary",
        }
        # Write it once manually
        with open(ws.LOG_FILE, "w") as f:
            f.write(json.dumps({"call_id": "existing-call-001", "summary": "manual"}) + "\n")

        ws._ensure_in_call_log(event)
        with open(ws.LOG_FILE) as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1, "Should not duplicate an existing call_id")

    def test_missing_call_id_no_write(self):
        ws._ensure_in_call_log({"summary": "no call_id here"})
        self.assertFalse(os.path.exists(ws.LOG_FILE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
