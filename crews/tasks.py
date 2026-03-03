"""
Task definitions for Voice Campaign Crew
Each task corresponds to a step in the calling workflow
"""
from crewai import Task
from textwrap import dedent

def create_lead_scoring_task(agent, account_list, salesforce_data):
    """Task: Score and prioritize accounts for calling"""
    return Task(
        description=dedent(f"""
            Score and prioritize the following accounts for today's calling campaign:
            
            Account List:
            {account_list}
            
            Salesforce Context:
            {salesforce_data}
            
            Your objectives:
            1. Calculate priority score for each account based on:
               - Pipeline value (higher = more priority)
               - E-Rate deadline urgency (closer deadline = higher priority)
               - Days since last contact (longer = lower priority unless strategic)
               - Opportunity stage (proposal/quote stage = high priority)
               - Recent activity signals (quote requests, downloads, etc.)
            
            2. Identify call timing considerations:
               - Best time to call based on timezone
               - Avoid accounts contacted in past 7 days
               - Flag accounts with scheduled meetings (don't call before meeting)
            
            3. Generate prioritized call list with:
               - Account name and contact info
               - Priority score (1-100)
               - Key talking points for caller
               - Any special considerations (renewal date, competitor threat, etc.)
            
            Output a ranked list of 10-20 accounts ready to call TODAY.
        """),
        agent=agent,
        expected_output=dedent("""
            A prioritized call list in JSON format:
            [
                {{
                    "account_name": "Example School District",
                    "account_id": "001...",
                    "contact_name": "Jane Doe",
                    "phone": "+1234567890",
                    "priority_score": 85,
                    "score_factors": {{
                        "pipeline_value": 50000,
                        "days_since_contact": 14,
                        "erate_deadline": "2026-03-01",
                        "opportunity_stage": "Proposal"
                    }},
                    "talking_points": ["Renewal due in 30 days", "Requested FortiGate quote"],
                    "best_call_time": "09:00-11:00 MST"
                }}
            ]
        """)
    )

def create_calling_task(agent, prioritized_leads, dry_run=True):
    """Task: Execute calls and track outcomes"""
    return Task(
        description=dedent(f"""
            Execute outbound calling campaign for the prioritized lead list.
            
            Prioritized Leads:
            {prioritized_leads}
            
            DRY RUN MODE: {'ENABLED - Do not make actual calls' if dry_run else 'DISABLED - Making real calls'}
            
            Your objectives:
            1. For each lead in priority order:
               {'- SIMULATE call execution (dry run)' if dry_run else '- Place call via SignalWire using Cold Caller agent (a774d2ee-dac8-4eb2-9832-845536168e52)'}
               - Track call outcome: ANSWERED, VOICEMAIL, NO_ANSWER, BUSY, FAILED
               - Record call duration and any AI agent notes
               - Capture conversation highlights if answered
            
            2. Respect rate limits:
               - Minimum 30 seconds between calls
               - Maximum 20 calls per hour
               - Stop after 3 consecutive failures
            
            3. Call outcome handling:
               - ANSWERED: Flag for immediate follow-up email + CRM logging
               - VOICEMAIL: Flag for voicemail follow-up email + retry in 48h
               - NO_ANSWER: Flag for soft touch email + retry in 24h
               - FAILED: Log error and move to next lead
            
            4. Generate call log with:
               - Timestamp, account, contact, phone number
               - Outcome, duration, notes
               - Next action required
            
            {'SIMULATE realistic outcomes for testing purposes.' if dry_run else 'Use SignalWire API to place real calls.'}
        """),
        agent=agent,
        expected_output=dedent("""
            A call log in JSON format:
            {{
                "campaign_id": "voice_campaign_2026-02-12",
                "dry_run": true/false,
                "total_calls": 15,
                "outcomes": {{
                    "answered": 3,
                    "voicemail": 7,
                    "no_answer": 4,
                    "failed": 1
                }},
                "calls": [
                    {{
                        "timestamp": "2026-02-12T10:15:00Z",
                        "account_name": "Example School",
                        "account_id": "001...",
                        "contact_name": "Jane Doe",
                        "phone": "+1234567890",
                        "outcome": "ANSWERED",
                        "duration_seconds": 120,
                        "notes": "Spoke with Jane about renewal, interested in demo",
                        "next_action": "Send follow-up email with demo link"
                    }}
                ]
            }}
        """)
    )

