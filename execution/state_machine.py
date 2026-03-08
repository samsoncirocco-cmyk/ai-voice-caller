"""
state_machine.py — Pure state transition logic for the Account state machine.

No DB imports.  Import this anywhere to validate transitions or compute cooldowns
without pulling in SQLAlchemy.

Usage:
    from execution.state_machine import AccountStateMachine, OUTCOME_TO_STATE, COOLDOWN

    sm = AccountStateMachine()
    sm.assert_can_transition("new", "queued")           # OK
    sm.assert_can_transition("converted", "queued")     # raises ValueError
    new_state = sm.outcome_to_state("voicemail")        # "voicemail"
    next_dt   = sm.next_call_at("voicemail")            # datetime 2 days from now
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Set


# ── state definitions ─────────────────────────────────────────────────────────

class S:
    """String constants for all states (avoids importing the SQLAlchemy enum)."""
    NEW                = "new"
    QUEUED             = "queued"
    IN_FLIGHT          = "in_flight"
    VOICEMAIL          = "voicemail"
    NO_ANSWER          = "no_answer"
    CALLBACK_REQUESTED = "callback_requested"
    NOT_INTERESTED     = "not_interested"
    ERROR              = "error"
    INTERESTED         = "interested"
    DNC                = "dnc"
    REFERRAL_GIVEN     = "referral_given"
    CONVERTED          = "converted"


ALL_STATES: Set[str] = {
    S.NEW, S.QUEUED, S.IN_FLIGHT, S.VOICEMAIL, S.NO_ANSWER,
    S.CALLBACK_REQUESTED, S.NOT_INTERESTED, S.ERROR,
    S.INTERESTED, S.DNC, S.REFERRAL_GIVEN, S.CONVERTED,
}

TERMINAL_STATES: Set[str] = {
    S.INTERESTED, S.DNC, S.REFERRAL_GIVEN, S.CONVERTED,
}

CHECKABLE_STATES: Set[str] = {
    S.NEW, S.VOICEMAIL, S.NO_ANSWER, S.CALLBACK_REQUESTED, S.NOT_INTERESTED, S.ERROR,
}


# ── outcome codes ─────────────────────────────────────────────────────────────

class O:
    """Outcome code constants."""
    VOICEMAIL          = "voicemail"
    NO_ANSWER          = "no_answer"
    HUNG_UP            = "hung_up"
    NOT_INTERESTED     = "not_interested"
    INTERESTED         = "interested"
    MEETING_BOOKED     = "meeting_booked"
    CALLBACK_REQUESTED = "callback_requested"
    REFERRAL_GIVEN     = "referral_given"
    DNC                = "dnc"
    CONVERTED          = "converted"
    ERROR_SWML         = "error_swml"
    ERROR_CARRIER      = "error_carrier"
    ERROR_TIMEOUT      = "error_timeout"


# ── transition graph ──────────────────────────────────────────────────────────
# { from_state: { to_state, ... } }

TRANSITIONS: Dict[str, Set[str]] = {
    S.NEW:                {S.QUEUED},
    S.QUEUED:             {S.IN_FLIGHT, S.NEW},      # NEW = release stale
    S.IN_FLIGHT:          {
        S.VOICEMAIL, S.NO_ANSWER, S.CALLBACK_REQUESTED,
        S.INTERESTED, S.NOT_INTERESTED, S.DNC,
        S.REFERRAL_GIVEN, S.CONVERTED, S.ERROR,
    },
    S.VOICEMAIL:          {S.NEW, S.QUEUED},          # after cooldown
    S.NO_ANSWER:          {S.NEW, S.QUEUED},
    S.CALLBACK_REQUESTED: {S.NEW, S.QUEUED, S.IN_FLIGHT},
    S.NOT_INTERESTED:     {S.NEW, S.QUEUED},
    S.ERROR:              {S.NEW, S.QUEUED},
    # Terminals can be overridden by explicit admin action only:
    S.INTERESTED:         {S.CONVERTED, S.DNC},
    S.DNC:                set(),                      # permanent — never transitions
    S.REFERRAL_GIVEN:     {S.CONVERTED},
    S.CONVERTED:          set(),                      # permanent
}

# ── outcome → state mapping ───────────────────────────────────────────────────

OUTCOME_TO_STATE: Dict[str, str] = {
    O.VOICEMAIL:          S.VOICEMAIL,
    O.NO_ANSWER:          S.NO_ANSWER,
    O.HUNG_UP:            S.NO_ANSWER,
    O.NOT_INTERESTED:     S.NOT_INTERESTED,
    O.INTERESTED:         S.INTERESTED,
    O.MEETING_BOOKED:     S.INTERESTED,
    O.CALLBACK_REQUESTED: S.CALLBACK_REQUESTED,
    O.REFERRAL_GIVEN:     S.REFERRAL_GIVEN,
    O.DNC:                S.DNC,
    O.CONVERTED:          S.CONVERTED,
    O.ERROR_SWML:         S.ERROR,
    O.ERROR_CARRIER:      S.ERROR,
    O.ERROR_TIMEOUT:      S.ERROR,
}

# ── cooldown rules ────────────────────────────────────────────────────────────
# state → days until next_call_at (None = never re-queue automatically)

COOLDOWN_DAYS: Dict[str, Optional[float]] = {
    S.VOICEMAIL:          2.0,
    S.NO_ANSWER:          1.0,
    S.NOT_INTERESTED:     30.0,
    S.ERROR:              1.0 / 24.0,   # 1 hour
    S.CALLBACK_REQUESTED: None,          # use explicit callback_at instead
    S.INTERESTED:         None,
    S.DNC:                None,
    S.REFERRAL_GIVEN:     None,
    S.CONVERTED:          None,
}


# ── class ─────────────────────────────────────────────────────────────────────

class AccountStateMachine:
    """
    Pure-logic state machine validator.

    No side effects — just validation and time computation.
    """

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return True if the transition is allowed."""
        return to_state in TRANSITIONS.get(from_state, set())

    def assert_can_transition(self, from_state: str, to_state: str) -> None:
        """Raise ValueError if the transition is not allowed."""
        if not self.can_transition(from_state, to_state):
            valid = ", ".join(sorted(TRANSITIONS.get(from_state, set()))) or "(none)"
            raise ValueError(
                f"Illegal state transition: {from_state!r} → {to_state!r}. "
                f"Valid targets from {from_state!r}: [{valid}]"
            )

    def outcome_to_state(self, outcome_code: str) -> str:
        """Map an outcome code to the resulting account state."""
        if outcome_code not in OUTCOME_TO_STATE:
            raise ValueError(
                f"Unknown outcome code: {outcome_code!r}. "
                f"Valid: {sorted(OUTCOME_TO_STATE)}"
            )
        return OUTCOME_TO_STATE[outcome_code]

    def next_call_at(
        self,
        state: str,
        callback_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """
        Compute next_call_at for the given post-outcome state.

        Returns None for terminal states or callback_requested without explicit time.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if state == S.CALLBACK_REQUESTED and callback_at is not None:
            return callback_at

        days = COOLDOWN_DAYS.get(state)
        if days is None:
            return None
        return now + timedelta(days=days)

    def is_terminal(self, state: str) -> bool:
        return state in TERMINAL_STATES

    def is_checkable(self, state: str) -> bool:
        return state in CHECKABLE_STATES

    def describe_transition(self, outcome_code: str) -> dict:
        """Return a human-readable summary of what happens for a given outcome code."""
        state    = self.outcome_to_state(outcome_code)
        cooldown = COOLDOWN_DAYS.get(state)
        terminal = self.is_terminal(state)

        if terminal:
            schedule = "never (terminal state — human follow-up required)"
        elif state == S.CALLBACK_REQUESTED:
            schedule = "at explicitly provided callback_at datetime"
        elif cooldown:
            hrs = cooldown * 24
            schedule = f"in {hrs:.0f}h" if hrs < 24 else f"in {cooldown:.0f}d"
        else:
            schedule = "immediately"

        return {
            "outcome_code":  outcome_code,
            "new_state":     state,
            "terminal":      terminal,
            "next_schedule": schedule,
        }

    def full_graph(self) -> dict:
        """Return the full transition graph as a plain dict (for documentation)."""
        return {k: sorted(v) for k, v in TRANSITIONS.items()}


# ── module-level singleton ────────────────────────────────────────────────────

sm = AccountStateMachine()


# ── CLI diagnostics ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== State Machine: Transition Graph ===")
    for state, targets in sm.full_graph().items():
        print(f"  {state:22} → {targets}")

    print("\n=== Outcome Codes → State + Schedule ===")
    for code in sorted(OUTCOME_TO_STATE):
        info = sm.describe_transition(code)
        print(f"  {code:25} → {info['new_state']:22} ({info['next_schedule']})")

    print("\n=== Validation examples ===")
    tests = [
        ("new",       "queued",    True),
        ("queued",    "in_flight", True),
        ("in_flight", "voicemail", True),
        ("converted", "queued",    False),
        ("dnc",       "new",       False),
    ]
    for frm, to, expected in tests:
        result = sm.can_transition(frm, to)
        mark   = "✓" if result == expected else "✗"
        print(f"  {mark} {frm} → {to}: {result}")
