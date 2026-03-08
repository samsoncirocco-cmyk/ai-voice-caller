"""
db_models.py — SQLAlchemy 2.0 ORM models for the AI Voice Caller V2 state machine.

Tables
------
  accounts      — Every callable target; owns the state machine
  call_attempts — One row per outbound call attempt (full audit trail)
  campaigns     — Logical grouping of a batch of calls
  agents        — Active orchestrator workers (heartbeat + ownership)
  referrals     — Contacts surfaced during calls that become new accounts

State machine transitions (accounts.account_state)
---------------------------------------------------
  new ──────────────────────────────────► queued
  queued ───────────────────────────────► in_flight
  in_flight ────────────────────────────► voicemail        (cooldown 2d)
                                        ► no_answer         (cooldown 1d)
                                        ► callback_requested(cooldown until cb_at)
                                        ► interested        (terminal – human takes over)
                                        ► not_interested    (cooldown 30d)
                                        ► dnc               (terminal – never call)
                                        ► referral_given    (terminal – referral queued)
                                        ► converted         (terminal – deal in SFDC)
                                        ► error             (cooldown 1h – retry)
  voicemail / no_answer / not_interested ► new (after cooldown expires)
  callback_requested ──────────────────► new (at callback_at)
"""

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from execution.db_engine import Base


# ── helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── enums ─────────────────────────────────────────────────────────────────────

class AccountState(str, enum.Enum):
    """Full state machine for an account in the calling pipeline."""
    # ── entry states ──
    new                = "new"                # just seeded, never touched
    queued             = "queued"             # dispatcher grabbed it, call pending
    in_flight          = "in_flight"          # SignalWire call is live right now
    # ── transient outcomes ──
    voicemail          = "voicemail"          # reached VM → retry in 2d
    no_answer          = "no_answer"          # rang out → retry in 1d
    callback_requested = "callback_requested" # contact asked us to call back
    not_interested     = "not_interested"     # said no → retry in 30d
    error              = "error"              # technical failure → retry in 1h
    # ── terminal outcomes ──
    interested         = "interested"         # positive → human follow-up
    dnc                = "dnc"               # do not call ever
    referral_given     = "referral_given"     # gave us another contact
    converted          = "converted"          # became SFDC opp / deal


class OutcomeCode(str, enum.Enum):
    """Granular outcome codes for a single call attempt."""
    voicemail          = "voicemail"
    no_answer          = "no_answer"
    hung_up            = "hung_up"
    not_interested     = "not_interested"
    interested         = "interested"
    meeting_booked     = "meeting_booked"
    callback_requested = "callback_requested"
    referral_given     = "referral_given"
    dnc                = "dnc"
    converted          = "converted"
    error_swml         = "error_swml"         # SignalWire SWML error
    error_carrier      = "error_carrier"      # carrier / SIP error
    error_timeout      = "error_timeout"      # no webhook received in time


class AgentStatus(str, enum.Enum):
    idle    = "idle"
    busy    = "busy"
    paused  = "paused"
    stopped = "stopped"


class CampaignStatus(str, enum.Enum):
    draft     = "draft"
    running   = "running"
    paused    = "paused"
    completed = "completed"
    archived  = "archived"


class ReferralStatus(str, enum.Enum):
    pending   = "pending"   # captured, not yet created as an account
    queued    = "queued"    # account row created, waiting for first call
    processed = "processed" # call made to the referral


# ── models ────────────────────────────────────────────────────────────────────

