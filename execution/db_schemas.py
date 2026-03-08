"""
db_schemas.py — Pydantic v2 schemas for the AI Voice Caller V2 state machine.

Three schema classes per entity:
  • Base   — shared fields
  • Create — fields required at creation time (for orchestrator inserts)
  • Read   — full fields for API responses / orchestrator reads (includes DB ids + timestamps)

Atomic checkout contract
------------------------
The orchestrator calls AccountRepository.checkout(agent_id) which:
  1. BEGIN IMMEDIATE
  2. SELECT the next due account (account_state in eligible set, next_call_at <= now, checked_out_by IS NULL)
  3. UPDATE account_state='queued', checked_out_by=agent_id, checked_out_at=now
  4. COMMIT
  5. Returns AccountRead

The orchestrator then places the call and calls complete(account_id, outcome_code, ...) which
transitions account_state based on the state machine rules below.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from execution.db_models import AccountState, AgentStatus, CampaignStatus, OutcomeCode, ReferralStatus


# ── shared config ────────────────────────────────────────────────────────────

class _OrmBase(BaseModel):
    """Base with ORM mode enabled for all schemas that read from SQLAlchemy models."""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ─────────────────────────────────────────────────────────────────────────────
# Account
# ─────────────────────────────────────────────────────────────────────────────

class AccountBase(_OrmBase):
    account_name: str = Field(..., max_length=255)
    phone:        str = Field(..., max_length=20, description="E.164 digits, no dashes")
    state:        Optional[str] = Field(None, max_length=2, description="IA / NE / SD")
    vertical:     Optional[str] = Field(None, max_length=100)
    sfdc_id:      Optional[str] = Field(None, max_length=20)
    website:      Optional[str] = Field(None, max_length=255)
    referral_source: Optional[str] = None
    do_not_call:  bool = False

    @field_validator("phone")
    @classmethod
    def strip_phone(cls, v: str) -> str:
        import re
        return re.sub(r"\D", "", v)


class AccountCreate(AccountBase):
    account_id:         Optional[str] = None     # auto-generated if omitted
    referral_parent_id: Optional[str] = None
    metadata_json:      Optional[str] = None


class AccountRead(AccountBase):
    account_id:           str
    account_state:        AccountState
    last_outcome_code:    Optional[OutcomeCode]
    last_interest_score:  Optional[int]
    call_count:           int
    last_called_at:       Optional[datetime]
    next_call_at:         Optional[datetime]
    callback_requested_at: Optional[datetime]
    checked_out_by:       Optional[str]
    checked_out_at:       Optional[datetime]
    current_call_sid:     Optional[str]
    referral_parent_id:   Optional[str]
    metadata_json:        Optional[str]
    created_at:           datetime
    updated_at:           datetime


class AccountSummary(_OrmBase):
    """Lightweight view used by the orchestrator loop — minimal fields."""
    account_id:    str
    account_name:  str
    phone:         str
    state:         Optional[str]
    vertical:      Optional[str]
    sfdc_id:       Optional[str]
    account_state: AccountState
    next_call_at:  Optional[datetime]
    call_count:    int


# ─────────────────────────────────────────────────────────────────────────────
# CallAttempt
# ─────────────────────────────────────────────────────────────────────────────

class CallAttemptBase(_OrmBase):
    account_id:  str
    campaign_id: Optional[str] = None
    agent_id:    Optional[str] = None
    call_sid:    Optional[str] = None
    caller_id:   Optional[str] = None
    prompt_file: Optional[str] = None
    voice_model: Optional[str] = None
    started_at:  datetime


class CallAttemptCreate(CallAttemptBase):
    attempt_id: Optional[str] = None     # auto-generated if omitted


class CallAttemptComplete(_OrmBase):
    """Payload sent by webhook_server.py to close out a call attempt."""
    attempt_id:       str
    account_id:       str
    outcome_code:     OutcomeCode
    interest_score:   Optional[int] = Field(None, ge=1, le=5)
    summary_text:     Optional[str] = None
    ended_at:         datetime
    duration_secs:    Optional[int] = None
    callback_at:      Optional[datetime] = None
    raw_payload_json: Optional[str] = None


class CallAttemptRead(CallAttemptBase):
    attempt_id:       str
    outcome_code:     Optional[OutcomeCode]
    interest_score:   Optional[int]
    summary_text:     Optional[str]
    ended_at:         Optional[datetime]
    duration_secs:    Optional[int]
    callback_at:      Optional[datetime]
    raw_payload_json: Optional[str]
    created_at:       datetime


# ─────────────────────────────────────────────────────────────────────────────
# Campaign
# ─────────────────────────────────────────────────────────────────────────────

class CampaignBase(_OrmBase):
    campaign_name: str = Field(..., max_length=255)
    description:   Optional[str] = None
    vertical:      Optional[str] = None
    state_filter:  Optional[str] = Field(None, description="Comma-sep state codes: 'IA,NE'")
    prompt_file:   Optional[str] = None
    caller_id:     Optional[str] = None
    voice_model:   Optional[str] = None


class CampaignCreate(CampaignBase):
    campaign_id: Optional[str] = None     # auto-generated if omitted


class CampaignRead(CampaignBase):
    campaign_id:         str
    status:              CampaignStatus
    started_at:          Optional[datetime]
    completed_at:        Optional[datetime]
    accounts_total:      int
    accounts_called:     int
    accounts_interested: int
    accounts_voicemail:  int
    accounts_dnc:        int
    created_at:          datetime
    updated_at:          datetime


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class AgentBase(_OrmBase):
    agent_id: str = Field(..., max_length=100)
    hostname: Optional[str] = None
    pid:      Optional[int] = None


class AgentCreate(AgentBase):
    pass


class AgentRead(AgentBase):
    status:            AgentStatus
    calls_made_today:  int
    calls_made_total:  int
    meetings_booked:   int
    last_call_at:      Optional[datetime]
    last_heartbeat_at: Optional[datetime]
    registered_at:     datetime


class AgentHeartbeat(_OrmBase):
    """Payload sent by each agent thread every 30s."""
    agent_id:          str
    status:            AgentStatus
    last_heartbeat_at: datetime
    calls_made_today:  int
    calls_made_total:  int


# ─────────────────────────────────────────────────────────────────────────────
# Referral
# ─────────────────────────────────────────────────────────────────────────────

class ReferralBase(_OrmBase):
    source_account_id:      Optional[str] = None
    source_call_attempt_id: Optional[str] = None
    referred_name:          Optional[str] = None
    referred_phone:         Optional[str] = None
    referred_account:       Optional[str] = None
    referred_title:         Optional[str] = None
    referred_state:         Optional[str] = Field(None, max_length=2)
    notes:                  Optional[str] = None


class ReferralCreate(ReferralBase):
    referral_id: Optional[str] = None


class ReferralRead(ReferralBase):
    referral_id:       str
    target_account_id: Optional[str]
    status:            ReferralStatus
    created_at:        datetime
    processed_at:      Optional[datetime]


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator-level composite types
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutResult(_OrmBase):
    """Returned by AccountRepository.checkout(). None means nothing is due."""
    account:      AccountRead
    attempt_id:   str          # pre-created CallAttempt row (blank outcome)
    campaign_id:  Optional[str]


class CompleteCallRequest(_OrmBase):
    """
    The orchestrator sends this after a call finishes (via webhook or timeout).
    Drives account state transition + closes CallAttempt row.
    """
    account_id:       str
    attempt_id:       str
    agent_id:         str
    outcome_code:     OutcomeCode
    interest_score:   Optional[int] = Field(None, ge=1, le=5)
    summary_text:     Optional[str] = None
    ended_at:         datetime
    duration_secs:    Optional[int] = None
    callback_at:      Optional[datetime] = None
    raw_payload_json: Optional[str] = None
    referral:         Optional[ReferralCreate] = None   # include if referral was given


class StatsResponse(_OrmBase):
    """Quick status counts for the dashboard / Slack report."""
    new:                int = 0
    queued:             int = 0
    in_flight:          int = 0
    voicemail:          int = 0
    no_answer:          int = 0
    callback_requested: int = 0
    interested:         int = 0
    not_interested:     int = 0
    dnc:                int = 0
    referral_given:     int = 0
    converted:          int = 0
    error:              int = 0
    total:              int = 0