def create_followup_task(agent, call_log):
    """Task: Draft follow-up emails based on call outcomes"""
    return Task(
        description=dedent(f"""
            Draft personalized follow-up emails for each call outcome.
            
            Call Log:
            {call_log}
            
            Your objectives:
            1. For each call, draft an appropriate follow-up email:
            
               ANSWERED:
               - Thank them for their time
               - Recap key discussion points
               - Include promised resources (demo link, whitepaper, etc.)
               - Clear next step (schedule demo, send proposal, etc.)
               - Warm, conversational tone
            
               VOICEMAIL:
               - Acknowledge you called and left a voicemail
               - Brief value proposition (why you're reaching out)
               - Easy reply option or suggest a call time
               - Not pushy, professional tone
            
               NO_ANSWER:
               - Soft touch: "Tried to reach you..."
               - Share something valuable (insight, resource)
               - Low-pressure invitation to connect
               - Friendly, helpful tone
            
            2. Personalize each email with:
               - Account-specific context (renewal date, products owned, etc.)
               - Reference to recent activity if available
               - Industry-relevant pain points or trends
            
            3. Keep emails concise: 100-200 words
            
            4. Include clear subject lines that vary by outcome
        """),
        agent=agent,
        expected_output=dedent("""
            A collection of draft emails in JSON format:
            [
                {{
                    "account_name": "Example School",
                    "account_id": "001...",
                    "contact_name": "Jane Doe",
                    "contact_email": "jane@example.edu",
                    "call_outcome": "ANSWERED",
                    "subject": "Demo link + FortiGate renewal options",
                    "body": "Hi Jane,\\n\\nGreat talking with you this morning about your network refresh project...\\n\\nBest,\\nSamson",
                    "send_priority": "immediate",
                    "draft_status": "ready_to_send"
                }}
            ]
        """)
    )

def create_crm_logging_task(agent, call_log, follow_up_emails):
    """Task: Log all activity to Salesforce"""
    return Task(
        description=dedent(f"""
            Log all call outcomes and follow-up actions to Salesforce.
            
            Call Log:
            {call_log}
            
            Follow-up Emails:
            {follow_up_emails}
            
            Your objectives:
            1. For each call, create a Salesforce Task record:
               - Subject: "Outbound Call - [OUTCOME]"
               - Description: Call notes and conversation summary
               - Status: Completed
               - Activity Date: Call timestamp
               - Related To: Account and Opportunity (if applicable)
            
            2. Update Account fields:
               - Last Contact Date
               - Last Contact Type: "Outbound Call"
               - Call Outcome: ANSWERED/VOICEMAIL/NO_ANSWER
            
            3. Create follow-up tasks:
               - ANSWERED: "Send demo materials" (due today)
               - VOICEMAIL: "Follow-up call" (due in 48h)
               - NO_ANSWER: "Retry call" (due in 24h)
            
            4. Update Opportunity stages if applicable:
               - If call resulted in demo request → move to "Demo Scheduled"
               - If call confirmed interest → update "Next Steps" field
            
            5. Log email follow-ups as separate activities
            
            6. Generate summary report of all Salesforce updates
        """),
        agent=agent,
        expected_output=dedent("""
            A Salesforce update report in JSON format:
            {{
                "summary": {{
                    "tasks_created": 15,
                    "accounts_updated": 15,
                    "opportunities_updated": 5,
                    "follow_up_tasks_created": 15
                }},
                "updates": [
                    {{
                        "account_id": "001...",
                        "account_name": "Example School",
                        "task_id": "00T...",
                        "task_subject": "Outbound Call - ANSWERED",
                        "follow_up_task_id": "00T...",
                        "follow_up_subject": "Send demo materials",
                        "follow_up_due_date": "2026-02-12",
                        "account_fields_updated": ["Last_Contact_Date__c", "Last_Call_Outcome__c"],
                        "opportunity_updated": "006...",
                        "opportunity_stage_change": "Qualification → Demo Scheduled"
                    }}
                ]
            }}
        """)
    )