class Account(Base):
    """
    Core entity. One row per callable target (school, municipality, etc.).

    The `account_state` column drives the entire scheduling loop.
    Atomic checkout is done by setting account_state='queued' + checked_out_by
    inside a BEGIN IMMEDIATE transaction (mirrors existing account_db.py logic).
    """
    __tablename__ = "accounts_v2"

    # ── identity ──
    account_id:   Mapped[str] = mapped_column(String(36), primary_key=True)   # UUID4
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone:        Mapped[str] = mapped_column(String(20),  nullable=False)     # E.164 digits
    state:        Mapped[Optional[str]] = mapped_column(String(2))             # IA/NE/SD
    vertical:     Mapped[Optional[str]] = mapped_column(String(100))
    sfdc_id:      Mapped[Optional[str]] = mapped_column(String(20), index=True)  # 18-char SFDC ID
    website:      Mapped[Optional[str]] = mapped_column(String(255))

    # ── state machine ──
    account_state: Mapped[AccountState] = mapped_column(
        Enum(AccountState, name="account_state_enum"),
        nullable=False,
        default=AccountState.new,
        index=True,
    )
    last_outcome_code:    Mapped[Optional[OutcomeCode]] = mapped_column(
        Enum(OutcomeCode, name="outcome_code_enum")
    )
    last_interest_score:  Mapped[Optional[int]] = mapped_column(Integer)       # 1–5
    call_count:           Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_called_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_call_at:         Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )                                                                          # NULL = due now
    callback_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── agent ownership ──
    checked_out_by:  Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("agents.agent_id", ondelete="SET NULL"), index=True
    )
    checked_out_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_call_sid: Mapped[Optional[str]] = mapped_column(String(100))      # live SW SID

    # ── provenance ──
    referral_source:    Mapped[Optional[str]] = mapped_column(String(100))    # how it got in
    referral_parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts_v2.account_id", ondelete="SET NULL")
    )                                                                          # who referred it
    do_not_call: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── extra data ──
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)                # JSON blob

    # ── audit ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── relationships ──
    call_attempts:    Mapped[List["CallAttempt"]]  = relationship(back_populates="account")
    referrals_given:  Mapped[List["Referral"]]     = relationship(
        back_populates="source_account", foreign_keys="[Referral.source_account_id]"
    )
    checked_out_agent: Mapped[Optional["Agent"]] = relationship(
        back_populates="current_accounts", foreign_keys=[checked_out_by]
    )
    referred_children: Mapped[List["Account"]] = relationship(
        "Account", foreign_keys=[referral_parent_id]
    )

    __table_args__ = (
        # Scheduling index: find next due account quickly
        Index(
            "ix_accounts_v2_schedule",
            "account_state", "next_call_at", "checked_out_by",
        ),
        # Unique per phone+name (prevents duplicate seeding)
        UniqueConstraint("phone", "account_name", name="uq_accounts_v2_phone_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<Account {self.account_id[:8]}… "
            f"name={self.account_name!r} "
            f"state={self.account_state.value}>"
        )


class CallAttempt(Base):
    """
    One row per outbound call. Full audit trail — nothing is ever deleted.

    The `outcome_code` is set by the webhook server after SignalWire posts
    the post-call summary. An in-flight call has outcome_code=NULL.
    """
    __tablename__ = "call_attempts"

    attempt_id:  Mapped[str] = mapped_column(String(36), primary_key=True)    # UUID4
    account_id:  Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts_v2.account_id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("campaigns.campaign_id", ondelete="SET NULL")
    )
    agent_id:    Mapped[Optional[str]] = mapped_column(String(100))            # orchestrator thread

    # ── call metadata ──
    call_sid:    Mapped[Optional[str]] = mapped_column(String(100), index=True)  # SW call SID
    caller_id:   Mapped[Optional[str]] = mapped_column(String(20))               # +1602…
    prompt_file: Mapped[Optional[str]] = mapped_column(String(255))
    voice_model: Mapped[Optional[str]] = mapped_column(String(100))              # openai.onyx

    # ── timing ──
    started_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_secs: Mapped[Optional[int]] = mapped_column(Integer)

    # ── outcome ──
    outcome_code:    Mapped[Optional[OutcomeCode]] = mapped_column(
        Enum(OutcomeCode, name="call_outcome_code_enum")
    )
    interest_score:  Mapped[Optional[int]] = mapped_column(Integer)            # 1–5
    summary_text:    Mapped[Optional[str]] = mapped_column(Text)               # AI summary
    callback_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_payload_json: Mapped[Optional[str]] = mapped_column(Text)             # full SW payload

    # ── audit ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── relationships ──
    account:  Mapped["Account"]            = relationship(back_populates="call_attempts")
    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="call_attempts")

    __table_args__ = (
        Index("ix_call_attempts_account_started", "account_id", "started_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<CallAttempt {self.attempt_id[:8]}… "
            f"account={self.account_id[:8]}… "
            f"outcome={self.outcome_code}>"
        )


class Campaign(Base):
    """
    Logical grouping for a batch of calls (e.g. 'K-12 Iowa March').

    A campaign knows its target vertical, state filter, and which prompt/
    caller-ID to use. One campaign can span many agents and many days.
    """
    __tablename__ = "campaigns"

    campaign_id:   Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID4
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description:   Mapped[Optional[str]] = mapped_column(Text)

    # ── targeting ──
    vertical:     Mapped[Optional[str]] = mapped_column(String(100))
    state_filter: Mapped[Optional[str]] = mapped_column(String(20))            # "IA,NE,SD"

    # ── configuration ──
    prompt_file: Mapped[Optional[str]] = mapped_column(String(255))
    caller_id:   Mapped[Optional[str]] = mapped_column(String(20))
    voice_model: Mapped[Optional[str]] = mapped_column(String(100))

    # ── status ──
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status_enum"),
        nullable=False,
        default=CampaignStatus.draft,
    )
    started_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── counters (denormalized for fast dashboard reads) ──
    accounts_total:      Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_called:     Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_interested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_voicemail:  Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_dnc:        Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── audit ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── relationships ──
    call_attempts: Mapped[List["CallAttempt"]] = relationship(back_populates="campaign")

    def __repr__(self) -> str:
        return f"<Campaign {self.campaign_id[:8]}… name={self.campaign_name!r} status={self.status.value}>"


