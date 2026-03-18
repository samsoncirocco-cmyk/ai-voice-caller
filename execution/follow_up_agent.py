# SFDC WRITE SAFETY: This script modifies Salesforce data.
# Run without --live for dry-run. REQUIRES human approval before --live.

"""
FollowUpAgent - Prefab agent for handling post-call follow-ups with SFDC integration.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE = "/home/samson/.openclaw/workspace"
TOKEN_FILE = Path(WORKSPACE) / ".sfdc-approved"
AUDIT_LOG_PATH = Path(WORKSPACE) / "memory" / "sfdc-write-audit.log"
SF_SAFE_PATH = Path(WORKSPACE) / "tools" / "sf-safe"
SLACK_DM_CHANNEL = "D0AG2FT2G6M"
APPROVAL_TIMEOUT_SECONDS = 3600
POLL_INTERVAL = 10

sys.path.insert(0, str(Path(WORKSPACE) / "execution"))
sys.path.insert(0, str(Path(WORKSPACE) / "tools"))

from signalwire_agents.core.agent_base import AgentBase
from signalwire_agents.core.function_result import SwaigFunctionResult
from slack_client import post_message


class FollowUpAgent(AgentBase):
    """
    Agent for handling follow-up actions after calls, with gated SFDC writes.
    """

    def __init__(
        self,
        name: str = "follow_up_agent",
        route: str = "/follow_up",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, route=route, use_pom=True, **kwargs)
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._configure_agent_settings()
        self._build_prompt()

    def _configure_agent_settings(self) -> None:
        self.set_params({
            "end_of_speech_timeout": 800,
            "speech_event_timeout": 1000,
        })

    def _build_prompt(self) -> None:
        self.prompt_add_section(
            "Objective",
            body="""You are a follow-up coordinator for sales calls. Your role is to:
1. Gather information about the call outcome
2. Record follow-up tasks and next steps
3. Update Salesforce with call results (requires explicit approval)

