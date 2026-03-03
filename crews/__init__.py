"""
Voice Campaign Crew - CrewAI-based calling automation

Provides end-to-end orchestration for outbound calling campaigns:
- Lead scoring and prioritization
- Call execution via SignalWire
- Outcome-based follow-up email generation
- CRM logging and task creation

Usage:
    from crews import create_voice_campaign_crew
    
    accounts = [...]  # List of account dictionaries
    crew = create_voice_campaign_crew(accounts, dry_run=True)
    results = crew.run_campaign()
"""

from .crew import create_voice_campaign_crew, VoiceCampaignCrew
from .agents import (
    create_lead_scorer_agent,
    create_caller_agent,
    create_followup_agent,
    create_crm_agent
)

__all__ = [
    'create_voice_campaign_crew',
    'VoiceCampaignCrew',
    'create_lead_scorer_agent',
    'create_caller_agent',
    'create_followup_agent',
    'create_crm_agent'
]

__version__ = '1.0.0'
