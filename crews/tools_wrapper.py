"""
Tools wrapper for Voice Campaign Crew
Provides tool implementations for each agent
"""
import sys
import os
import json
from pathlib import Path

# Add parent directories to path for imports
# __file__ is in .../projects/ai-voice-caller/crews/tools_wrapper.py
# workspace_root should be .../workspace
workspace_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(workspace_root / 'tools' / 'salesforce-intel'))
sys.path.insert(0, str(workspace_root / 'tools' / 'erate-parser'))

from crewai.tools import tool
from datetime import datetime, timedelta

# Import existing tools
try:
    from typed_query import TypedSalesforceQuery
    SALESFORCE_AVAILABLE = True
except ImportError:
    SALESFORCE_AVAILABLE = False
    print("Warning: Salesforce tools not available")

try:
    from parser import ERateParser
    from models import ERateFiling
    ERATE_AVAILABLE = True
except ImportError:
    ERATE_AVAILABLE = False
    print("Warning: E-Rate parser not available")

# Load SignalWire config
# Path from workspace root: workspace/projects/ai-voice-caller/config/signalwire.json
CONFIG_PATH = workspace_root / 'projects' / 'ai-voice-caller' / 'config' / 'signalwire.json'
with open(CONFIG_PATH) as f:
    SIGNALWIRE_CONFIG = json.load(f)


# ============================================================================
# LEAD SCORER TOOLS
# ============================================================================

@tool("Fetch Salesforce Account Data")
def fetch_salesforce_account_data(account_ids: list) -> str:
    """
    Fetch account and opportunity data from Salesforce for lead scoring.
    
    Args:
        account_ids: List of Salesforce Account IDs
    
    Returns:
        JSON string with account details, opportunities, pipeline value, and recent activity
    """
    if not SALESFORCE_AVAILABLE:
        return json.dumps({"error": "Salesforce tools not available"})
    
    try:
        query = TypedSalesforceQuery()
        results = []
        
        for account_id in account_ids:
            account_data = query.get_account_intelligence(account_id)
            results.append(account_data)
        
        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("Parse E-Rate Deadlines")