class Agent(Base):
    """
    Represents one orchestrator worker thread / process.

    The agent heartbeats its `last_heartbeat_at` every ~30s. The supervisor
    uses this to detect crashed agents and release their checked-out accounts.
    """
    __tablename__ = "agents"

    agent_id:   Mapped[str] = mapped_column(String(100), primary_key=True)    # e.g. "agent-3"
    hostname:   Mapped[Optional[str]] = mapped_column(String(255))
    pid:        Mapped[Optional[int]] = mapped_column(Integer)

    # ── state ──
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status_enum"),
        nullable=False,
        default=AgentStatus.idle,
    )

    # ── performance counters ──
    calls_made_today:  Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_made_total:  Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meetings_booked:   Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── timing ──
    last_call_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    registered_at:     Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── relationships ──
    current_accounts: Mapped[List["Account"]] = relationship(
        back_populates="checked_out_agent",
        foreign_keys="[Account.checked_out_by]",
    )

    def __repr__(self) -> str:
        return f"<Agent {self.agent_id} status={self.status.value} calls={self.calls_made_today}>"


class Referral(Base):
    """
    A contact surfaced during a call that should become a new callable target.

    The orchestrator creates an Account row for a referral once status='queued'.
    """
    __tablename__ = "referrals"

    referral_id:           Mapped[str] = mapped_column(String(36), primary_key=True)
    source_account_id:     Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts_v2.account_id", ondelete="SET NULL")
    )
    source_call_attempt_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("call_attempts.attempt_id", ondelete="SET NULL")
    )
    target_account_id:     Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts_v2.account_id", ondelete="SET NULL")
    )

    # ── contact data ──
    referred_name:    Mapped[Optional[str]] = mapped_column(String(255))
    referred_phone:   Mapped[Optional[str]] = mapped_column(String(20))
    referred_account: Mapped[Optional[str]] = mapped_column(String(255))
    referred_title:   Mapped[Optional[str]] = mapped_column(String(255))
    referred_state:   Mapped[Optional[str]] = mapped_column(String(2))
    notes:            Mapped[Optional[str]] = mapped_column(Text)

    # ── status ──
    status: Mapped[ReferralStatus] = mapped_column(
        Enum(ReferralStatus, name="referral_status_enum"),
        nullable=False,
        default=ReferralStatus.pending,
    )

    # ── audit ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── relationships ──
    source_account: Mapped[Optional["Account"]] = relationship(
        back_populates="referrals_given",
        foreign_keys=[source_account_id],
    )

    def __repr__(self) -> str:
        return (
            f"<Referral {self.referral_id[:8]}… "
            f"name={self.referred_name!r} "
            f"status={self.status.value}>"
        )


class Opportunity(Base):
    """
    Salesforce opportunities synced via sfdc_live_sync.py.

    Kept separate from Account to avoid denormalizing SFDC data.
    One account can have many opportunities.
    """
    __tablename__ = "opportunities"

    opp_id:          Mapped[str] = mapped_column(String(36), primary_key=True)
    sfdc_opp_id:     Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    sfdc_account_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    account_name:    Mapped[Optional[str]] = mapped_column(String(255))
    opp_name:        Mapped[Optional[str]] = mapped_column(String(255))
    stage:           Mapped[Optional[str]] = mapped_column(String(100))
    amount:          Mapped[Optional[float]] = mapped_column(Float)
    close_date:      Mapped[Optional[str]] = mapped_column(String(10))          # YYYY-MM-DD
    probability:     Mapped[Optional[float]] = mapped_column(Float)
    state:           Mapped[Optional[str]] = mapped_column(String(2))
    synced_at:       Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:
        return f"<Opportunity {self.sfdc_opp_id} stage={self.stage!r} amt={self.amount}>"
