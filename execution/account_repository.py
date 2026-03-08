"""
account_repository.py — Data access layer for AI Voice Caller V2.

The orchestrator imports ONLY this module. It never touches raw SQL.

Key guarantees:
  • checkout()  — BEGIN IMMEDIATE ensures only one agent ever gets an account
  • complete()  — validates the state machine transition, writes CallAttempt outcome
  • heartbeat() — agents ping every 30s; supervisor detects stale checkouts and releases them
  • release_stale() — called by orchestrator supervisor thread on startup and every N minutes

State machine transition table
-------------------------------
From            | Trigger               | To
----------------|----------------------|----------------------
new             | checkout()           | queued
queued          | _set_in_flight()     | in_flight
in_flight       | complete(voicemail)  | voicemail
in_flight       | complete(no_answer)  | no_answer
in_flight       | complete(callback_*) | callback_requested
in_flight       | complete(interested) | interested  [terminal]
in_flight       | complete(not_int…)   | not_interested
in_flight       | complete(dnc)        | dnc         [terminal]
in_flight       | complete(referral_*) | referral_given [terminal]
in_flight       | complete(converted)  | converted   [terminal]
in_flight       | complete(error_*)    | error
voicemail       | cooldown expires     | new  (via next_call_at)
no_answer       | cooldown expires     | new
callback_req.   | callback_at arrives  | new
not_interested  | cooldown expires     | new
error           | cooldown expires     | new
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from execution.db_engine import get_session
from execution.db_models import (
    Account,
    AccountState,
    Agent,
    AgentStatus,
    CallAttempt,
    Campaign,
    OutcomeCode,
    Referral,
    ReferralStatus,
)
from execution.db_schemas import (
    AccountRead,
    AccountSummary,
    AgentRead,
    CallAttemptRead,
    CheckoutResult,
    CompleteCallRequest,
    ReferralCreate,
    StatsResponse,
)

log = logging.getLogger(__name__)

# ── cooldown rules (state → days until next_call_at) ─────────────────────────
# None = never re-queue automatically (terminal)
COOLDOWN: Dict[AccountState, Optional[float]] = {
    AccountState.voicemail:          2.0,
    AccountState.no_answer:          1.0,
    AccountState.not_interested:     30.0,
    AccountState.error:              1 / 24,  # 1 hour
    AccountState.callback_requested: None,     # uses callback_at instead
    # terminals
    AccountState.interested:         None,
    AccountState.dnc:                None,
    AccountState.referral_given:     None,
    AccountState.converted:          None,
}

# Outcome code → account state mapping
OUTCOME_TO_STATE: Dict[OutcomeCode, AccountState] = {
    OutcomeCode.voicemail:          AccountState.voicemail,
    OutcomeCode.no_answer:          AccountState.no_answer,
    OutcomeCode.hung_up:            AccountState.no_answer,
    OutcomeCode.not_interested:     AccountState.not_interested,
    OutcomeCode.interested:         AccountState.interested,
    OutcomeCode.meeting_booked:     AccountState.interested,
    OutcomeCode.callback_requested: AccountState.callback_requested,
    OutcomeCode.referral_given:     AccountState.referral_given,
    OutcomeCode.dnc:                AccountState.dnc,
    OutcomeCode.converted:          AccountState.converted,
    OutcomeCode.error_swml:         AccountState.error,
    OutcomeCode.error_carrier:      AccountState.error,
    OutcomeCode.error_timeout:      AccountState.error,
}

# States from which an account is eligible for checkout
CHECKABLE_STATES = {
    AccountState.new,
    AccountState.voicemail,
    AccountState.no_answer,
    AccountState.not_interested,
    AccountState.callback_requested,
    AccountState.error,
}

# Terminal states (never re-queue automatically)
TERMINAL_STATES = {
    AccountState.interested,
    AccountState.dnc,
    AccountState.referral_given,
    AccountState.converted,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_call_dt(state: AccountState, callback_at: Optional[datetime] = None) -> Optional[datetime]:
    """Compute next_call_at for the given post-outcome state."""
    if state == AccountState.callback_requested and callback_at:
        return callback_at
    days = COOLDOWN.get(state)
    if days is None:
        return None  # terminal or callback_requested with no explicit time
    return _now() + timedelta(days=days)


# ─────────────────────────────────────────────────────────────────────────────
# AccountRepository
# ─────────────────────────────────────────────────────────────────────────────

class AccountRepository:
    """
    All state-machine operations in one place.

    Every mutating method uses BEGIN IMMEDIATE to serialise concurrent agents.
    """

    # ── checkout ─────────────────────────────────────────────────────────────

    def checkout(
        self,
        agent_id: str,
        campaign_id: Optional[str] = None,
        state_filter: Optional[List[str]] = None,
        vertical_filter: Optional[List[str]] = None,
    ) -> Optional[CheckoutResult]:
        """
        Atomically assign the next due account to agent_id.

        Returns a CheckoutResult (account + pre-created attempt_id), or None if
        nothing is due.

        Eligibility:
          - account_state in CHECKABLE_STATES
          - next_call_at IS NULL or <= now
          - checked_out_by IS NULL
          - do_not_call = False

        Priority order: new > no_answer > voicemail > callback_requested > not_interested > error,
        then by next_call_at ASC NULLS FIRST.
        """
        now = _now()
        priority = {
            AccountState.new:                1,
            AccountState.no_answer:          2,
            AccountState.voicemail:          3,
            AccountState.callback_requested: 4,
            AccountState.not_interested:     5,
            AccountState.error:              6,
        }

        with get_session() as session:
            # BEGIN IMMEDIATE so no other agent can grab the same row
            session.execute(text("BEGIN IMMEDIATE"))

            query = (
                select(Account)
                .where(
                    Account.account_state.in_(list(CHECKABLE_STATES)),
                    (Account.next_call_at.is_(None)) | (Account.next_call_at <= now),
                    Account.checked_out_by.is_(None),
                    Account.do_not_call.is_(False),
                )
            )
            if state_filter:
                query = query.where(Account.state.in_(state_filter))
            if vertical_filter:
                query = query.where(Account.vertical.in_(vertical_filter))

            candidates = session.scalars(query).all()
            if not candidates:
                session.execute(text("ROLLBACK"))
                return None

            # Pick highest-priority, earliest next_call_at
            account = sorted(
                candidates,
                key=lambda a: (
                    priority.get(a.account_state, 99),
                    a.next_call_at or datetime.min.replace(tzinfo=timezone.utc),
                ),
            )[0]

            # Transition: → queued
            account.account_state   = AccountState.queued
            account.checked_out_by  = agent_id
            account.checked_out_at  = now
            account.updated_at      = now

            # Pre-create the CallAttempt row (outcome=None until call ends)
            attempt = CallAttempt(
                attempt_id  = str(uuid.uuid4()),
                account_id  = account.account_id,
                campaign_id = campaign_id,
                agent_id    = agent_id,
                started_at  = now,
                created_at  = now,
            )
            session.add(attempt)
            session.flush()

            account_read = AccountRead.model_validate(account)
            attempt_id   = attempt.attempt_id

        return CheckoutResult(
            account    = account_read,
            attempt_id = attempt_id,
            campaign_id= campaign_id,
        )

    # ── set in-flight ─────────────────────────────────────────────────────────

    def set_in_flight(
        self,
        account_id: str,
        attempt_id: str,
        call_sid: str,
        caller_id: Optional[str] = None,
        prompt_file: Optional[str] = None,
        voice_model: Optional[str] = None,
    ) -> bool:
        """
        Called once SignalWire confirms the call is dialling.
        Transitions account: queued → in_flight.
        """
        now = _now()
        with get_session() as session:
            session.execute(text("BEGIN IMMEDIATE"))

            account = session.get(Account, account_id)
            if account is None:
                log.error("set_in_flight: account %s not found", account_id)
                session.execute(text("ROLLBACK"))
                return False

            account.account_state    = AccountState.in_flight
            account.current_call_sid = call_sid
            account.updated_at       = now

            attempt = session.get(CallAttempt, attempt_id)
            if attempt:
                attempt.call_sid    = call_sid
                attempt.caller_id   = caller_id
                attempt.prompt_file = prompt_file
                attempt.voice_model = voice_model

        return True

    # ── complete ──────────────────────────────────────────────────────────────

    def complete(self, req: CompleteCallRequest) -> bool:
        """
        Close out a call attempt and advance the account state machine.

        Steps:
          1. Map outcome_code → new account_state
          2. Compute next_call_at based on state
          3. Update account row (clear checkout, set counters)
          4. Fill in the CallAttempt row
          5. Optionally create a Referral row
        """
        now           = _now()
        new_state     = OUTCOME_TO_STATE.get(req.outcome_code, AccountState.error)
        next_call     = _next_call_dt(new_state, req.callback_at)

        with get_session() as session:
            session.execute(text("BEGIN IMMEDIATE"))

            account = session.get(Account, req.account_id)
            if account is None:
                log.error("complete: account %s not found", req.account_id)
                session.execute(text("ROLLBACK"))
                return False

            # Advance state
            account.account_state         = new_state
            account.last_outcome_code     = req.outcome_code
            account.last_interest_score   = req.interest_score
            account.call_count           += 1
            account.last_called_at        = req.ended_at or now
            account.next_call_at          = next_call
            account.callback_requested_at = req.callback_at if new_state == AccountState.callback_requested else account.callback_requested_at
            account.current_call_sid      = None
            account.checked_out_by        = None
            account.checked_out_at        = None
            account.updated_at            = now

            # DNC outcomes permanently flag the row so it can never be checked out again
            if new_state == AccountState.dnc:
                account.do_not_call = True

            # Close the attempt row
            attempt = session.get(CallAttempt, req.attempt_id)
            if attempt:
                attempt.outcome_code     = req.outcome_code
                attempt.interest_score   = req.interest_score
                attempt.summary_text     = req.summary_text
                attempt.ended_at         = req.ended_at or now
                attempt.duration_secs    = req.duration_secs
                attempt.callback_at      = req.callback_at
                attempt.raw_payload_json = req.raw_payload_json
            else:
                log.warning("complete: CallAttempt %s not found — creating ad-hoc", req.attempt_id)
                session.add(CallAttempt(
                    attempt_id       = req.attempt_id,
                    account_id       = req.account_id,
                    agent_id         = req.agent_id,
                    started_at       = req.ended_at or now,
                    ended_at         = req.ended_at or now,
                    duration_secs    = req.duration_secs,
                    outcome_code     = req.outcome_code,
                    interest_score   = req.interest_score,
                    summary_text     = req.summary_text,
                    raw_payload_json = req.raw_payload_json,
                    created_at       = now,
                ))

            # Referral
            if req.referral:
                ref = Referral(
                    referral_id            = req.referral.referral_id or str(uuid.uuid4()),
                    source_account_id      = req.account_id,
                    source_call_attempt_id = req.attempt_id,
                    referred_name          = req.referral.referred_name,
                    referred_phone         = req.referral.referred_phone,
                    referred_account       = req.referral.referred_account,
                    referred_title         = req.referral.referred_title,
                    referred_state         = req.referral.referred_state,
                    notes                  = req.referral.notes,
                    status                 = ReferralStatus.pending,
                    created_at             = now,
                )
                session.add(ref)

        return True

    # ── agent heartbeat ───────────────────────────────────────────────────────

    def register_agent(self, agent_id: str, hostname: Optional[str] = None, pid: Optional[int] = None) -> AgentRead:
        """Register or re-register an orchestrator agent."""
        now = _now()
        with get_session() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                agent = Agent(
                    agent_id      = agent_id,
                    hostname      = hostname,
                    pid           = pid,
                    status        = AgentStatus.idle,
                    registered_at = now,
                    last_heartbeat_at = now,
                )
                session.add(agent)
            else:
                agent.hostname          = hostname or agent.hostname
                agent.pid               = pid or agent.pid
                agent.status            = AgentStatus.idle
                agent.last_heartbeat_at = now
            session.flush()
            return AgentRead.model_validate(agent)

    def heartbeat(
        self,
        agent_id: str,
        status: AgentStatus = AgentStatus.busy,
        calls_today_delta: int = 0,
    ) -> bool:
        """Agent pings this every ~30s to prove it's alive."""
        now = _now()
        with get_session() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return False
            agent.status            = status
            agent.last_heartbeat_at = now
            agent.calls_made_today += calls_today_delta
            agent.calls_made_total += calls_today_delta
        return True

    def stop_agent(self, agent_id: str) -> bool:
        """Mark agent stopped and release any checked-out accounts."""
        now = _now()
        with get_session() as session:
            agent = session.get(Agent, agent_id)
            if agent:
                agent.status            = AgentStatus.stopped
                agent.last_heartbeat_at = now

            # Release any accounts this agent still holds
            session.execute(
                update(Account)
                .where(
                    Account.checked_out_by == agent_id,
                    Account.account_state == AccountState.queued,
                )
                .values(
                    account_state  = AccountState.new,
                    checked_out_by = None,
                    checked_out_at = None,
                    next_call_at   = None,
                    updated_at     = now,
                )
            )
        return True

    # ── stale checkout recovery ───────────────────────────────────────────────

    def release_stale_checkouts(self, older_than_minutes: int = 60) -> int:
        """
        Release accounts stuck in 'queued'/'in_flight' with no heartbeat.

        Called by the orchestrator supervisor thread on startup + every 10min.
        Returns count of released accounts.
        """
        cutoff = _now() - timedelta(minutes=older_than_minutes)
        now    = _now()
        with get_session() as session:
            result = session.execute(
                update(Account)
                .where(
                    Account.account_state.in_([AccountState.queued, AccountState.in_flight]),
                    Account.checked_out_at <= cutoff,
                )
                .values(
                    account_state   = AccountState.new,
                    checked_out_by  = None,
                    checked_out_at  = None,
                    current_call_sid= None,
                    next_call_at    = None,
                    updated_at      = now,
                )
            )
        released = result.rowcount
        if released:
            log.warning("Released %d stale checked-out accounts", released)
        return released

    # ── DNC ───────────────────────────────────────────────────────────────────

    def mark_dnc(self, account_id: str, reason: str = "") -> bool:
        """Permanently mark an account as do-not-call (terminal state)."""
        now = _now()
        with get_session() as session:
            account = session.get(Account, account_id)
            if account is None:
                return False
            account.account_state  = AccountState.dnc
            account.do_not_call    = True
            account.checked_out_by = None
            account.checked_out_at = None
            account.next_call_at   = None
            account.updated_at     = now
            if reason:
                existing = account.metadata_json or "{}"
                try:
                    meta = json.loads(existing)
                except json.JSONDecodeError:
                    meta = {}
                meta["dnc_reason"] = reason
                account.metadata_json = json.dumps(meta)
        return True

    # ── queries ───────────────────────────────────────────────────────────────

    def get_due(self, limit: int = 50, state_filter: Optional[List[str]] = None) -> List[AccountSummary]:
        """Return eligible accounts without exclusively locking them. Use checkout() to claim."""
        now = _now()
        with get_session() as session:
            q = (
                select(Account)
                .where(
                    Account.account_state.in_(list(CHECKABLE_STATES)),
                    (Account.next_call_at.is_(None)) | (Account.next_call_at <= now),
                    Account.checked_out_by.is_(None),
                    Account.do_not_call.is_(False),
                )
                .limit(limit)
            )
            if state_filter:
                q = q.where(Account.state.in_(state_filter))
            rows = session.scalars(q).all()
            return [AccountSummary.model_validate(r) for r in rows]

    def get_stats(self) -> StatsResponse:
        """Count accounts by state. Used by dashboard + Slack report."""
        with get_session() as session:
            rows = session.execute(
                select(Account.account_state, func.count().label("cnt"))
                .group_by(Account.account_state)
            ).all()
        counts = {r.account_state: r.cnt for r in rows}
        total  = sum(counts.values())
        return StatsResponse(
            new                = counts.get(AccountState.new,                0),
            queued             = counts.get(AccountState.queued,             0),
            in_flight          = counts.get(AccountState.in_flight,          0),
            voicemail          = counts.get(AccountState.voicemail,          0),
            no_answer          = counts.get(AccountState.no_answer,          0),
            callback_requested = counts.get(AccountState.callback_requested, 0),
            interested         = counts.get(AccountState.interested,         0),
            not_interested     = counts.get(AccountState.not_interested,     0),
            dnc                = counts.get(AccountState.dnc,                0),
            referral_given     = counts.get(AccountState.referral_given,     0),
            converted          = counts.get(AccountState.converted,          0),
            error              = counts.get(AccountState.error,              0),
            total              = total,
        )

    def get_history(self, account_id: str) -> List[CallAttemptRead]:
        """Full call history for a single account."""
        with get_session() as session:
            rows = session.scalars(
                select(CallAttempt)
                .where(CallAttempt.account_id == account_id)
                .order_by(CallAttempt.started_at)
            ).all()
            return [CallAttemptRead.model_validate(r) for r in rows]


# ── module-level singleton ────────────────────────────────────────────────────

repo = AccountRepository()
