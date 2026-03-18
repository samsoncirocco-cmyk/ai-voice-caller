import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path


ROOT = Path("/home/samson/.openclaw/workspace/projects/ai-voice-caller")
MODULE_PATH = ROOT / "execution" / "follow_up_agent.py"
SF_SAFE_PATH = Path("/home/samson/.openclaw/workspace/tools/sf-safe")


def load_follow_up_agent_module():
    signalwire_agents = types.ModuleType("signalwire_agents")
    core = types.ModuleType("signalwire_agents.core")
    agent_base = types.ModuleType("signalwire_agents.core.agent_base")
    function_result = types.ModuleType("signalwire_agents.core.function_result")

    class FakeAgentBase:
        def __init__(self, *args, **kwargs):
            pass

        def set_params(self, params):
            self.params = params

        def prompt_add_section(self, *args, **kwargs):
            return None

        @staticmethod
        def tool(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class FakeSwaigFunctionResult:
        def __init__(self, response):
            self.response = response

    slack_client = types.ModuleType("slack_client")
    slack_client.post_message = lambda channel, text: {"channel": channel, "text": text}

    sys.modules["signalwire_agents"] = signalwire_agents
    sys.modules["signalwire_agents.core"] = core
    sys.modules["signalwire_agents.core.agent_base"] = agent_base
    sys.modules["signalwire_agents.core.function_result"] = function_result
    sys.modules["slack_client"] = slack_client

    agent_base.AgentBase = FakeAgentBase
    function_result.SwaigFunctionResult = FakeSwaigFunctionResult

    spec = importlib.util.spec_from_file_location("follow_up_agent_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_commands_uses_whoid_and_contact_sobject():
    module = load_follow_up_agent_module()
    agent = module.FollowUpAgent()

    sobject, dry_run_cmds, live_cmds = agent._build_commands(
        "003ABC123456789",
        "Working",
        "Call back next week",
        "2026-03-20",
    )

    assert sobject == "Contact"
    assert "WhoId=003ABC123456789" in dry_run_cmds[0][-1]
    assert "WhatId" not in dry_run_cmds[0][-1]
    assert dry_run_cmds[1][5] == "Contact"
    assert live_cmds[0][-1] == "--live"
    assert live_cmds[1][-1] == "--live"


def test_update_salesforce_logs_skip_on_approval_timeout(tmp_path, monkeypatch):
    module = load_follow_up_agent_module()
    monkeypatch.setattr(module, "AUDIT_LOG_PATH", tmp_path / "sfdc-write-audit.log")

    agent = module.FollowUpAgent()
    monkeypatch.setattr(agent, "_run_dry_run_commands", lambda commands: (True, "preview", []))
    monkeypatch.setattr(agent, "_post_slack_dm", lambda message: False)
    monkeypatch.setattr(agent, "_wait_for_approval", lambda: (False, "approval timeout"))
    monkeypatch.setattr(agent, "_save_to_firestore", lambda payload: None)

    result = agent.update_salesforce(
        {
            "lead_id": "00QABC123456789",
            "status": "Qualified",
            "task_description": "Send deck",
            "next_follow_up_date": "2026-03-21",
        },
        {},
    )

    lines = (tmp_path / "sfdc-write-audit.log").read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["status"] == "skipped"
    assert entry["reason"] == "approval timeout"
    assert "not executed" in result.response.lower()


def test_update_salesforce_executes_live_commands_after_approval(monkeypatch):
    module = load_follow_up_agent_module()
    agent = module.FollowUpAgent()
    captured = {}

    monkeypatch.setattr(agent, "_run_dry_run_commands", lambda commands: (True, "preview", []))
    monkeypatch.setattr(agent, "_post_slack_dm", lambda message: True)
    monkeypatch.setattr(agent, "_wait_for_approval", lambda: (True, "Approved invocation"))
    monkeypatch.setattr(agent, "_save_to_firestore", lambda payload: None)
    monkeypatch.setattr(agent, "_log_audit", lambda payload: None)

    def fake_execute(commands):
        captured["commands"] = commands
        return [{"success": True, "stdout": "ok", "stderr": "", "command": cmd[-1]} for cmd in commands]

    monkeypatch.setattr(agent, "_execute_live_writes", fake_execute)

    result = agent.update_salesforce(
        {
            "lead_id": "00QABC123456789",
            "status": "Qualified",
            "task_description": "Send deck",
            "next_follow_up_date": "2026-03-21",
        },
        {},
    )

    assert all(cmd[-1] == "--live" for cmd in captured["commands"])
    assert "successfully" in result.response.lower()


def test_sf_safe_write_without_live_is_dry_run():
    result = subprocess.run(
        [
            str(SF_SAFE_PATH),
            "data",
            "create",
            "record",
            "--sobject",
            "Task",
            "--values",
            "WhoId=003ABC Subject=\"Follow up\"",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