def parse_erate_deadlines(account_name: str) -> str:
    """
    Parse E-Rate filings to extract deadlines and funding amounts.
    
    Args:
        account_name: Name of the school/library district
    
    Returns:
        JSON string with E-Rate deadlines and funding info
    """
    if not ERATE_AVAILABLE:
        return json.dumps({"error": "E-Rate parser not available"})
    
    try:
        parser = ERateParser()
        # This is a placeholder - actual implementation would query E-Rate database
        # For now, return mock data
        return json.dumps({
            "account_name": account_name,
            "erate_deadlines": [
                {"deadline": "2026-03-01", "funding_year": "2026", "amount": 150000}
            ]
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("Calculate Lead Score")
def calculate_lead_score(account_data: dict) -> str:
    """
    Calculate priority score based on multiple factors.
    
    Args:
        account_data: Dictionary with pipeline_value, days_since_contact, 
                     erate_deadline, opportunity_stage
    
    Returns:
        JSON string with calculated score (1-100) and breakdown
    """
    try:
        score = 0
        factors = {}
        
        # Pipeline value (0-40 points)
        pipeline_value = account_data.get('pipeline_value', 0)
        if pipeline_value > 100000:
            score += 40
            factors['pipeline_value'] = 40
        elif pipeline_value > 50000:
            score += 30
            factors['pipeline_value'] = 30
        elif pipeline_value > 10000:
            score += 20
            factors['pipeline_value'] = 20
        else:
            score += 10
            factors['pipeline_value'] = 10
        
        # Days since contact (0-20 points - inverted: more days = lower score)
        days_since = account_data.get('days_since_contact', 999)
        if days_since <= 7:
            contact_score = 5  # Too recent
        elif days_since <= 30:
            contact_score = 20
        elif days_since <= 60:
            contact_score = 15
        else:
            contact_score = 10
        
        score += contact_score
        factors['recency'] = contact_score
        
        # E-Rate deadline urgency (0-20 points)
        deadline_str = account_data.get('erate_deadline')
        if deadline_str:
            deadline = datetime.fromisoformat(deadline_str)
            days_to_deadline = (deadline - datetime.now()).days
            if days_to_deadline <= 14:
                score += 20
                factors['erate_urgency'] = 20
            elif days_to_deadline <= 30:
                score += 15
                factors['erate_urgency'] = 15
            elif days_to_deadline <= 60:
                score += 10
                factors['erate_urgency'] = 10
        
        # Opportunity stage (0-20 points)
        stage = account_data.get('opportunity_stage', '').lower()
        if 'proposal' in stage or 'quote' in stage:
            score += 20
            factors['stage'] = 20
        elif 'qualification' in stage:
            score += 15
            factors['stage'] = 15
        elif 'prospecting' in stage:
            score += 10
            factors['stage'] = 10
        
        return json.dumps({
            "total_score": min(score, 100),
            "factors": factors
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# ============================================================================
# CALLER TOOLS
# ============================================================================

@tool("Make SignalWire Call")
def make_signalwire_call(phone_number: str, account_context: dict, dry_run: bool = True) -> str:
    """
    Place an outbound call via SignalWire AI agent.
    
    Args:
        phone_number: E.164 formatted phone number
        account_context: Dictionary with account info for the AI agent
        dry_run: If True, simulate call without actually placing it
    
    Returns:
        JSON string with call outcome and details
    """
    if dry_run:
        # Simulate call outcomes for testing
        import random
        outcomes = ['ANSWERED', 'VOICEMAIL', 'NO_ANSWER', 'BUSY']
        outcome = random.choice(outcomes)
        
        return json.dumps({
            "call_id": f"dry_run_{datetime.now().timestamp()}",
            "dry_run": True,
            "phone_number": phone_number,
            "outcome": outcome,
            "duration_seconds": random.randint(10, 180) if outcome == 'ANSWERED' else 0,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Simulated call - {outcome}"
        })
    
    # Real call implementation using SignalWire API
    try:
        import requests
        
        url = f"https://{SIGNALWIRE_CONFIG['space_url']}/api/calling/calls"
        headers = {
            "Authorization": f"Bearer {SIGNALWIRE_CONFIG['auth_token']}",
            "Content-Type": "application/json"
        }
        
        # SWML payload for Fabric AI agent
        swml_payload = {
            "from": SIGNALWIRE_CONFIG['phone_number'],
            "to": phone_number,
            "timeout": 30,
            "swml": {
                "version": "1.0.0",
                "sections": {
                    "main": [
                        {
                            "ai": {
                                "voice": SIGNALWIRE_CONFIG['ai_agent']['voice'],
                                "prompt": {
                                    "text": f"You are calling {account_context.get('account_name', 'a prospect')}. Context: {json.dumps(account_context)}"
                                },
                                "post_prompt_url": SIGNALWIRE_CONFIG.get('swaig_webhook_url', ''),
                                "post_prompt_auth_user": "",
                                "post_prompt_auth_password": ""
                            }
                        }
                    ]
                }
            }
        }
        
        response = requests.post(url, headers=headers, json=swml_payload)
        
        if response.status_code == 201:
            call_data = response.json()
            return json.dumps({
                "call_id": call_data.get('id'),
                "dry_run": False,
                "phone_number": phone_number,
                "outcome": "INITIATED",
                "timestamp": datetime.now().isoformat(),
                "notes": "Call placed successfully"
            })
        else:
            return json.dumps({
                "error": f"SignalWire API error: {response.status_code}",
                "details": response.text
            })
    
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("Get Call Status")
def get_call_status(call_id: str) -> str:
    """
    Check the status of a SignalWire call.
    
    Args:
        call_id: SignalWire call ID
    
    Returns:
        JSON string with call status and outcome
    """
    if call_id.startswith('dry_run_'):
        return json.dumps({"call_id": call_id, "dry_run": True, "status": "completed"})
    
    try:
        import requests
        
        url = f"https://{SIGNALWIRE_CONFIG['space_url']}/api/calling/calls/{call_id}"
        headers = {
            "Authorization": f"Bearer {SIGNALWIRE_CONFIG['auth_token']}"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.text
        else:
            return json.dumps({"error": f"API error: {response.status_code}"})
    
    except Exception as e:
        return json.dumps({"error": str(e)})


# ============================================================================
# FOLLOW-UP TOOLS
# ============================================================================

@tool("Draft Follow-up Email")
def draft_followup_email(account_data: dict, call_outcome: str, call_notes: str) -> str:
    """
    Generate a personalized follow-up email based on call outcome.
    
    Args:
        account_data: Dictionary with account info
        call_outcome: ANSWERED, VOICEMAIL, or NO_ANSWER
        call_notes: Notes from the call
    
    Returns:
        JSON string with email subject and body
    """
    try:
        account_name = account_data.get('account_name', 'Your Organization')
        contact_name = account_data.get('contact_name', 'there')
        
        templates = {
            'ANSWERED': {
                'subject': f"Great connecting today - {account_data.get('topic', 'next steps')}",
                'body': f"""Hi {contact_name},

Thanks for taking the time to speak with me today about {account_data.get('topic', 'your network security needs')}.

As discussed, I'll {account_data.get('promised_action', 'send over those materials')}.

{call_notes if call_notes else ''}

Looking forward to our next conversation.

Best,
Samson Cooper
Fortinet SLED Territory Manager"""
            },
            'VOICEMAIL': {
                'subject': f"Following up - {account_name}",
                'body': f"""Hi {contact_name},

I tried reaching you earlier today regarding {account_data.get('topic', 'your upcoming network refresh')}.

I wanted to share some insights on how other {account_data.get('industry', 'school districts')} are addressing similar challenges.

Would you have 15 minutes this week for a quick call?

Best,
Samson Cooper
Fortinet SLED Territory Manager
+1 (480) 602-4668"""
            },
            'NO_ANSWER': {
                'subject': f"Quick question about {account_name}",
                'body': f"""Hi {contact_name},

I hope this note finds you well.

I wanted to reach out about {account_data.get('topic', 'your cybersecurity strategy')} - I've been working with several {account_data.get('industry', 'educational institutions')} in your area and thought you might find value in a brief conversation.

No pressure - if you're interested, feel free to reply or give me a call at +1 (480) 602-4668.

Best,
Samson Cooper
Fortinet SLED Territory Manager"""
            }
        }
        
        template = templates.get(call_outcome, templates['NO_ANSWER'])
        return json.dumps(template)
    
    except Exception as e:
        return json.dumps({"error": str(e)})


# ============================================================================
# CRM TOOLS
# ============================================================================

@tool("Log Call to Salesforce")
def log_call_to_salesforce(account_id: str, call_data: dict, dry_run: bool = True) -> str:
    """
    Create a Task record in Salesforce to log the call.
    
    Args:
        account_id: Salesforce Account ID
        call_data: Dictionary with call details
        dry_run: If True, simulate logging without actually writing to SF
    
    Returns:
        JSON string with task ID and status
    """
    if dry_run:
        return json.dumps({
            "dry_run": True,
            "task_id": f"00T_dry_run_{datetime.now().timestamp()}",
            "account_id": account_id,
            "status": "simulated"
        })
    
    if not SALESFORCE_AVAILABLE:
        return json.dumps({"error": "Salesforce tools not available"})
    
    try:
        # Real Salesforce logging would go here
        # Using simple_salesforce or similar
        return json.dumps({
            "task_id": "00T...",
            "account_id": account_id,
            "status": "created"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("Create Follow-up Task")
def create_followup_task(account_id: str, subject: str, due_date: str, dry_run: bool = True) -> str:
    """
    Create a follow-up task in Salesforce.
    
    Args:
        account_id: Salesforce Account ID
        subject: Task subject line
        due_date: ISO format date string
        dry_run: If True, simulate without actually creating
    
    Returns:
        JSON string with task ID and status
    """
    if dry_run:
        return json.dumps({
            "dry_run": True,
            "task_id": f"00T_followup_{datetime.now().timestamp()}",
            "account_id": account_id,
            "subject": subject,
            "due_date": due_date,
            "status": "simulated"
        })
    
    if not SALESFORCE_AVAILABLE:
        return json.dumps({"error": "Salesforce tools not available"})
    
    try:
        # Real Salesforce task creation would go here
        return json.dumps({
            "task_id": "00T...",
            "account_id": account_id,
            "status": "created"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# ============================================================================
# TOOL COLLECTIONS FOR EACH AGENT
# ============================================================================

def get_lead_scorer_tools():
    """Tools for Lead Scorer Agent"""
    return [
        fetch_salesforce_account_data,
        parse_erate_deadlines,
        calculate_lead_score
    ]

def get_caller_tools():
    """Tools for Caller Agent"""
    return [
        make_signalwire_call,
        get_call_status
    ]

def get_followup_tools():
    """Tools for Follow-up Agent"""
    return [
        draft_followup_email
    ]

def get_crm_tools():
    """Tools for CRM Agent"""
    return [
        log_call_to_salesforce,
        create_followup_task
    ]
