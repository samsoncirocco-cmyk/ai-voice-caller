"""
tests/test_sfdc_id_pipeline_e2e.py

5-Step end-to-end validation of the SFDC ID pipeline:

  Step 1: Unit test suite (existing — run separately)
  Step 2: Webhook URL query param delivery
          — SignalWire does NOT echo global_data in post_prompt_url callbacks.
          — sfdc_id must arrive via URL query params embedded at call-creation time.
          — Verifies webhook_server.py reads query params first (FIX 2026-03-13).
  Step 3: Log persistence — logged call_summaries.jsonl contains sfdc_id from URL params.
  Step 4: make_call_v8.py build_swml() embeds sfdc_id in post_prompt_url.
  Step 5: sfdc_push.py dry-run — finds the logged sfdc_id and would write to SFDC.

Run from project root:
    python -m pytest tests/test_sfdc_id_pipeline_e2e.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── path setup ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Redirect log files to a tmp dir before importing webhook_server
_TMP = tempfile.mkdtemp()
os.environ.setdefault("SFDC_SYNC_TEST_LOGDIR", _TMP)

import webhook_server as ws  # noqa: E402

ws.LOG_DIR        = _TMP
ws.LOG_FILE       = os.path.join(_TMP, "call_summaries.jsonl")
ws._SFDC_SYNC_LOG = os.path.join(_TMP, "sfdc-live-sync.jsonl")
ws._SFDC_BASE_WAIT = 0
ws._SFDC_MAX_TRIES = 2

# Also import build_swml from make_call_v8 for Step 4
import importlib.util
_V8_PATH = ROOT / "make_call_v8.py"
_spec = importlib.util.spec_from_file_location("make_call_v8", _V8_PATH)
_v8 = importlib.util.module_from_spec(_spec)
# Stub env vars so module-level reads don't crash in test env
os.environ.setdefault("SIGNALWIRE_PROJECT_ID", "test-project-id")
os.environ.setdefault("SIGNALWIRE_AUTH_TOKEN",  "test-auth-token")
os.environ.setdefault("SIGNALWIRE_SPACE_URL",   "test.signalwire.com")
_spec.loader.exec_module(_v8)


# ── helpers ───────────────────────────────────────────────────────────────────

SYNTHETIC_SFDC_ID    = "001SYNTHETIC0000001"
SYNTHETIC_ACCOUNT    = "Lincoln%20Public%20Schools"  # URL-encoded
SYNTHETIC_CALL_ID    = "synth-call-pipeline-001"
SYNTHETIC_TO_NUMBER  = "+16055559999"
SYNTHETIC_FROM_NUM   = "+16028985026"

_MINIMAL_PAYLOAD = {
    "call_id":  SYNTHETIC_CALL_ID,
    "SWMLCall": {
        "to_number":   SYNTHETIC_TO_NUMBER,
        "from_number": SYNTHETIC_FROM_NUM,
    },
    "post_prompt_data": {
        "raw": "- Call outcome: Connected\n- Spoke with: Dr. Hansen, IT Director",
    },
}


class _Base(unittest.TestCase):
    def setUp(self):
        ws.app.testing = True
        self.client = ws.app.test_client()
        for p in [ws.LOG_FILE, ws._SFDC_SYNC_LOG]:
            if os.path.exists(p):
                os.remove(p)


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — URL query param delivery
# ──────────────────────────────────────────────────────────────────────────────

class Step2_WebhookURLParamDelivery(_Base):
    """
    SignalWire does NOT echo global_data in post_prompt_url callbacks.
    Verify webhook_server reads sfdc_id from URL query params (FIX 2026-03-13).
    """

    def _post_with_qp(self, extra_qp: dict | None = None, body: dict | None = None):
        qp = {"sfdc_id": SYNTHETIC_SFDC_ID, "account_name": "Lincoln Public Schools"}
        if extra_qp:
            qp.update(extra_qp)
        from urllib.parse import urlencode
        qs = urlencode(qp)
        payload = dict(_MINIMAL_PAYLOAD)
        if body:
            payload.update(body)
        return self.client.post(
            f"/voice-caller/post-call?{qs}",
            json=payload,
            content_type="application/json",
        )

    def test_2a_sfdc_id_from_url_param_returns_200(self):
        """Webhook accepts call with sfdc_id in URL params only (no global_data)."""
        resp = self._post_with_qp()
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_2b_sfdc_id_priority_url_over_global_data(self):
        """
        URL param sfdc_id must take precedence over global_data sfdc_id.
        (global_data values arrive stale/missing from SignalWire; URL params are reliable.)
        """
        resp = self._post_with_qp(
            body={**_MINIMAL_PAYLOAD, "global_data": {"sfdc_id": "WRONG_ID_FROM_GLOBAL_DATA"}}
        )
        self.assertEqual(resp.status_code, 200)
        # Verify log entry has the URL-param sfdc_id, not the global_data value
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        matching = [e for e in entries if e.get("call_id") == SYNTHETIC_CALL_ID]
        self.assertTrue(matching, "Log entry not found")
        self.assertEqual(matching[0]["sfdc_id"], SYNTHETIC_SFDC_ID,
                         "URL param sfdc_id should win over global_data")

    def test_2c_no_sfdc_id_still_logs_call(self):
        """Calls without sfdc_id (dialed direct, not from SFDC campaign) still log fine."""
        resp = self.client.post(
            "/voice-caller/post-call",
            json={**_MINIMAL_PAYLOAD, "call_id": "synth-no-sfdc-001"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        matching = [e for e in entries if e.get("call_id") == "synth-no-sfdc-001"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].get("sfdc_id", ""), "")

    def test_2d_global_data_fallback_when_no_url_param(self):
        """
        When URL param is absent, global_data fallback should populate sfdc_id.
        (Backward compat — older calls before campaign_runner fix.)
        """
        resp = self.client.post(
            "/voice-caller/post-call",
            json={
                **_MINIMAL_PAYLOAD,
                "call_id": "synth-global-fallback-001",
                "global_data": {"sfdc_id": "001GLOBAL0000001", "account_name": "Fallback School"},
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        matching = [e for e in entries if e.get("call_id") == "synth-global-fallback-001"]
        self.assertTrue(matching, "Fallback entry not found")
        self.assertEqual(matching[0].get("sfdc_id"), "001GLOBAL0000001",
                         "global_data fallback should populate sfdc_id when URL param absent")


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — Log persistence with sfdc_id
# ──────────────────────────────────────────────────────────────────────────────

class Step3_LogPersistence(_Base):
    """Verify logged call_summaries.jsonl entries contain sfdc_id and are durable."""

    def _post_synthetic(self):
        from urllib.parse import urlencode
        qs = urlencode({"sfdc_id": SYNTHETIC_SFDC_ID, "account_name": "Lincoln Public Schools"})
        return self.client.post(
            f"/voice-caller/post-call?{qs}",
            json=_MINIMAL_PAYLOAD,
            content_type="application/json",
        )

    def test_3a_log_file_created_on_first_call(self):
        self.assertFalse(os.path.exists(ws.LOG_FILE))
        self._post_synthetic()
        self.assertTrue(os.path.exists(ws.LOG_FILE))

    def test_3b_log_entry_has_sfdc_id(self):
        self._post_synthetic()
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(entries)
        entry = entries[-1]
        self.assertEqual(entry["sfdc_id"], SYNTHETIC_SFDC_ID)

    def test_3c_log_entry_has_account_name(self):
        self._post_synthetic()
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        entry = entries[-1]
        self.assertEqual(entry["account_name"], "Lincoln Public Schools")

    def test_3d_log_entry_has_call_id(self):
        self._post_synthetic()
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        entry = entries[-1]
        self.assertEqual(entry["call_id"], SYNTHETIC_CALL_ID)

    def test_3e_log_entry_has_summary(self):
        self._post_synthetic()
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        entry = entries[-1]
        self.assertIn("Connected", entry.get("summary", "") or "")

    def test_3f_log_entry_is_valid_jsonl(self):
        """Every line in call_summaries.jsonl must parse as valid JSON."""
        self._post_synthetic()
        self._post_synthetic()  # second call (same call_id — idempotent? or second entry)
        with open(ws.LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    parsed = json.loads(line)
                    self.assertIn("call_id", parsed)

    def test_3g_log_has_timestamp(self):
        self._post_synthetic()
        with open(ws.LOG_FILE) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        entry = entries[-1]
        self.assertIn("timestamp", entry)
        self.assertIn("T", entry["timestamp"])  # ISO 8601 format


# ──────────────────────────────────────────────────────────────────────────────
# STEP 4 — make_call_v8.build_swml() embeds sfdc_id in post_prompt_url
# ──────────────────────────────────────────────────────────────────────────────

class Step4_BuildSwmlURLEmbedding(unittest.TestCase):
    """
    Verify make_call_v8.build_swml() embeds sfdc_id as a URL query param.
    This ensures every outbound call carries sfdc_id even if SignalWire drops global_data.
    """

    def _get_post_prompt_url(self, **kwargs) -> str:
        swml = _v8.build_swml("test prompt", "en-US-Neural2-J", **kwargs)
        ai_block = swml["sections"]["main"][1]["ai"]
        return ai_block["post_prompt_url"]

    def test_4a_no_sfdc_id_uses_bare_url(self):
        url = self._get_post_prompt_url()
        self.assertNotIn("sfdc_id", url)
        self.assertNotIn("?", url)

    def test_4b_sfdc_id_appended_as_query_param(self):
        url = self._get_post_prompt_url(sfdc_id="001TEST0000001", account_name="Test School")
        self.assertIn("sfdc_id=001TEST0000001", url)
        self.assertIn("?", url)

    def test_4c_account_name_url_encoded(self):
        url = self._get_post_prompt_url(sfdc_id="001TEST0000002", account_name="School District #5")
        self.assertIn("account_name=", url)
        # URL-encoded (space → + or %20, # → %23)
        self.assertNotIn(" ", url)
        self.assertNotIn("#", url)

    def test_4d_empty_sfdc_id_uses_bare_url(self):
        url = self._get_post_prompt_url(sfdc_id="", account_name="")
        self.assertNotIn("?", url)

    def test_4e_sfdc_id_only_no_account_name(self):
        url = self._get_post_prompt_url(sfdc_id="001ONLYONE0001")
        self.assertIn("sfdc_id=001ONLYONE0001", url)

    def test_4f_base_url_is_hooks_6eyes_dev(self):
        url = self._get_post_prompt_url(sfdc_id="001BASE0000001")
        self.assertTrue(url.startswith("https://hooks.6eyes.dev/voice-caller/post-call"),
                        f"Unexpected base URL: {url}")


# ──────────────────────────────────────────────────────────────────────────────
# STEP 5 — sfdc_push.py dry-run via call log
# ──────────────────────────────────────────────────────────────────────────────

class Step5_SfdcPushDryRun(unittest.TestCase):
    """
    Simulate a synthetic call log entry with sfdc_id, then verify sfdc_push.py
    can parse it and would attempt a Salesforce write (mocked — no real SFDC call).
    """

    def _seed_call_log(self, log_path: str, sfdc_id: str = SYNTHETIC_SFDC_ID):
        """Write a synthetic call log entry as if it came from a real call."""
        entry = {
            "timestamp":    "2026-03-13T22:00:00+00:00",
            "call_id":      "synth-sfdc-push-001",
            "to":           "+16055550001",
            "from":         "+16028985026",
            "sfdc_id":      sfdc_id,
            "account_name": "Lincoln Public Schools",
            "summary":      "- Spoke with: Dr. Hansen, IT Director\n- Interest level: 4/5\n- Outcome: Connected",
            "raw":          {},
        }
        with open(log_path, "w") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def test_5a_sfdc_push_script_exists(self):
        self.assertTrue((ROOT / "sfdc_push.py").exists(),
                        "sfdc_push.py is missing from project root")

    def test_5b_sfdc_push_parses_jsonl_with_sfdc_id(self):
        """
        sfdc_push.py should read the JSONL log and extract sfdc_id.
        We test this by importing sfdc_push internals directly.
        """
        import sfdc_push as sp
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tf:
            tmp_log = tf.name
            self._seed_call_log(tmp_log)

        try:
            items = sp._load_jsonl(tmp_log)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["sfdc_id"], SYNTHETIC_SFDC_ID)
            self.assertEqual(items[0]["call_id"], "synth-sfdc-push-001")
        finally:
            os.unlink(tmp_log)

    @patch("sfdc_push._run_sf")
    def test_5c_sfdc_push_uses_sfdc_id_as_account_id(self, mock_run_sf):
        """
        When a log entry has sfdc_id, sfdc_push.py should use it directly
        as the WhatId for the Salesforce Task — not fall back to phone lookup.
        Tests the internal _create_task path when sfdc_id is present.
        """
        import sfdc_push as sp

        # Seed a log entry with sfdc_id
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tf:
            tmp_log = tf.name
            self._seed_call_log(tmp_log)

        # Mock a successful SF task create
        mock_run_sf.return_value = (True, json.dumps({"result": {"id": "00T999SYNTHETIC"}}))

        original_path  = sp.SUMMARIES_PATH
        original_state = sp.STATE_PATH
        tmp_state = tmp_log.replace(".jsonl", "-state.json")
        sp.SUMMARIES_PATH = tmp_log
        sp.STATE_PATH     = tmp_state

        try:
            with patch("sys.argv", ["sfdc_push.py", "--all"]):
                try:
                    sp.main()
                except SystemExit:
                    pass

            # sfdc_push should have attempted at least one SF call
            self.assertTrue(mock_run_sf.called,
                            "sfdc_push.py never called the SF CLI — check main() logic")

            # The sf CLI call args should reference the synthetic sfdc_id
            all_calls_str = str(mock_run_sf.call_args_list)
            self.assertIn(SYNTHETIC_SFDC_ID, all_calls_str,
                          f"sfdc_id {SYNTHETIC_SFDC_ID} not found in SF CLI args:\n{all_calls_str}")
        finally:
            sp.SUMMARIES_PATH = original_path
            sp.STATE_PATH     = original_state
            os.unlink(tmp_log)
            if os.path.exists(tmp_state):
                os.unlink(tmp_state)

    @patch("sfdc_push._run_sf")
    def test_5d_sfdc_push_skips_entries_without_sfdc_id(self, mock_run_sf):
        """
        Entries without sfdc_id should fall back to phone-based account lookup,
        not crash. (Regression guard.)
        """
        import sfdc_push as sp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tf:
            tmp_log = tf.name
            entry = {
                "timestamp":    "2026-03-13T22:05:00+00:00",
                "call_id":      "synth-no-sfdc-push-001",
                "to":           "+16055550099",
                "from":         "+16028985026",
                "sfdc_id":      "",
                "account_name": "Unknown District",
                "summary":      "- No answer",
                "raw":          {},
            }
            tf.write(json.dumps(entry) + "\n")

        # Mock SF to say no account found (empty records)
        mock_run_sf.return_value = (True, json.dumps({"result": {"records": []}}))

        original_path  = sp.SUMMARIES_PATH
        original_state = sp.STATE_PATH
        tmp_state = tmp_log.replace(".jsonl", "-state.json")
        sp.SUMMARIES_PATH = tmp_log
        sp.STATE_PATH     = tmp_state

        try:
            with patch("sys.argv", ["sfdc_push.py", "--all"]):
                try:
                    sp.main()
                except SystemExit:
                    pass
        except Exception as exc:
            self.fail(f"sfdc_push raised unexpectedly for no-sfdc_id entry: {exc}")
        finally:
            sp.SUMMARIES_PATH = original_path
            sp.STATE_PATH     = original_state
            os.unlink(tmp_log)
            if os.path.exists(tmp_state):
                os.unlink(tmp_state)

    def test_5e_sfdc_push_dry_run_flag_does_not_call_sf(self):
        """
        With --dry-run flag, sfdc_push.py must NOT call the SF CLI.
        Safety gate — SFDC write safety rule (added Mar 9 2026).
        """
        import sfdc_push as sp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tf:
            tmp_log = tf.name
            self._seed_call_log(tmp_log)

        original_path  = sp.SUMMARIES_PATH
        original_state = sp.STATE_PATH
        tmp_state = tmp_log.replace(".jsonl", "-state.json")
        sp.SUMMARIES_PATH = tmp_log
        sp.STATE_PATH     = tmp_state

        try:
            with patch("sfdc_push._run_sf") as mock_sf:
                with patch("sys.argv", ["sfdc_push.py", "--all", "--dry-run"]):
                    try:
                        sp.main()
                    except SystemExit:
                        pass
                self.assertFalse(mock_sf.called,
                                 "SF CLI was called during --dry-run — this is a bug!")
        finally:
            sp.SUMMARIES_PATH = original_path
            sp.STATE_PATH     = original_state
            os.unlink(tmp_log)
            if os.path.exists(tmp_state):
                os.unlink(tmp_state)


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