When the user confirms they want to update Salesforce, use the update_salesforce function.
The system will show a preview first and wait for Samson's approval before making any changes.""",
        )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _get_sobject_type(lead_id: str) -> str:
        if lead_id.startswith("00Q"):
            return "Lead"
        if lead_id.startswith("003"):
            return "Contact"
        return "Contact"

    @staticmethod
    def _shell_join(parts: List[str]) -> str:
        return shlex.join(parts)

    @staticmethod
    def _task_values(lead_id: str, task_description: str, next_follow_up_date: str) -> str:
        values = [
            f"WhoId={lead_id}",
            f"Subject={json.dumps(task_description)}",
            "Status='Not Started'",
        ]
        if next_follow_up_date:
            values.append(f"ActivityDate={next_follow_up_date}")
        return " ".join(values)

    @staticmethod
    def _status_values(status: str) -> str:
        return f"Status={json.dumps(status)}"

    def _build_commands(
        self,
        lead_id: str,
        status: str,
        task_description: str,
        next_follow_up_date: str,
    ) -> Tuple[str, List[List[str]], List[List[str]]]:
        sobject = self._get_sobject_type(lead_id)
        task_values = self._task_values(lead_id, task_description, next_follow_up_date)
        status_values = self._status_values(status)

        dry_run_cmds = [
            [
                str(SF_SAFE_PATH),
                "data",
                "create",
                "record",
                "--sobject",
                "Task",
                "--values",
                task_values,
            ],
            [
                str(SF_SAFE_PATH),
                "data",
                "update",
                "record",
                "--sobject",
                sobject,
                "--record-id",
                lead_id,
                "--values",
                status_values,
            ],
        ]
        live_cmds = [cmd + ["--live"] for cmd in dry_run_cmds]
        return sobject, dry_run_cmds, live_cmds

    def _build_slack_message(
        self,
        invocation_token: str,
        lead_id: str,
        status: str,
        task_description: str,
        next_follow_up_date: str,
        dry_run_output: str,
        dry_run_cmds: List[List[str]],
    ) -> str:
        command_lines = "\n".join(
            f"  {self._shell_join(cmd)}" for cmd in dry_run_cmds
        )
        approve_cmd = f"python3 tools/sfdc-approve.py --token {invocation_token}"
        return (
            "[SFDC DRY RUN — pending approval]\n\n"
            f"lead_id:           {lead_id}\n"
            f"status:            {status}\n"
            f"task_description:  {task_description}\n"
            f"next_follow_up:    {next_follow_up_date or '(not set)'}\n"
            f"invocation_token:  {invocation_token}\n\n"
            "Commands to run:\n"
            f"{command_lines}\n\n"
            "Dry-run output:\n"
            "```\n"
            f"{dry_run_output.strip() or '(no dry-run output)'}\n"
            "```\n\n"
            f"Approve: {approve_cmd}\n"
        )

    def _run_command(self, cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": self._shell_join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }

    def _run_dry_run_commands(self, commands: List[List[str]]) -> Tuple[bool, str, List[Dict[str, Any]]]:
        outputs: List[str] = []
        results: List[Dict[str, Any]] = []
        all_ok = True

        for cmd in commands:
            result = self._run_command(cmd)
            results.append(result)
            outputs.append(f"$ {result['command']}")
            if result["stdout"].strip():
                outputs.append(result["stdout"].strip())
            if result["stderr"].strip():
                outputs.append(result["stderr"].strip())
            if not result["success"]:
                all_ok = False

        return all_ok, "\n".join(outputs).strip(), results

    def _post_slack_dm(self, message: str) -> bool:
        try:
            post_message(SLACK_DM_CHANNEL, message)
            return True
        except Exception as exc:
            print("[WARN] Slack DM failed — approval still possible via sfdc-approve.py")
            print(f"[FollowUpAgent] Slack error: {exc}")
            return False

    def _read_approval_token(self) -> Tuple[bool, str]:
        if not TOKEN_FILE.exists():
            return False, "No approval token found"

        try:
            with open(TOKEN_FILE, encoding="utf-8") as handle:
                token = json.load(handle)
        except Exception as exc:
            return False, f"Token read error: {exc}"

        now = time.time()
        created_at = token.get("created_at", 0)
        ttl_seconds = token.get("ttl_seconds", APPROVAL_TIMEOUT_SECONDS)
        expires_at = token.get("expires_at", created_at + ttl_seconds)
        if now >= expires_at:
            return False, "Approval token expired"

        return True, token.get("reason", "approved")

    def _wait_for_approval(self) -> Tuple[bool, str]:
        for _ in range(APPROVAL_TIMEOUT_SECONDS // POLL_INTERVAL):
            valid, detail = self._read_approval_token()
            if valid:
                return True, detail
            time.sleep(POLL_INTERVAL)
        return False, "approval timeout"

    def _log_audit(self, entry: Dict[str, Any]) -> None:
        record = {"timestamp": self._utc_now(), **entry}
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def _save_to_firestore(self, payload: Dict[str, Any]) -> None:
        try:
            from account_db import save_follow_up_result  # type: ignore
        except Exception:
            return

        try:
            save_follow_up_result(payload)
        except Exception as exc:
            print(f"[FollowUpAgent] Firestore save failed (non-blocking): {exc}")

    def _execute_live_writes(self, commands: List[List[str]]) -> List[Dict[str, Any]]:
        return [self._run_command(cmd) for cmd in commands]

    @AgentBase.tool(
        name="update_salesforce",
        description="Update Salesforce with call outcome information. Creates a Task and updates Lead/Contact status. REQUIRES APPROVAL - will show preview first.",
        parameters={
            "lead_id": {
                "type": "string",
                "description": "Salesforce Lead or Contact ID (e.g., '00Q...' for Lead, '003...' for Contact)",
            },
            "status": {
                "type": "string",
                "description": "New status to set (e.g., 'Contacted', 'Qualified', 'Unqualified')",
            },
            "task_description": {
                "type": "string",
                "description": "Description of the task/follow-up to create",
            },
            "next_follow_up_date": {
                "type": "string",
                "description": "Next follow-up date in YYYY-MM-DD format (optional)",
                "optional": True,
            },
        },
        required=["lead_id", "status", "task_description"],
    )
    def update_salesforce(self, args: Dict[str, Any], raw_data: Dict[str, Any]) -> SwaigFunctionResult:
        del raw_data
        lead_id = args.get("lead_id", "")
        status = args.get("status", "")
        task_description = args.get("task_description", "")
        next_follow_up_date = args.get("next_follow_up_date", "")
        invocation_token = str(uuid.uuid4())

        sobject, dry_run_cmds, live_cmds = self._build_commands(
            lead_id, status, task_description, next_follow_up_date
        )

        dry_run_ok, dry_run_output, dry_run_results = self._run_dry_run_commands(dry_run_cmds)
        slack_message = self._build_slack_message(
            invocation_token,
            lead_id,
            status,
            task_description,
            next_follow_up_date,
            dry_run_output,
            dry_run_cmds,
        )
        self._post_slack_dm(slack_message)

        if not dry_run_ok:
            self._log_audit({
                "command": "update_salesforce",
                "lead_id": lead_id,
                "status": "skipped",
                "reason": "dry-run failed",
                "invocation_token": invocation_token,
                "dry_run_results": dry_run_results,
            })
            self._save_to_firestore({
                "lead_id": lead_id,
                "status": status,
                "task_description": task_description,
                "next_follow_up_date": next_follow_up_date,
                "sfdc_written": False,
                "sfdc_reason": "dry-run failed",
            })
            return SwaigFunctionResult(
                "Salesforce update not executed because the dry-run failed. "
                "Review the dry-run output in Slack before approving."
            )

        approved, approval_reason = self._wait_for_approval()
        if not approved:
            self._log_audit({
                "command": "update_salesforce",
                "lead_id": lead_id,
                "status": "skipped",
                "reason": approval_reason,
                "invocation_token": invocation_token,
            })
            self._save_to_firestore({
                "lead_id": lead_id,
                "status": status,
                "task_description": task_description,
                "next_follow_up_date": next_follow_up_date,
                "sfdc_written": False,
                "sfdc_reason": approval_reason,
            })
            return SwaigFunctionResult(
                f"Salesforce update not executed: {approval_reason}."
            )

        live_results = self._execute_live_writes(live_cmds)
        all_success = all(result["success"] for result in live_results)

        self._log_audit({
            "command": "update_salesforce",
            "lead_id": lead_id,
            "status": "completed" if all_success else "failed",
            "reason": approval_reason,
            "invocation_token": invocation_token,
            "results": live_results,
        })
        self._save_to_firestore({
            "lead_id": lead_id,
            "status": status,
            "task_description": task_description,
            "next_follow_up_date": next_follow_up_date,
            "sfdc_written": all_success,
            "sfdc_reason": approval_reason,
            "sfdc_results": live_results,
        })

        if all_success:
            return SwaigFunctionResult(
                f"Salesforce updated successfully for {sobject} {lead_id}."
            )

        failures = [result["stderr"] or result["stdout"] for result in live_results if not result["success"]]
        return SwaigFunctionResult(
            "Salesforce update partially failed: " + "; ".join(failure.strip() for failure in failures if failure.strip())
        )


def update_salesforce(
    lead_id: str,
    status: str,
    task_description: str,
    next_follow_up_date: str = "",
) -> Dict[str, Any]:
    agent = FollowUpAgent()
    result = agent.update_salesforce(
        {
            "lead_id": lead_id,
            "status": status,
            "task_description": task_description,
            "next_follow_up_date": next_follow_up_date,
        },
        {},
    )
    response = getattr(result, "response", str(result))
    return {
        "success": "not executed" not in response.lower() and "failed" not in response.lower(),
        "response": response,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--date", default="")
    cli_args = parser.parse_args()

    print(
        json.dumps(
            update_salesforce(
                cli_args.lead_id,
                cli_args.status,
                cli_args.task,
                cli_args.date,
            ),
            indent=2,
        )
    )
