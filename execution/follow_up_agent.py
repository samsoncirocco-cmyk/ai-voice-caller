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
from typing import Dict, Any, Optional

# Add workspace to path for tools
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "tools"))

from signalwire_agents.core.agent_base import AgentBase
from signalwire_agents.core.function_result import SwaigFunctionResult

WORKSPACE = Path(__file__).resolve().parents[2]
TOKEN_FILE = WORKSPACE / ".sfdc-approved"
SF_SAFE_PATH = WORKSPACE / "tools" / "sf-safe"
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour
POLL_INTERVAL = 10  # seconds


class FollowUpAgent(AgentBase):
    """
    Agent for handling follow-up actions after calls, with gated SFDC writes.
    
    Key features:
    - update_salesforce() SWAIG function with dry-run -> approval -> live-write flow
    - Uses sf-safe for all SFDC operations (requires explicit approval)
    - Posts approval requests to Slack DM
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
        
        self._configure_agent_settings()
        self._build_prompt()
        self._register_tools()
    
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
    
    def _register_tools(self):
        """Register SWAIG tools"""
        pass  # Tools defined via decorators below
    
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
        Update Salesforce with call outcome.
        
        Flow:
        1. Generate preview of proposed changes
        2. Post to Slack DM for approval
        3. Wait for sfdc-approve.py token
        4. Execute via sf-safe --live if approved
        5. Return result
        """
        lead_id = args.get("lead_id", "")
        status = args.get("status", "")
        task_description = args.get("task_description", "")
        next_follow_up_date = args.get("next_follow_up_date", "")
        
        # Generate invocation token for correlation
        invocation_token = str(uuid.uuid4())
        
        # Step 1: Build preview of changes
        preview = self._build_preview(lead_id, status, task_description, next_follow_up_date)
        
        # Step 2: Post to Slack for approval
        slack_msg = self._format_slack_approval_request(
            invocation_token, lead_id, status, task_description, 
            next_follow_up_date, preview
        )
        self._post_slack_dm(slack_msg)
        
        # Step 3: Wait for approval token
        approved, reason = self._wait_for_approval(timeout=APPROVAL_TIMEOUT_SECONDS)
        
        if not approved:
            return SwaigFunctionResult(
                f"Salesforce update NOT executed. Reason: {reason}. "
                f"To approve future updates, Samson should run: python3 tools/sfdc-approve.py --reason 'Approved follow-up update'"
            )
        
        # Step 4: Execute live writes via sf-safe
        try:
            results = self._execute_sfdc_writes(
                lead_id, status, task_description, next_follow_up_date
            )
            
            success_count = sum(1 for r in results if r["success"])
            
            if success_count == len(results):
                return SwaigFunctionResult(
                    f"✅ Salesforce updated successfully! Created task and updated status to '{status}'. "
                    f"(Token: {invocation_token[:8]}...)"
                )
            else:
                errors = [r["error"] for r in results if not r["success"]]
                return SwaigFunctionResult(
                    f"⚠️ Partial success: {success_count}/{len(results)} operations succeeded. "
                    f"Errors: {'; '.join(errors)}"
                )
                
        except Exception as e:
            return SwaigFunctionResult(
                f"❌ Salesforce update failed: {str(e)}. Token: {invocation_token[:8]}..."
            )
    
    def _build_preview(self, lead_id: str, status: str, task_description: str, 
                       next_follow_up_date: str) -> str:
        """Build human-readable preview of proposed changes"""
        lines = [
            "📋 PROPOSED SALESFORCE UPDATE",
            "",
            f"   Target: {lead_id}",
            f"   Status: → {status}",
            f"   Task: {task_description[:60]}{'...' if len(task_description) > 60 else ''}",
        ]
        if next_follow_up_date:
            lines.append(f"   Follow-up Date: {next_follow_up_date}")
        
        lines.extend([
            "",
            "🔧 Commands that will execute:",
            f"   1. sf data create record --sobject Task --values \"Subject={task_description[:50]}...|Status=Not Started|WhoId={lead_id}{f'|ActivityDate={next_follow_up_date}' if next_follow_up_date else ''}\"",
            f"   2. sf data update record --sobject Lead --record-id {lead_id} --values \"Status={status}\"",
            "",
            "⏳ Waiting for approval..."
        ])
        
        return "\n".join(lines)
    
    def _format_slack_approval_request(self, token: str, lead_id: str, status: str,
                                       task_description: str, next_date: str, 
                                       preview: str) -> str:
        """Format Slack approval message"""
        return f"""🤖 *AI Voice Caller - Salesforce Update Request*

*Correlation ID:* `{token}`

{preview}

✅ *To APPROVE:*
```
python3 tools/sfdc-approve.py --reason "Approved follow-up for {lead_id}"
```

❌ *To REJECT:*
Do nothing. Request will timeout in 60 minutes.

*Note:* This request came from the Follow-Up Agent after a voice call."""
    
    def _post_slack_dm(self, message: str) -> bool:
        """Post message to Slack DM D0AG2FT2G6M"""
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
                print(f"[FollowUpAgent] Slack approval request sent to D0AG2FT2G6M")
                return True
            else:
                print(f"[FollowUpAgent] Slack API error: {result.get('error')}")
                return False
                
        except Exception as e:
            print(f"[FollowUpAgent] Failed to post to Slack: {e}")
            return False
    
    def _wait_for_approval(self, timeout: int = APPROVAL_TIMEOUT_SECONDS) -> tuple[bool, str]:
        """
        Wait for sfdc-approve.py to create .sfdc-approved token.
        
        Returns: (approved: bool, reason: str)
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if TOKEN_FILE.exists():
                try:
                    with open(TOKEN_FILE) as f:
                        token = json.load(f)
                    
                    created_at = token.get("created_at", 0)
                    ttl = token.get("ttl_seconds", 3600)
                    expires_at = token.get("expires_at", created_at + ttl)
                    
                    if time.time() < expires_at:
                        print(f"[FollowUpAgent] Approval token found: {token.get('reason', 'unspecified')}")
                        return True, f"Approved: {token.get('reason', 'unspecified')}"
                    else:
                        print(f"[FollowUpAgent] Token expired")
                        return False, "Approval token expired"
                        
                except Exception as e:
                    print(f"[FollowUpAgent] Error reading token: {e}")
            
            time.sleep(POLL_INTERVAL)
        
        return False, f"Timeout after {timeout} seconds - no approval received"
    
    def _execute_sfdc_writes(self, lead_id: str, status: str, 
                             task_description: str, next_follow_up_date: str) -> list:
        """
        Execute Salesforce writes via sf-safe --live.
        
        Returns list of result dicts with 'success' and 'error' keys.
        """
        results = []
        
        # Determine if lead_id is Lead or Contact
        object_type = "Lead" if lead_id.startswith("00Q") else "Contact" if lead_id.startswith("003") else "Lead"
        
        # 1. Create Task
        task_values = f"Subject={task_description[:250]}|Status=Not Started|WhoId={lead_id}"
        if next_follow_up_date:
            task_values += f"|ActivityDate={next_follow_up_date}"
        
        task_cmd = [
            str(SF_SAFE_PATH),
            "data", "create", "record",
            "--sobject", "Task",
            "--values", task_values,
            "--live"  # This flag required for actual writes
        ]
        
        results.append(self._run_sf_safe(task_cmd, "Create Task"))
        
        # 2. Update Lead/Contact Status
        status_cmd = [
            str(SF_SAFE_PATH),
            "data", "update", "record",
            "--sobject", object_type,
            "--record-id", lead_id,
            "--values", f"Status={status}",
            "--live"
        ]
        
        results.append(self._run_sf_safe(status_cmd, f"Update {object_type} Status"))
        
        return results
    
    def _run_sf_safe(self, cmd: list, description: str) -> dict:
        """Run sf-safe command and return result dict"""
        try:
            print(f"[FollowUpAgent] Executing: {description}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return {"success": True, "error": None, "output": result.stdout}
            else:
                return {"success": False, "error": result.stderr or result.stdout}
                
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"{description} timed out after 60s"}
        except Exception as e:
            return {"success": False, "error": f"{description} failed: {str(e)}"}


# Convenience function for non-agent usage
def update_salesforce(lead_id: str, status: str, task_description: str,
                     next_follow_up_date: str = "", dry_run: bool = True) -> dict:
    """
    Standalone function to update Salesforce (for use outside SWAIG context).
    
    If dry_run=True, only shows preview and posts to Slack.
    If dry_run=False, waits for approval and executes.
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
    parser.add_argument("--live", action="store_true", help="Wait for approval and execute")
    args = parser.parse_args()
    
    result = update_salesforce(
        args.lead_id, args.status, args.task, args.date,
        dry_run=not args.live
    )
    print(json.dumps(result, indent=2))
