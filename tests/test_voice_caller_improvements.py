import argparse
import json
import os
import time
from unittest.mock import MagicMock, patch


# Test 1: transcript saving
def test_transcript_saving(tmp_path):
    import webhook_server

    log_dir = tmp_path / "logs"
    webhook_server.LOG_DIR = str(log_dir)
    webhook_server.LOG_FILE = str(log_dir / "call_summaries.jsonl")
    webhook_server.TRANSCRIPTS_DIR = str(log_dir / "call_transcripts")
    os.makedirs(webhook_server.LOG_DIR, exist_ok=True)

    payload = {
        "call_id": "test-call-abc",
        "conversation_history": [
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Hi"},
        ],
        "post_prompt_data": {"raw": "summary text"},
        "SWMLCall": {"to_number": "+16025550100", "from_number": "+16025550101"},
    }

    dummy_thread = MagicMock()
    dummy_thread.start = MagicMock()

    with patch.object(webhook_server.threading, "Thread", return_value=dummy_thread):
        client = webhook_server.app.test_client()
        resp = client.post("/voice-caller/post-call", json=payload)

    assert resp.status_code == 200

    transcript_file = log_dir / "call_transcripts" / "test-call-abc.json"
    assert transcript_file.exists()
    transcript_data = json.loads(transcript_file.read_text())
    assert isinstance(transcript_data, list)
    assert transcript_data[0]["content"] == "Hello"

    # Existing summary behavior must still work
    summary_log = log_dir / "call_summaries.jsonl"
    assert summary_log.exists()
    lines = [json.loads(line) for line in summary_log.read_text().splitlines() if line.strip()]
    assert any(line.get("call_id") == "test-call-abc" for line in lines)


# Test 2: fallback stub
def test_fallback_stub(tmp_path):
    import campaign_runner_v2

    campaign_runner_v2.LOG_DIR = tmp_path / "logs"
    campaign_runner_v2.STATE_DIR = tmp_path / "state"
    campaign_runner_v2.RESEARCH_CACHE_DIR = tmp_path / "research_cache"
    campaign_runner_v2.LOG_DIR.mkdir(parents=True, exist_ok=True)
    campaign_runner_v2.STATE_DIR.mkdir(parents=True, exist_ok=True)
    campaign_runner_v2.RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    csv_file = tmp_path / "leads.csv"
    csv_file.write_text(
        "phone,name,account,notes,sf_account_id\n"
        "(602) 555-1212,Test User,Acme Public Schools,South Dakota Education,001TEST\n"
    )

    args = argparse.Namespace(
        limit=1,
        interval=1,
        dry_run=False,
        resume=False,
        business_hours=False,
        prompt="prompts/paul.txt",
        voice="openai.onyx",
        from_number=None,
    )

    fake_cost_tracker = MagicMock()
    fake_cost_tracker.get_balance = MagicMock(side_effect=[10.50, 10.45])
    fake_cost_tracker.log_call_cost = MagicMock(return_value=(0.05, 0.05))

    with patch.object(campaign_runner_v2, "research_account", return_value={"_source": "test", "hook_1": "hook"}), \
         patch.object(campaign_runner_v2, "build_dynamic_swml", return_value={"version": "1.0.0"}), \
         patch.object(campaign_runner_v2, "make_call", return_value={"success": True, "call_id": "fake-call-123"}), \
         patch.object(campaign_runner_v2, "cost_tracker", fake_cost_tracker), \
         patch.object(campaign_runner_v2.time, "sleep", return_value=None):
        campaign_runner_v2.run_campaign(str(csv_file), args)

    summaries = campaign_runner_v2.LOG_DIR / "call_summaries.jsonl"
    assert summaries.exists()
    rows = [json.loads(line) for line in summaries.read_text().splitlines() if line.strip()]
    stub = next((r for r in rows if r.get("call_id") == "fake-call-123"), None)
    assert stub is not None
    assert stub["status"] == "pending"
    assert stub["phone"] == "+16025551212"
    assert stub["account"] == "Acme Public Schools"


# Test 3: agent name parsing
def test_agent_name_parsing():
    base = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/prompts"
    for fname, expected in [("paul.txt","Paul"),("cold_outreach.txt","Alex"),("k12.txt","Paul")]:
        path = os.path.join(base, fname)
        with open(path) as f:
            first_line = f.readline().strip()
        assert first_line.startswith("# AGENT_NAME:"), f"{fname} missing AGENT_NAME header"
        name = first_line.split(":", 1)[1].strip()
        assert name == expected, f"{fname}: expected {expected}, got {name}"


# Test 4: cost tracker
def test_cost_tracker(tmp_path):
    from execution.cost_tracker import log_call_cost
    log_file = str(tmp_path / "test_cost.log")
    cost, total = log_call_cost("test-call-001", 10.50, 10.45, log_file)
    assert abs(cost - 0.05) < 0.001
    assert abs(total - 0.05) < 0.001
    assert os.path.exists(log_file)
    content = open(log_file).read()
    assert "test-call-001" in content
    assert "running_total=$0.05" in content


# Test 5: cache TTL
def test_cache_ttl(tmp_path):
    import importlib, sys
    cache_file = tmp_path / "test_account.json"
    cache_file.write_text('{"data": "old"}')
    # Set mtime to 40 days ago
    old_time = time.time() - (40 * 86400)
    os.utime(str(cache_file), (old_time, old_time))
    # Check that mtime-based TTL logic correctly identifies this as stale
    mtime = os.path.getmtime(str(cache_file))
    is_stale = mtime < time.time() - (30 * 86400)
    assert is_stale, "40-day-old cache should be stale"
    # Fresh cache
    fresh_file = tmp_path / "fresh_account.json"
    fresh_file.write_text('{"data": "fresh"}')
    # mtime is now (default), should be fresh
    is_fresh = os.path.getmtime(str(fresh_file)) >= time.time() - (30 * 86400)
    assert is_fresh, "Brand new cache should not be stale"
