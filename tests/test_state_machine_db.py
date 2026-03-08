"""
tests/test_state_machine_db.py — V2 State Machine DB full test suite.

Tests:
  - state_machine.py       (pure logic, no DB)
  - db_models.py           (SQLAlchemy ORM)
  - db_schemas.py          (Pydantic v2 validation)
  - account_repository.py  (atomic checkout, state transitions, stale release)

All DB tests run against a temp-file SQLite database so the live
campaigns/accounts.db is never touched, and we avoid `:memory:` per-connection
isolation problems.

Run:
    source venv/bin/activate
    python3 -m pytest tests/test_state_machine_db.py -v
"""

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

# ── path setup ────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# MUST point at a temp FILE (not :memory:) before importing db_engine.
# SQLite :memory: creates a fresh empty DB for every new connection,
# so the tables created by init_db() would be invisible to repo sessions.
_TMP_DIR = tempfile.mkdtemp(prefix="voice_caller_tests_")
_TEST_DB  = os.path.join(_TMP_DIR, "test_v2.db")
os.environ["VOICE_CALLER_DB"] = _TEST_DB

from execution.db_engine import Base, engine, get_session, init_db  # noqa: E402
from execution.db_models import (                                     # noqa: E402
    Account,
    AccountState,
    Agent,
    AgentStatus,
    CallAttempt,
    Campaign,
    CampaignStatus,
    OutcomeCode,
    Referral,
    ReferralStatus,
)
from execution.db_schemas import (                                    # noqa: E402
    AccountCreate,
    AccountRead,
    AccountSummary,
    AgentCreate,
    AgentHeartbeat,
    AgentRead,
    CallAttemptComplete,
    CallAttemptCreate,
    CallAttemptRead,
    CampaignCreate,
    CampaignRead,
    CheckoutResult,
    CompleteCallRequest,
    ReferralCreate,
    ReferralRead,
    StatsResponse,
)
from execution.state_machine import (                                 # noqa: E402
    COOLDOWN_DAYS,
    OUTCOME_TO_STATE,
    TERMINAL_STATES,
    TRANSITIONS,
    AccountStateMachine,
    O,
    S,
    sm,
)
from execution.account_repository import (                            # noqa: E402
    CHECKABLE_STATES,
    AccountRepository,
    _next_call_dt,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Create all tables once for the entire test run (temp-file DB)."""
    init_db()
    yield


@pytest.fixture()
def repo():
    """Fresh AccountRepository per test (shares the session-scoped temp DB)."""
    return AccountRepository()


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_phone() -> str:
    """Generate a unique 10-digit US phone number for test isolation."""
    return f"5{uuid.uuid4().int % 10**9:09d}"


def _make_account(
    *,
    name: str = "Test School",
    phone: Optional[str] = None,
    state: str = "SD",
    vertical: str = "K-12",
    account_state: AccountState = AccountState.new,
    next_call_at: Optional[datetime] = None,
    checked_out_by: Optional[str] = None,
    checked_out_at: Optional[datetime] = None,
    do_not_call: bool = False,
) -> Account:
    """Build an Account ORM row (not yet persisted)."""
    now = datetime.now(timezone.utc)
    return Account(
        account_id     = str(uuid.uuid4()),
        account_name   = name,
        phone          = phone or _new_phone(),
        state          = state,
        vertical       = vertical,
        account_state  = account_state,
        next_call_at   = next_call_at,
        checked_out_by = checked_out_by,
        checked_out_at = checked_out_at,
        do_not_call    = do_not_call,
        call_count     = 0,
        created_at     = now,
        updated_at     = now,
    )


def _make_agent(agent_id: str) -> Agent:
    now = datetime.now(timezone.utc)
    return Agent(
        agent_id          = agent_id,
        status            = AgentStatus.idle,
        registered_at     = now,
        last_heartbeat_at = now,
    )


def _insert_account(acct: Account) -> str:
    """Insert account; return account_id (captured before session expires it)."""
    aid = acct.account_id          # UUID is set before session — safe to grab now
    with get_session() as session:
        session.add(acct)
    return aid


def _insert_agent(agent_id: str) -> None:
    with get_session() as session:
        existing = session.get(Agent, agent_id)
        if existing is None:
            session.add(_make_agent(agent_id))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pure state machine logic (no DB)
# ─────────────────────────────────────────────────────────────────────────────


class TestStateMachinePure:

    def test_singleton_available(self):
        assert sm is not None
        assert isinstance(sm, AccountStateMachine)

    # ── transition graph ──────────────────────────────────────────────────────

    @pytest.mark.parametrize("frm,to,expected", [
        (S.NEW,       S.QUEUED,      True),
        (S.QUEUED,    S.IN_FLIGHT,   True),
        (S.IN_FLIGHT, S.VOICEMAIL,   True),
        (S.IN_FLIGHT, S.NO_ANSWER,   True),
        (S.IN_FLIGHT, S.INTERESTED,  True),
        (S.IN_FLIGHT, S.DNC,         True),
        (S.IN_FLIGHT, S.CONVERTED,   True),
        (S.IN_FLIGHT, S.ERROR,       True),
        # terminals must NOT loop back
        (S.CONVERTED, S.NEW,         False),
        (S.CONVERTED, S.QUEUED,      False),
        (S.DNC,       S.NEW,         False),
        (S.DNC,       S.QUEUED,      False),
        (S.DNC,       S.IN_FLIGHT,   False),
        # cooldown states return to new/queued only
        (S.VOICEMAIL, S.NEW,         True),
        (S.VOICEMAIL, S.IN_FLIGHT,   False),
        (S.NO_ANSWER, S.NEW,         True),
        (S.NO_ANSWER, S.IN_FLIGHT,   False),
    ])
    def test_can_transition(self, frm, to, expected):
        assert sm.can_transition(frm, to) is expected

    def test_assert_can_transition_raises_on_illegal(self):
        with pytest.raises(ValueError, match="Illegal state transition"):
            sm.assert_can_transition(S.CONVERTED, S.QUEUED)

    def test_assert_can_transition_ok(self):
        sm.assert_can_transition(S.NEW, S.QUEUED)   # no exception

    # ── outcome → state ───────────────────────────────────────────────────────

    @pytest.mark.parametrize("outcome,expected_state", [
        (O.VOICEMAIL,          S.VOICEMAIL),
        (O.NO_ANSWER,          S.NO_ANSWER),
        (O.HUNG_UP,            S.NO_ANSWER),
        (O.NOT_INTERESTED,     S.NOT_INTERESTED),
        (O.INTERESTED,         S.INTERESTED),
        (O.MEETING_BOOKED,     S.INTERESTED),
        (O.CALLBACK_REQUESTED, S.CALLBACK_REQUESTED),
        (O.REFERRAL_GIVEN,     S.REFERRAL_GIVEN),
        (O.DNC,                S.DNC),
        (O.CONVERTED,          S.CONVERTED),
        (O.ERROR_SWML,         S.ERROR),
        (O.ERROR_CARRIER,      S.ERROR),
        (O.ERROR_TIMEOUT,      S.ERROR),
    ])
    def test_outcome_to_state(self, outcome, expected_state):
        assert sm.outcome_to_state(outcome) == expected_state

    def test_outcome_to_state_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown outcome code"):
            sm.outcome_to_state("not_a_real_code")

    # ── cooldowns ─────────────────────────────────────────────────────────────

    def test_next_call_at_voicemail_2d(self):
        now = datetime.now(timezone.utc)
        t   = sm.next_call_at(S.VOICEMAIL, now=now)
        assert t is not None
        delta_days = (t - now).total_seconds() / 86400
        assert abs(delta_days - 2.0) < 0.01

    def test_next_call_at_no_answer_1d(self):
        now = datetime.now(timezone.utc)
        t   = sm.next_call_at(S.NO_ANSWER, now=now)
        assert t is not None
        delta_hrs = (t - now).total_seconds() / 3600
        assert abs(delta_hrs - 24.0) < 0.1

    def test_next_call_at_not_interested_30d(self):
        now = datetime.now(timezone.utc)
        t   = sm.next_call_at(S.NOT_INTERESTED, now=now)
        assert t is not None
        delta_days = (t - now).total_seconds() / 86400
        assert abs(delta_days - 30.0) < 0.1

    def test_next_call_at_error_1h(self):
        now = datetime.now(timezone.utc)
        t   = sm.next_call_at(S.ERROR, now=now)
        assert t is not None
        delta_hrs = (t - now).total_seconds() / 3600
        assert abs(delta_hrs - 1.0) < 0.01

    def test_next_call_at_terminal_is_none(self):
        for state in (S.INTERESTED, S.DNC, S.CONVERTED, S.REFERRAL_GIVEN):
            assert sm.next_call_at(state) is None

    def test_next_call_at_callback_uses_explicit_dt(self):
        cb = datetime.now(timezone.utc) + timedelta(hours=3)
        result = sm.next_call_at(S.CALLBACK_REQUESTED, callback_at=cb)
        assert result == cb

    def test_next_call_at_callback_without_dt_is_none(self):
        assert sm.next_call_at(S.CALLBACK_REQUESTED) is None

    # ── helpers ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("state,expected", [
        (S.INTERESTED,     True),
        (S.DNC,            True),
        (S.CONVERTED,      True),
        (S.REFERRAL_GIVEN, True),
        (S.NEW,            False),
        (S.QUEUED,         False),
        (S.VOICEMAIL,      False),
        (S.ERROR,          False),
    ])
    def test_is_terminal(self, state, expected):
        assert sm.is_terminal(state) is expected

    @pytest.mark.parametrize("state,expected", [
        (S.NEW,                True),
        (S.VOICEMAIL,          True),
        (S.NO_ANSWER,          True),
        (S.CALLBACK_REQUESTED, True),
        (S.NOT_INTERESTED,     True),
        (S.ERROR,              True),
        (S.QUEUED,             False),
        (S.IN_FLIGHT,          False),
        (S.INTERESTED,         False),
        (S.DNC,                False),
        (S.CONVERTED,          False),
    ])
    def test_is_checkable(self, state, expected):
        assert sm.is_checkable(state) is expected

    def test_full_graph_has_all_states(self):
        g = sm.full_graph()
        assert S.NEW     in g
        assert S.DNC     in g
        assert S.CONVERTED in g

    def test_describe_transition_voicemail(self):
        info = sm.describe_transition(O.VOICEMAIL)
        assert info["new_state"]  == S.VOICEMAIL
        assert info["terminal"]   is False
        assert "2d" in info["next_schedule"]

    def test_describe_transition_dnc_is_terminal(self):
        info = sm.describe_transition(O.DNC)
        assert info["new_state"] == S.DNC
        assert info["terminal"]  is True
        assert "terminal" in info["next_schedule"]

    def test_describe_transition_callback(self):
        info = sm.describe_transition(O.CALLBACK_REQUESTED)
        assert info["new_state"] == S.CALLBACK_REQUESTED
        assert "callback_at" in info["next_schedule"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pydantic schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestPydanticSchemas:

    def test_account_create_phone_stripped(self):
        a = AccountCreate(account_name="Test", phone="605-555-1234", state="SD")
        assert a.phone == "6055551234"

    def test_account_create_phone_parens(self):
        a = AccountCreate(account_name="Test", phone="(605) 555-1234")
        assert a.phone == "6055551234"

    def test_account_create_defaults(self):
        a = AccountCreate(account_name="Test", phone="6055550001")
        assert a.do_not_call is False
        assert a.sfdc_id is None

    def test_call_attempt_complete_valid_interest_score(self):
        now = datetime.now(timezone.utc)
        c = CallAttemptComplete(
            attempt_id="id-1", account_id="a-1",
            outcome_code=OutcomeCode.voicemail,
            interest_score=3, ended_at=now,
        )
        assert c.interest_score == 3

    def test_call_attempt_complete_rejects_score_out_of_range(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(Exception):
            CallAttemptComplete(
                attempt_id="id-2", account_id="a-2",
                outcome_code=OutcomeCode.voicemail,
                interest_score=6, ended_at=now,
            )

    def test_stats_response_defaults_zero(self):
        s = StatsResponse()
        assert s.total == 0
        assert s.new   == 0

    def test_complete_call_request_with_referral(self):
        now = datetime.now(timezone.utc)
        req = CompleteCallRequest(
            account_id="acc-1", attempt_id="att-1", agent_id="ag-1",
            outcome_code=OutcomeCode.referral_given, ended_at=now,
            referral=ReferralCreate(
                referred_name="Jane Doe",
                referred_phone="5555550002",
                referred_account="City of Nowhere",
            ),
        )
        assert req.referral is not None
        assert req.referral.referred_name == "Jane Doe"

    def test_campaign_create_fields(self):
        c = CampaignCreate(campaign_name="K-12 Iowa March", vertical="K-12", state_filter="IA")
        assert c.state_filter == "IA"

    def test_agent_heartbeat_schema(self):
        now = datetime.now(timezone.utc)
        h = AgentHeartbeat(
            agent_id="agent-2", status=AgentStatus.busy,
            last_heartbeat_at=now, calls_made_today=3, calls_made_total=42,
        )
        assert h.agent_id == "agent-2"

    def test_account_summary_orm_compat(self):
        """AccountSummary.model_validate should work with a dict (from_attributes=True)."""
        now = datetime.now(timezone.utc)
        raw = {
            "account_id": str(uuid.uuid4()), "account_name": "X",
            "phone": "6055550001", "state": "SD", "vertical": "K-12",
            "sfdc_id": None, "account_state": AccountState.new,
            "next_call_at": None, "call_count": 0,
        }
        s = AccountSummary(**raw)
        assert s.account_name == "X"


# ─────────────────────────────────────────────────────────────────────────────
# 3. SQLAlchemy ORM — basic CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestORMBasic:

    def test_create_and_read_account(self):
        acct = _make_account(name="ORM School", phone=_new_phone())
        aid  = _insert_account(acct)

        with get_session() as session:
            loaded = session.get(Account, aid)
            assert loaded is not None
            assert loaded.account_name  == "ORM School"
            assert loaded.account_state == AccountState.new

    def test_create_agent(self):
        agent_id = f"orm-agent-{uuid.uuid4().hex[:6]}"
        with get_session() as session:
            session.add(_make_agent(agent_id))

        with get_session() as session:
            loaded = session.get(Agent, agent_id)
            assert loaded is not None
            assert loaded.status == AgentStatus.idle

    def test_call_attempt_linked_to_account(self):
        now  = datetime.now(timezone.utc)
        acct = _make_account(name="ORM School 2", phone=_new_phone())
        aid  = _insert_account(acct)

        att_id = str(uuid.uuid4())
        attempt = CallAttempt(
            attempt_id = att_id, account_id = aid,
            started_at = now, created_at = now,
        )
        with get_session() as session:
            session.add(attempt)

        with get_session() as session:
            loaded = session.get(CallAttempt, att_id)
            assert loaded is not None
            assert loaded.account_id == aid

    def test_unique_phone_name_constraint(self):
        from sqlalchemy.exc import IntegrityError
        phone = _new_phone()
        aid1  = _insert_account(_make_account(name="Dupe School", phone=phone))

        with pytest.raises(IntegrityError):
            _insert_account(_make_account(name="Dupe School", phone=phone))

    def test_do_not_call_default_false(self):
        aid = _insert_account(_make_account(name="DNC Default", phone=_new_phone()))
        with get_session() as session:
            loaded = session.get(Account, aid)
            assert loaded.do_not_call is False

    def test_referral_creation(self):
        now = datetime.now(timezone.utc)
        rid = str(uuid.uuid4())
        ref = Referral(
            referral_id    = rid,
            referred_name  = "Ref Person",
            referred_phone = _new_phone(),
            status         = ReferralStatus.pending,
            created_at     = now,
        )
        with get_session() as session:
            session.add(ref)

        with get_session() as session:
            loaded = session.get(Referral, rid)
            assert loaded.referred_name == "Ref Person"
            assert loaded.status        == ReferralStatus.pending

    def test_campaign_creation(self):
        now = datetime.now(timezone.utc)
        cid = str(uuid.uuid4())
        c   = Campaign(
            campaign_id   = cid,
            campaign_name = "Test Campaign",
            status        = CampaignStatus.draft,
            created_at    = now, updated_at = now,
        )
        with get_session() as session:
            session.add(c)

        with get_session() as session:
            loaded = session.get(Campaign, cid)
            assert loaded.campaign_name == "Test Campaign"
            assert loaded.status        == CampaignStatus.draft


# ─────────────────────────────────────────────────────────────────────────────
# 4. AccountRepository — state machine + atomic checkout
# ─────────────────────────────────────────────────────────────────────────────


class TestAccountRepository:
    """
    All tests use isolated accounts/agents seeded with unique phones/IDs.

    get_session() auto-commits; account_id UUIDs are captured before commit
    to avoid DetachedInstanceError.
    """

    def _seed(
        self, *,
        phone: Optional[str] = None,
        name: Optional[str] = None,
        account_state: AccountState = AccountState.new,
        next_call_at: Optional[datetime] = None,
        checked_out_by: Optional[str] = None,
        checked_out_at: Optional[datetime] = None,
        do_not_call: bool = False,
    ) -> str:
        p = phone or _new_phone()
        n = name or f"Seed {p}"
        acct = _make_account(
            phone=p, name=n,
            account_state=account_state,
            next_call_at=next_call_at,
            checked_out_by=checked_out_by,
            checked_out_at=checked_out_at,
            do_not_call=do_not_call,
        )
        return _insert_account(acct)

    # ── register_agent / heartbeat ────────────────────────────────────────────

    def test_register_agent(self, repo):
        ar = repo.register_agent(f"agent-{uuid.uuid4().hex[:6]}", hostname="localhost", pid=1)
        assert isinstance(ar, AgentRead)
        assert ar.status == AgentStatus.idle.value

    def test_heartbeat_updates_ok(self, repo):
        aid = f"agent-hb-{uuid.uuid4().hex[:6]}"
        repo.register_agent(aid)
        ok = repo.heartbeat(aid, status=AgentStatus.busy)
        assert ok is True

    def test_heartbeat_unknown_agent_false(self, repo):
        ok = repo.heartbeat("ghost-agent-xyz")
        assert ok is False

    # ── checkout ──────────────────────────────────────────────────────────────

    def test_checkout_new_account(self, repo):
        agent_id = f"co-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        aid = self._seed(name=f"Checkout Test {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None
        assert isinstance(result, CheckoutResult)
        # The checked-out account should match the one we seeded
        # (may not if other new accounts exist — just verify structure)
        assert result.account.account_state in (
            AccountState.queued.value, AccountState.queued
        )
        assert result.attempt_id  # a UUID string

    def test_checkout_skips_dnc(self, repo):
        agent_id = f"dnc-co-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        dnc_id = self._seed(
            name=f"DNC {agent_id}",
            account_state=AccountState.dnc,
            do_not_call=True,
        )

        result = repo.checkout(agent_id)
        # If a result is returned, it must NOT be the DNC account
        if result is not None:
            assert result.account.account_id != dnc_id

    def test_checkout_skips_future_next_call_at(self, repo):
        agent_id = f"future-co-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        far_future = datetime.now(timezone.utc) + timedelta(days=99)
        far_id = self._seed(
            account_state=AccountState.voicemail,
            next_call_at=far_future,
        )

        # Only eligible accounts should be checked out
        result = repo.checkout(agent_id)
        if result is not None:
            assert result.account.account_id != far_id

    # ── complete — voicemail cooldown ─────────────────────────────────────────

    def test_complete_voicemail_sets_2d_cooldown(self, repo):
        agent_id = f"vm-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"VM Test {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None, "No account available for checkout"

        now = datetime.now(timezone.utc)
        ok  = repo.complete(CompleteCallRequest(
            account_id=result.account.account_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.voicemail,
            ended_at=now, duration_secs=15,
        ))
        assert ok is True

        with get_session() as session:
            acct = session.get(Account, result.account.account_id)
            assert acct.account_state == AccountState.voicemail
            assert acct.next_call_at is not None
            delta = (
                acct.next_call_at.replace(tzinfo=timezone.utc) - now
            ).total_seconds() / 86400
            assert 1.9 < delta < 2.1, f"Expected ~2d cooldown, got {delta:.3f}d"

    # ── complete — interested (terminal) ─────────────────────────────────────

    def test_complete_interested_terminal(self, repo):
        agent_id = f"int-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"Interested {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None

        now = datetime.now(timezone.utc)
        repo.complete(CompleteCallRequest(
            account_id=result.account.account_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.interested,
            ended_at=now,
        ))

        with get_session() as session:
            acct = session.get(Account, result.account.account_id)
            assert acct.account_state  == AccountState.interested
            assert acct.next_call_at   is None
            assert acct.checked_out_by is None

    # ── complete — DNC (terminal + do_not_call flag) ──────────────────────────

    def test_complete_dnc_sets_flag(self, repo):
        agent_id = f"dnc-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"DNC {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None

        now = datetime.now(timezone.utc)
        repo.complete(CompleteCallRequest(
            account_id=result.account.account_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.dnc, ended_at=now,
        ))

        with get_session() as session:
            acct = session.get(Account, result.account.account_id)
            assert acct.account_state == AccountState.dnc
            assert acct.do_not_call   is True
            assert acct.next_call_at  is None

    # ── complete — error with 1h cooldown ─────────────────────────────────────

    def test_complete_error_1h_cooldown(self, repo):
        agent_id = f"err-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"Error {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None

        now = datetime.now(timezone.utc)
        repo.complete(CompleteCallRequest(
            account_id=result.account.account_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.error_timeout, ended_at=now,
        ))

        with get_session() as session:
            acct = session.get(Account, result.account.account_id)
            assert acct.account_state == AccountState.error
            delta_hrs = (
                acct.next_call_at.replace(tzinfo=timezone.utc) - now
            ).total_seconds() / 3600
            assert 0.9 < delta_hrs < 1.1, f"Expected ~1h cooldown, got {delta_hrs:.3f}h"

    # ── complete — callback_requested uses explicit datetime ──────────────────

    def test_complete_callback_uses_explicit_dt(self, repo):
        agent_id = f"cb-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"Callback {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None

        callback_dt = datetime.now(timezone.utc) + timedelta(hours=6)
        now = datetime.now(timezone.utc)
        repo.complete(CompleteCallRequest(
            account_id=result.account.account_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.callback_requested,
            ended_at=now, callback_at=callback_dt,
        ))

        with get_session() as session:
            acct = session.get(Account, result.account.account_id)
            assert acct.account_state == AccountState.callback_requested
            diff = abs(
                (acct.next_call_at.replace(tzinfo=timezone.utc) - callback_dt).total_seconds()
            )
            assert diff < 2, f"next_call_at drift: {diff}s"

    # ── complete — referral creates Referral row ──────────────────────────────

    def test_complete_referral_creates_row(self, repo):
        agent_id = f"ref-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"Referral Giver {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None
        acct_id = result.account.account_id

        now = datetime.now(timezone.utc)
        repo.complete(CompleteCallRequest(
            account_id=acct_id, attempt_id=result.attempt_id,
            agent_id=agent_id, outcome_code=OutcomeCode.referral_given,
            ended_at=now,
            referral=ReferralCreate(
                source_account_id = acct_id,
                referred_name     = "Jane Smith",
                referred_phone    = _new_phone(),
                referred_account  = "Smith County SD",
                referred_state    = "SD",
            ),
        ))

        with get_session() as session:
            from sqlalchemy import select
            refs = session.scalars(
                select(Referral).where(Referral.source_account_id == acct_id)
            ).all()
            assert len(refs) == 1
            assert refs[0].referred_name == "Jane Smith"
            assert refs[0].status        == ReferralStatus.pending

    # ── mark_dnc direct ───────────────────────────────────────────────────────

    def test_mark_dnc_direct(self, repo):
        aid = self._seed(name=f"Direct DNC {_new_phone()}")
        ok  = repo.mark_dnc(aid, reason="Said never call again")
        assert ok is True

        with get_session() as session:
            acct = session.get(Account, aid)
            assert acct.account_state == AccountState.dnc
            assert acct.do_not_call   is True

    def test_mark_dnc_unknown_returns_false(self, repo):
        assert repo.mark_dnc("non-existent-uuid") is False

    # ── stale checkout release ────────────────────────────────────────────────

    def test_release_stale_checkouts(self, repo):
        # Must insert the agent row first (FK on accounts_v2.checked_out_by)
        stale_agent_id = f"stale-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(stale_agent_id)

        stale_time = datetime.now(timezone.utc) - timedelta(hours=3)
        aid = self._seed(
            account_state  = AccountState.queued,
            checked_out_by = stale_agent_id,
            checked_out_at = stale_time,
        )

        released = repo.release_stale_checkouts(older_than_minutes=60)
        assert released >= 1

        with get_session() as session:
            acct = session.get(Account, aid)
            assert acct.account_state  == AccountState.new
            assert acct.checked_out_by is None

    # ── stop_agent releases held accounts ─────────────────────────────────────

    def test_stop_agent_releases_accounts(self, repo):
        agent_id = f"stop-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        aid = self._seed(
            account_state=AccountState.queued,
            checked_out_by=agent_id,
        )

        ok = repo.stop_agent(agent_id)
        assert ok is True

        with get_session() as session:
            acct = session.get(Account, aid)
            assert acct.account_state  == AccountState.new
            assert acct.checked_out_by is None

    # ── get_stats ─────────────────────────────────────────────────────────────

    def test_get_stats_returns_stats_response(self, repo):
        stats = repo.get_stats()
        assert isinstance(stats, StatsResponse)
        assert stats.total >= 0

    def test_get_stats_total_is_sum_of_parts(self, repo):
        stats = repo.get_stats()
        parts = (
            stats.new + stats.queued + stats.in_flight +
            stats.voicemail + stats.no_answer + stats.callback_requested +
            stats.interested + stats.not_interested + stats.dnc +
            stats.referral_given + stats.converted + stats.error
        )
        assert stats.total == parts

    # ── get_due ───────────────────────────────────────────────────────────────

    def test_get_due_excludes_dnc_accounts(self, repo):
        self._seed(
            account_state=AccountState.dnc,
            do_not_call=True,
        )
        due = repo.get_due(limit=1000)
        for a in due:
            state = a.account_state
            if hasattr(state, "value"):
                state = state.value
            assert state != AccountState.dnc.value

    def test_get_due_excludes_future_next_call_at(self, repo):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        future_id = self._seed(
            account_state=AccountState.voicemail,
            next_call_at=future,
        )
        due = repo.get_due(limit=1000)
        due_ids = {a.account_id for a in due}
        assert future_id not in due_ids

    def test_get_due_excludes_already_checked_out(self, repo):
        agent_id = f"held-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        held_id = self._seed(
            account_state=AccountState.queued,
            checked_out_by=agent_id,
        )
        due = repo.get_due(limit=1000)
        due_ids = {a.account_id for a in due}
        assert held_id not in due_ids

    # ── get_history ───────────────────────────────────────────────────────────

    def test_get_history_returns_call_attempts(self, repo):
        agent_id = f"hist-agent-{uuid.uuid4().hex[:6]}"
        _insert_agent(agent_id)
        self._seed(name=f"History {agent_id}")

        result = repo.checkout(agent_id)
        assert result is not None

        history = repo.get_history(result.account.account_id)
        assert isinstance(history, list)
        assert len(history) >= 1
        assert all(isinstance(a, CallAttemptRead) for a in history)

    def test_get_history_empty_for_unknown_account(self, repo):
        history = repo.get_history(str(uuid.uuid4()))
        assert history == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Migration script — idempotency + seed-agents
# ─────────────────────────────────────────────────────────────────────────────


class TestMigration:

    def test_migrate_dry_run_exits_zero(self, tmp_path):
        import subprocess
        db = str(tmp_path / "dry.db")
        r  = subprocess.run(
            ["python3", "execution/migrate_v2.py", "--dry-run", "--db", db],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr + r.stdout

    def test_migrate_idempotent_on_fresh_db(self, tmp_path):
        import subprocess
        db = str(tmp_path / "idempotent.db")
        for _ in range(2):
            r = subprocess.run(
                ["python3", "execution/migrate_v2.py", "--db", db, "--no-backup"],
                cwd=ROOT, capture_output=True, text=True,
            )
            assert r.returncode == 0, r.stderr + r.stdout

        import sqlite3
        conn   = sqlite3.connect(db)
        tables = {t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"accounts_v2", "call_attempts", "agents", "referrals",
                "campaigns", "migration_log"}.issubset(tables)
        conn.close()

    def test_migrate_creates_all_indexes(self, tmp_path):
        import subprocess, sqlite3
        db = str(tmp_path / "idx.db")
        subprocess.run(
            ["python3", "execution/migrate_v2.py", "--db", db, "--no-backup"],
            cwd=ROOT, capture_output=True, check=True,
        )
        conn    = sqlite3.connect(db)
        indexes = {r[1] for r in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        assert "ix_accounts_v2_schedule"  in indexes
        assert "ix_accounts_v2_state"     in indexes
        assert "uq_accounts_v2_phone_name" in indexes
        conn.close()

    def test_migrate_seed_agents(self, tmp_path):
        import subprocess, sqlite3
        db = str(tmp_path / "seed.db")
        subprocess.run(
            [
                "python3", "execution/migrate_v2.py",
                "--db", db, "--no-backup",
                "--seed-agents", "agent-1,agent-2,agent-3",
            ],
            cwd=ROOT, capture_output=True, check=True,
        )
        conn    = sqlite3.connect(db)
        agents  = [r[0] for r in conn.execute("SELECT agent_id FROM agents").fetchall()]
        assert "agent-1" in agents
        assert "agent-2" in agents
        assert "agent-3" in agents
        conn.close()
