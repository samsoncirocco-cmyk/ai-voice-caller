"""
FollowUpAgent - Prefab agent for handling post-call follow-ups with SFDC integration

Safety header (per sfdc-write-safety.md):
This agent invokes sf-safe for ALL Salesforce write operations.
sf-safe requires a valid .sfdc-approved token before any write will execute.
Default mode is DRY_RUN=True; --live flag required for actual writes.
"""

import os
import sys
import json
import uuid
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

# WORKSPACE: Absolute path to agent workspace root
WORKSPACE = "/home/samson/.openclaw/workspace"

# Add workspace to path for tools
sys.path.insert(0, os.path.join(WORKSPACE, "tools"))

from signalwire_agents.core.agent_base import AgentBase
from signalwire_agents.core.function_result import SwaigFunctionResult

# Token and paths
TOKEN_FILE = os.path.join(WORKSPACE, ".sfdc-approved")
SF_SAFE_PATH = os.path.join(WORKSPACE, "tools", "sf-safe")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "os.environ.get("SLACK_BOT_TOKEN", "")")
AUDIT_LOG_PATH = os.path.join(WORKSPACE, "memory", "sfdc-write-audit.log")

APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour
POLL_INTERVAL = 10  # seconds


class FollowUpAgent(AgentBase):
    """
    Agent for handling follow-up actions after calls, with gated SFDC writes.
    
    Key features:
    - update_salesforce() SWAIG function with dry-run -> approval -> live-write flow
    - Uses sf-safe for ALL SFDC operations - never calls sf directly
    - Posts approval requests to Slack DM D0AG2FT2G6M
    - Logs all activity (approved and skipped) to sfdc-write-audit.log
    """
    
    def __init__(
        self,
        name: str = "follow_up_agent",
        route: str = "/follow_up",
        **kwargs
    ):
        super().__init__(
            name=name,
            route=route,
            use_pom=True,
            **kwargs
        )
        self._ensure_audit_log()
        self._configure_agent_settings()
        self._build_prompt()
    
    def _ensure_audit_log(self):
        """Ensure sfdc-write-audit.log exists"""
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        if not os.path.exists(AUDIT_LOG_PATH):
            open(AUDIT_LOG_PATH, 'a').close()
    
    def _log_audit(self, entry: Dict[str, Any]):
        """Append entry to audit log"""
        entry["timestamp"] = datetime.utcnow().isoformat() + "Z"
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def _configure_agent_settings(self):
        """Configure agent behavior parameters"""
        self.set_params({
            "end_of_speech_timeout": 800,
            "speech_event_timeout": 1000
        })
    
    def _build_prompt(self):
        """Build agent prompt"""
        self.prompt_add_section(
            "Objective",
            body="""You are a follow-up coordinator for sales calls. Your role is to:
1. Gather information about the call outcome
2. Record follow-up tasks and next steps
3. Update Salesforce with call results (requires explicit approval)

When the user confirms they want to update Salesforce, use the update_salesforce function.
The system will show a preview first and wait for Samson's approval before making any changes."""
        )
    
    def _get_sobject_type(self, lead_id: str) -> str:
        """Determine Salesforce object type from ID prefix"""
        if lead_id.startswith("00Q"):
            return "Lead"
        elif lead_id.startswith("003"):
            return "Contact"
        else:
            # Default to Lead for unknown prefixes
            return "Lead"
    
    @AgentBase.tool(
        name="update_salesforce",
        description="Update Salesforce with call outcome information. Creates a Task and updates Lead/Contact status. REQUIRES APPROVAL - will show preview first.",
        parameters={
            "lead_id": {
                "type": "string",
                "description": "Salesforce Lead or Contact ID (e.g., '00Q...' for Lead, '003...' for Contact)"
            },
            "status": {
                "type": "string",
                "description": "New status to set (e.g., 'Contacted', 'Qualified', 'Unqualified')"
            },
            "task_description": {
                "type": "string",
                "description": "Description of the task/follow-up to create"
            },
            "next_follow_up_date": {
                "type": "string",
                "description": "Next follow-up date in YYYY-MM-DD format (optional)",
                "optional": True
            }
        },
        required=["lead_id", "status", "task_description"]
    )
    def update_salesforce(self, args: Dict[str, Any], raw_data: Dict[str, Any]) -> SwaigFunctionResult:
        """
        Update Salesforce with call outcome - gated by Slack approval.
        
        Flow:
        1. Format dry-run summary
        2. Post dry-run to Slack DM (approval request)
        3. Poll for sfdc-approve.py token (max 60 min)
        4. If approved: execute sf-safe --live commands
        5. If rejected/timeout: log skip to audit log
        6. Save to Firestore (regardless of SFDC outcome)
        """
        lead_id = args.get("lead_id", "")
        status = args.get("status", "")
        task_description = args.get("task_description", "")
        next_follow_up_date = args.get("next_follow_up_date", "")
        
        invocation_token = str(uuid.uuid4())
        
        # Step 1: Get sobject type from lead_id prefix
        sobject = self._get_sobject_type(lead_id)
        
        # Step 2: Build dry-run summary and sf-safe command preview
        dry_run_summary = self._build_dry_run_summary(
            lead_id, sobject, status, task_description, next_follow_up_date, invocation_token
        )
        
        # Step 3: Post to Slack for approval (don't abort on failure)
        slack_ok = self._post_slack_approval_request(dry_run_summary)
        if not slack_ok:
            print("[WARN] Slack DM failed - approval still possible via sfdc-approve.py")
        
        # Step 4: Poll for approval token
        approved = self._poll_for_approval()
        
        if not approved:
            # Log skipped write
            self._log_audit({
                "command": "update_salesforce",
                "lead_id": lead_id,
                "status": "skipped",
                "reason": "approval timeout",
                "invocation_token": invocation_token
            })
            
            # Save to Firestore regardless
            self._save_to_firestore(lead_id, status, task_description, next_follow_up_date, 
                                    sfdc_written=False, reason="approval timeout")
            
            return SwaigFunctionResult(
                f"Salesforce update NOT executed (approval timeout). Logged skip to sfdc-write-audit.log. "
                f"To approve: python3 tools/sfdc-approve.py --reason 'Approved follow-up'"
            )
        
        # Step 5: Execute live writes via sf-safe
        try:
            results = self._execute_sfdc_writes(
                lead_id, sobject, status, task_description, next_follow_up_date
            )
            
            success_count = sum(1 for r in results if r["success"])
            all_success = success_count == len(results)
            
            # Log outcome
            self._log_audit({
                "command": "update_salesforce",
                "lead_id": lead_id,
                "status": "completed" if all_success else "partial",
                "invocation_token": invocation_token,
                "operations": [r["description"] for r in results]
            })
            
            # Save to Firestore regardless of SFDC outcome
            self._save_to_firestore(lead_id, status, task_description, next_follow_up_date,
                                    sfdc_written=all_success, results=results)
            
            if all_success:
                return SwaigFunctionResult(
                    f"Salesforce updated successfully! Created Task and updated {sobject} Status to '{status}'."
                )
            else:
                errors = [r["error"] for r in results if not r["success"]]
                return SwaigFunctionResult(
                    f"Partial success: {success_count}/{len(results)} operations succeeded. "
                    f"Errors: {'; '.join(errors)}"
                )
                
        except Exception as e:
            # Log failure
            self._log_audit({
                "command": "update_salesforce",
                "lead_id": lead_id,
                "status": "failed",
                "reason": str(e),
                "invocation_token": invocation_token
            })
            
            # Save to Firestore even on exception
            self._save_to_firestore(lead_id, status, task_description, next_follow_up_date,
                                    sfdc_written=False, reason=str(e))
            
            return SwaigFunctionResult(
                f"Salesforce update failed: {str(e)}"
            )
    
    def _build_dry_run_summary(self, lead_id: str, sobject: str, status: str,
                               task_description: str, next_follow_up_date: str,
                               invocation_token: str) -> str:
        """Build dry-run summary showing what commands will run"""
        # Escape single quotes in task description for shell safety
        safe_task = task_description.replace("'", "'\"'\"'")
        
        task_cmd = f"sf-safe data create record --sobject Task --values \"WhoId={lead_id} Subject='{safe_task[:100]}' Status='Not Started'\""
        if next_follow_up_date:
            task_cmd += f" ActivityDate={next_follow_up_date}"
        task_cmd += " --live"
        
        status_cmd = f"sf-safe data update record --sobject {sobject} --record-id {lead_id} --values \"Status='{status}'\" --live"
        
        return f"""[SFDC DRY RUN — pending approval]

lead_id: {lead_id}
status: {status}
task_description: {task_description[:100]}{'...' if len(task_description) > 100 else ''}
next_follow_up: {next_follow_up_date or '(not set)'}

Commands to run:
  {task_cmd}
  {status_cmd}

Approve: python3 tools/sfdc-approve.py --token {invocation_token}
Timeout: 60 minutes"""
    
    def _post_slack_approval_request(self, message: str) -> bool:
        """Post approval request to Slack DM D0AG2FT2G6M using slack_client.py"""
        try:
            # Import slack_client from tools
            from slack_client import post_message
            
            result = post_message(
                channel="D0AG2FT2G6M",
                text=message,
                token=SLACK_BOT_TOKEN
            )
            
            if result.get("ok"):
                print("[FollowUpAgent] Slack approval request sent to D0AG2FT2G6M")
                return True
            else:
                print(f"[FollowUpAgent] Slack API error: {result.get('error')}")
                return False
                
        except ImportError:
            # Fallback to direct requests if slack_client not available
            try:
                import requests
                url = "https://slack.com/api/chat.postMessage"
                headers = {
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "channel": "D0AG2FT2G6M",
                    "text": message,
                    "unfurl_links": False
                }
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                result = response.json()
                
                if result.get("ok"):
                    print("[FollowUpAgent] Slack approval request sent (via requests)")
                    return True
                else:
                    print(f"[FollowUpAgent] Slack API error: {result.get('error')}")
                    return False
                    
            except Exception as e:
                print(f"[FollowUpAgent] Failed to post to Slack: {e}")
                return False
        except Exception as e:
            print(f"[FollowUpAgent] Failed to post to Slack: {e}")
            return False
    
    def _poll_for_approval(self) -> bool:
        """
        Poll for sfdc-approve.py token file.
        Returns True if valid token found, False on timeout.
        """
        max_iterations = APPROVAL_TIMEOUT_SECONDS // POLL_INTERVAL  # 360 iterations for 1 hour
        
        for _ in range(max_iterations):
            if os.path.exists(TOKEN_FILE):
                try:
                    with open(TOKEN_FILE) as f:
                        token = json.load(f)
                    
                    created_at = token.get("created_at", 0)
                    ttl = token.get("ttl_seconds", 3600)
                    age = time.time() - created_at
                    
                    if age <= ttl:
                        print(f"[FollowUpAgent] Approval token found: {token.get('reason', 'unspecified')}")
                        return True
                    else:
                        print(f"[FollowUpAgent] Token expired (age: {age}s)")
                        
                except Exception as e:
                    print(f"[FollowUpAgent] Error reading token: {e}")
            
            time.sleep(POLL_INTERVAL)
        
        return False
    
    def _execute_sfdc_writes(self, lead_id: str, sobject: str, status: str,
                             task_description: str, next_follow_up_date: str) -> List[Dict[str, Any]]:
        """
        Execute Salesforce writes via sf-safe --live.
        
        Task: WhoId = lead_id (Lead or Contact), no WhatId
        Status update: on sobject (Lead or Contact based on prefix)
        """
        results = []
        
        # Escape single quotes for shell
        safe_task = task_description.replace("'", "'\"'\"'")
        
        # 1. Create Task with WhoId (lead_id), no WhatId
        # Task fields: WhoId, Subject, ActivityDate, Status
        task_values = f"WhoId={lead_id} Subject='{safe_task[:250]}' Status='Not Started'"
        if next_follow_up_date:
            task_values += f" ActivityDate={next_follow_up_date}"
        
        task_cmd = [
            str(SF_SAFE_PATH),
            "data", "create", "record",
            "--sobject", "Task",
            "--values", task_values,
            "--live"
        ]
        
        results.append(self._run_sf_safe(task_cmd, "Create Task"))
        
        # 2. Update Lead or Contact Status
        status_values = f"Status='{status}'"
        
        status_cmd = [
            str(SF_SAFE_PATH),
            "data", "update", "record",
            "--sobject", sobject,
            "--record-id", lead_id,
            "--values", status_values,
            "--live"
        ]
        
        results.append(self._run_sf_safe(status_cmd, f"Update {sobject} Status"))
        
        return results
    
    def _run_sf_safe(self, cmd: List[str], description: str) -> Dict[str, Any]:
        """Run sf-safe command and return result dict"""
        try:
            print(f"[FollowUpAgent] Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "description": description,
                    "error": None,
                    "output": result.stdout
                }
            else:
                return {
                    "success": False,
                    "description": description,
                    "error": result.stderr or result.stdout
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "description": description,
                "error": f"{description} timed out after 60s"
            }
        except Exception as e:
            return {
                "success": False,
                "description": description,
                "error": f"{description} failed: {str(e)}"
            }
    
    def _save_to_firestore(self, lead_id: str, status: str, task_description: str,
                           next_follow_up_date: str, sfdc_written: bool, 
                           reason: str = None, results: List[Dict] = None):
        """
        Save follow-up result to Firestore.
        Called regardless of SFDC write outcome.
        """
        try:
            # Import Firestore utilities
            sys.path.insert(0, os.path.join(WORKSPACE, "projects", "ai-voice-caller", "execution"))
            from account_db import save_follow_up_result
            
            follow_up_data = {
                "lead_id": lead_id,
                "status": status,
                "task_description": task_description,
                "next_follow_up_date": next_follow_up_date,
                "sfdc_written": sfdc_written,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            
            if reason:
                follow_up_data["reason"] = reason
            if results:
                follow_up_data["sfdc_results"] = results
            
            save_follow_up_result(follow_up_data)
            print(f"[FollowUpAgent] Saved to Firestore (sfdc_written={sfdc_written})")
            
        except Exception as e:
            print(f"[FollowUpAgent] Firestore save failed (non-blocking): {e}")


# Convenience function for non-agent usage
def update_salesforce(lead_id: str, status: str, task_description: str,
                     next_follow_up_date: str = "") -> Dict[str, Any]:
    """
    Standalone function to update Salesforce (for use outside SWAIG context).
    Always uses gated approval flow.
    """
    agent = FollowUpAgent()
    
    args = {
        "lead_id": lead_id,
        "status": status,
        "task_description": task_description,
        "next_follow_up_date": next_follow_up_date
    }
    
    result = agent.update_salesforce(args, {})
    return {
        "success": "NOT executed" not in result.response and "failed" not in result.response.lower(),
        "response": result.response
    }


if __name__ == "__main__":
    # CLI test mode
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--date", default="")
    args = parser.parse_args()
    
    result = update_salesforce(
        args.lead_id, args.status, args.task, args.date
    )
    print(json.dumps(result, indent=2))
