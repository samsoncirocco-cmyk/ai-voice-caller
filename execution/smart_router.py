#!/usr/bin/env python3
"""
smart_router.py — Intelligent call router for the AI Voice Caller.

Replaces the simple account_db.checkout() with a brain that decides:
  • WHICH account to call next (vertical + time-of-day + state load-balance)
  • WHICH prompt to use (vertical match → performance optimized)
  • WHICH voice to use (persona-aware)

Public API
──────────
    from smart_router import SmartRouter

    router = SmartRouter()
    result = router.get_next_call("agent-1")
    # → {
    #     "account":     {...},        # full account dict (same shape as account_db.checkout)
    #     "prompt_file": "prompts/paul.txt",
    #     "voice":       "openai.onyx",
    #     "vertical":    "k12",
    #     "reason":      "K-12 school → paul.txt (answer_rate 40% vs 20%)",
    #   }
    # → None if no callable accounts right now

Routing layers (applied in order)
──────────────────────────────────
  1. Time-of-day gate:   schools → 8-10am or 1-3pm
                         government → 9-11am
                         NEVER call 12-1pm (lunch block)
  2. State load-balancer: if ≥3 calls in-flight for a state, prefer others
  3. Vertical matcher:   decide prompt_file + voice from account type/name
  4. Performance tuner:  if performance_stats.json has data, pick the
                         variant with the highest answer_rate for this vertical
"""

import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

# ── path setup ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from account_db import AccountDB  # noqa: E402

# ── optional performance tracker integration ───────────────────────────────────
# PerformanceTracker writes richer outcome data (answered/interested/voicemail/etc.)
# SmartRouter's built-in stats only track answered/calls per prompt.
# We consult the tracker for get_best_prompt() when its data is ready.
try:
    from performance_tracker import PerformanceTracker as _PerformanceTracker
    _perf_tracker = _PerformanceTracker()
except Exception:
    _perf_tracker = None  # type: ignore

# ── logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────
PERFORMANCE_STATS_FILE = ROOT / "campaigns" / "performance_stats.json"
PROMPTS_DIR = ROOT / "prompts"

# ── voice personas ────────────────────────────────────────────────────────────
# paul.txt    → "Paul"  persona — authority / compliance angle (K-12, government)
# cold_outreach.txt → "Alex" persona — cold open, qualify fast

VOICE_PAUL  = "openai.onyx"    # deep, authoritative — matches Paul's persona
VOICE_ALEX  = "openai.shimmer" # warm but efficient — matches Alex's persona

# ── prompt paths ──────────────────────────────────────────────────────────────
PROMPT_PAUL  = "prompts/paul.txt"
PROMPT_COLD  = "prompts/cold_outreach.txt"
PROMPT_K12   = "prompts/k12.txt"  # use if present, otherwise fall back to paul.txt

# ── vertical detection patterns ───────────────────────────────────────────────
K12_PATTERNS = [
    "school", "district", "school district", "usd", "k-12", "k12",
    "elementary", "high school", "middle school", "community school",
    "unified school", "public school", "charter school", "isd", "csd",
    "board of education", "dept of education",
]

MUNICIPAL_PATTERNS = [
    "municipal", "county", "city of", "city ", " city", "town of",
    "township", "village", "borough", "metro", "municipality",
    "government", "dept of", "department of", "sheriff", "police",
    "fire dept", "fire department", "utility", "utilities", "water district",
    "sanitation", "public works",
]

HIGHER_ED_PATTERNS = [
    "university", "college", "community college", "state university",
    "university of", "polytechnic", "technical college", "vo-tech",
    "vocational", " cc ", "junior college",
]

# Time windows — MST / America/Phoenix (no DST)
CALL_TZ = "America/Phoenix"

# Time-of-day windows (hour, minute) tuples → (start_inclusive, end_exclusive)
WINDOW_SCHOOLS = [
    ((8, 0),  (10, 0)),   # 8:00–10:00am
    ((13, 0), (15, 0)),   # 1:00–3:00pm
]
WINDOW_GOVERNMENT = [
    ((9, 0),  (11, 0)),   # 9:00–11:00am
]
LUNCH_BLOCK = ((12, 0), (13, 0))  # 12:00–1:00pm — never call

# State load balance threshold
MAX_IN_FLIGHT_PER_STATE = 3

# ── default performance stats seed ───────────────────────────────────────────
DEFAULT_PERF_STATS: Dict = {
    "k12": {
        "prompts/paul.txt":          {"calls": 0, "answered": 0},
        "prompts/k12.txt":           {"calls": 0, "answered": 0},
        "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
    },
    "government": {
        "prompts/paul.txt":          {"calls": 0, "answered": 0},
        "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
    },
    "higher_ed": {
        "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
        "prompts/paul.txt":          {"calls": 0, "answered": 0},
    },
    "other": {
        "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
        "prompts/paul.txt":          {"calls": 0, "answered": 0},
    },
}

# Minimum calls before we trust the data (avoid tiny-sample bias)
MIN_CALLS_FOR_PERF_ROUTING = 10


# ─────────────────────────────────────────────────────────────────────────────
# SmartRouter
# ─────────────────────────────────────────────────────────────────────────────

class SmartRouter:
    """
    Brain that picks the next account + prompt + voice for each agent.

    Thread-safe — multiple orchestrator threads can call get_next_call()
    simultaneously.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        stats_file: Optional[Path] = None,
        bypass_time_windows: bool = False,
    ):
        self.db = AccountDB(db_path=db_path)
        self.stats_file = stats_file or PERFORMANCE_STATS_FILE
        self.bypass_time_windows = bypass_time_windows

        # In-flight state tracker: state_abbrev → set of account_ids
        self._lock = threading.Lock()
        self._in_flight: Dict[str, set] = {}  # e.g. {"IA": {"uuid1", "uuid2"}}

        self._ensure_stats_file()

    # ─────────────────────────── public API ──────────────────────────────────

    def get_next_call(self, agent_id: str) -> Optional[Dict]:
        """
        Return the best available account + routing decision for agent_id.

        Returns dict with keys:
          account, prompt_file, voice, vertical, reason
        OR None if nothing is callable right now.
        """
        now = self._now()
        perf = self._load_stats()

        # Snapshot in-flight counts per state
        with self._lock:
            in_flight_counts = {
                state: len(ids) for state, ids in self._in_flight.items()
            }

        # Get ALL candidates (up to 50 due accounts)
        candidates = self.db.get_due(limit=50)
        if not candidates:
            logger.debug("[SmartRouter] No due accounts.")
            return None

        # Score and filter each candidate
        best: Optional[Dict] = None
        best_score: float = -1.0
        best_routing: Dict = {}

        for account in candidates:
            vertical = self._classify_vertical(account)
            prompt_file, voice = self._select_prompt_and_voice(vertical, perf)

            # Time-of-day gate
            if not self.bypass_time_windows:
                if not self._is_callable_now(vertical, now):
                    logger.debug(
                        "[SmartRouter] Skipping %s — outside time window for %s",
                        account.get("account_name"), vertical,
                    )
                    continue

            # State load-balance score penalty
            state = (account.get("state") or "").upper()
            in_flight_for_state = in_flight_counts.get(state, 0)

            if in_flight_for_state >= MAX_IN_FLIGHT_PER_STATE:
                # Soft skip — only block if there's another state available
                # We'll use a score penalty instead of a hard skip so the
                # system degrades gracefully when all states are saturated.
                state_penalty = 0.3
            else:
                state_penalty = 1.0

            # Base priority from DB ordering (new=4, no_answer=3, voicemail=2, not_interested=1)
            status_scores = {
                "new": 4, "no_answer": 3, "voicemail": 2, "not_interested": 1
            }
            base = status_scores.get(account.get("call_status", "new"), 1)

            score = base * state_penalty

            if score > best_score:
                best_score = score
                best = account
                best_routing = {
                    "prompt_file": prompt_file,
                    "voice": voice,
                    "vertical": vertical,
                    "in_flight_for_state": in_flight_for_state,
                }

        if best is None:
            logger.info("[SmartRouter] All candidates filtered by time windows.")
            return None

        # Atomically check out the winner
        account_id = best["account_id"]
        checked_out = self._checkout_specific(agent_id, account_id)
        if not checked_out:
            # Race condition — another agent grabbed it; try recursively once
            logger.debug("[SmartRouter] Race condition on %s, retrying.", account_id)
            return self.get_next_call(agent_id)

        # Track in-flight
        state = (best.get("state") or "").upper()
        with self._lock:
            self._in_flight.setdefault(state, set()).add(account_id)

        reason = self._build_reason(
            best, best_routing["vertical"], best_routing["prompt_file"],
            best_routing["in_flight_for_state"], perf
        )

        logger.info(
            "[SmartRouter] agent=%s → %s | prompt=%s | voice=%s | reason=%s",
            agent_id,
            best.get("account_name"),
            best_routing["prompt_file"],
            best_routing["voice"],
            reason,
        )

        return {
            "account":     checked_out,
            "prompt_file": best_routing["prompt_file"],
            "voice":       best_routing["voice"],
            "vertical":    best_routing["vertical"],
            "reason":      reason,
        }

    def complete_call(
        self,
        account_id: str,
        outcome: str,
        notes: str = "",
        answered: bool = False,
        referral_source: Optional[str] = None,
    ) -> bool:
        """
        Mark a call complete + update performance stats.

        answered=True means the human picked up (even if call was short).
        """
        # Remove from in-flight
        with self._lock:
            for state_ids in self._in_flight.values():
                state_ids.discard(account_id)

        # Get account for stats before completing
        account = self.db.get_by_id(account_id)

        # Complete in DB
        result = self.db.complete(
            account_id, outcome, notes, referral_source=referral_source
        )

        # Update performance stats
        if account:
            vertical = self._classify_vertical(account)
            perf = self._load_stats()
            prompt_key = self._last_prompt_for_account(account)
            if prompt_key and vertical in perf:
                variant = perf[vertical].setdefault(
                    prompt_key, {"calls": 0, "answered": 0}
                )
                variant["calls"] += 1
                if answered or outcome in ("interested", "referral_given"):
                    variant["answered"] += 1
                self._save_stats(perf)

        return result

    def get_in_flight_counts(self) -> Dict[str, int]:
        """Return current in-flight call counts per state."""
        with self._lock:
            return {s: len(ids) for s, ids in self._in_flight.items()}

    def is_callable_now(self, vertical: str) -> bool:
        """Public wrapper for time-window check (useful for orchestrator)."""
        return self._is_callable_now(vertical, self._now())

    # ─────────────────────────── vertical classification ─────────────────────

    def _classify_vertical(self, account: Dict) -> str:
        """
        Classify account into one of: k12, government, higher_ed, other.

        Checks account_type field first, then account_name patterns.
        """
        account_type = (account.get("account_type") or account.get("vertical") or "").lower()
        account_name = (account.get("account_name") or "").lower()
        haystack = f"{account_type} {account_name}".strip()

        if self._matches(haystack, K12_PATTERNS):
            return "k12"
        if self._matches(haystack, HIGHER_ED_PATTERNS):
            return "higher_ed"
        if self._matches(haystack, MUNICIPAL_PATTERNS):
            return "government"

        # Fallback: check account_type field explicitly
        if "k-12" in account_type or "k12" in account_type or "education" in account_type:
            if not self._matches(haystack, HIGHER_ED_PATTERNS):
                return "k12"
        if "government" in account_type or "municipal" in account_type:
            return "government"

        return "other"

    @staticmethod
    def _matches(text: str, patterns: List[str]) -> bool:
        return any(p in text for p in patterns)

    # ─────────────────────────── prompt + voice selection ────────────────────

    def _select_prompt_and_voice(
        self, vertical: str, perf: Dict
    ) -> Tuple[str, str]:
        """
        Return (prompt_file, voice) for a vertical.

        Vertical → default mapping (policy layer):
          k12      → paul.txt  + VOICE_PAUL   (authority/compliance angle)
          government → paul.txt + VOICE_PAUL
          higher_ed  → cold_outreach.txt + VOICE_ALEX
          other      → cold_outreach.txt + VOICE_ALEX

        Then performance layer overrides the prompt if we have enough data
        and a clear winner.
        """
        # Policy defaults
        defaults = {
            "k12":        (self._resolve_k12_prompt(), VOICE_PAUL),
            "government": (PROMPT_PAUL,  VOICE_PAUL),
            "higher_ed":  (PROMPT_COLD,  VOICE_ALEX),
            "other":      (PROMPT_COLD,  VOICE_ALEX),
        }
        default_prompt, default_voice = defaults.get(vertical, (PROMPT_COLD, VOICE_ALEX))

        # Performance override — consult PerformanceTracker (richer data) first,
        # then fall back to the built-in campaigns/performance_stats.json signal.
        best_prompt = None
        if _perf_tracker is not None:
            try:
                best_prompt = _perf_tracker.get_best_prompt(vertical)
            except Exception:
                pass
        if best_prompt is None:
            best_prompt = self._best_prompt_by_perf(vertical, perf)
        if best_prompt:
            chosen_prompt = best_prompt
            # Voice follows the prompt persona:
            # paul.txt + k12.txt both use the "Paul" persona → VOICE_PAUL
            _is_paul_persona = "paul" in best_prompt or "k12" in best_prompt
            voice = VOICE_PAUL if _is_paul_persona else VOICE_ALEX
        else:
            chosen_prompt = default_prompt
            voice = default_voice

        return chosen_prompt, voice

    def _resolve_k12_prompt(self) -> str:
        """Use k12.txt if it exists, otherwise paul.txt."""
        k12_path = ROOT / PROMPT_K12
        if k12_path.exists():
            return PROMPT_K12
        return PROMPT_PAUL

    def _best_prompt_by_perf(self, vertical: str, perf: Dict) -> Optional[str]:
        """
        Return the prompt with the highest answer_rate for this vertical,
        but only if it has enough call volume to be statistically meaningful.

        Returns None if no variant beats the policy default with confidence.
        """
        variants = perf.get(vertical, {})
        if not variants:
            return None

        best_prompt = None
        best_rate = -1.0

        for prompt_key, stats in variants.items():
            calls = stats.get("calls", 0)
            answered = stats.get("answered", 0)

            if calls < MIN_CALLS_FOR_PERF_ROUTING:
                continue  # Not enough data

            rate = answered / calls
            if rate > best_rate:
                best_rate = rate
                best_prompt = prompt_key

        return best_prompt  # None if no variant has enough data

    # ─────────────────────────── time-of-day logic ───────────────────────────

    def _is_callable_now(self, vertical: str, now: datetime) -> bool:
        """
        Return True if it's an appropriate time to call this vertical.

        Rules:
          - NEVER call during lunch (12–1pm)
          - k12: only 8–10am or 1–3pm
          - government: only 9–11am
          - other: any business hour (8am–6pm, M–F)
        """
        # Weekends: no calls
        if now.weekday() >= 5:
            return False

        hour = now.hour
        minute = now.minute

        # Lunch block applies to ALL verticals
        lunch_start, lunch_end = LUNCH_BLOCK
        if self._in_window(hour, minute, lunch_start, lunch_end):
            return False

        if vertical == "k12":
            return any(
                self._in_window(hour, minute, start, end)
                for start, end in WINDOW_SCHOOLS
            )

        if vertical == "government":
            return any(
                self._in_window(hour, minute, start, end)
                for start, end in WINDOW_GOVERNMENT
            )

        # higher_ed and other: standard business hours 8am–6pm
        return 8 <= hour < 18

    @staticmethod
    def _in_window(
        hour: int, minute: int,
        start: Tuple[int, int], end: Tuple[int, int]
    ) -> bool:
        """Check if (hour, minute) is within [start, end)."""
        t = hour * 60 + minute
        s = start[0] * 60 + start[1]
        e = end[0] * 60 + end[1]
        return s <= t < e

    # ─────────────────────────── DB helpers ──────────────────────────────────

    def _checkout_specific(self, agent_id: str, account_id: str) -> Optional[Dict]:
        """
        Attempt to check out a specific account_id.
        Returns the account dict if successful, None if already taken.
        """
        import sqlite3
        from account_db import _now_utc

        db_path = str(self.db.db_path)
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM accounts
                WHERE account_id = ?
                  AND call_status IN ('new', 'voicemail', 'no_answer', 'not_interested')
                  AND agent_id IS NULL
                """,
                (account_id,)
            ).fetchone()

            if row is None:
                conn.execute("ROLLBACK")
                return None

            conn.execute(
                """
                UPDATE accounts
                SET agent_id = ?, call_status = 'queued'
                WHERE account_id = ?
                """,
                (agent_id, account_id)
            )
            updated = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            conn.execute("COMMIT")
            return dict(updated) if updated else None
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    # ─────────────────────────── performance stats ───────────────────────────

    def _ensure_stats_file(self) -> None:
        """Create default performance_stats.json if it doesn't exist."""
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.stats_file.exists():
            self._save_stats(DEFAULT_PERF_STATS)
            logger.info("[SmartRouter] Created default performance_stats.json at %s", self.stats_file)

    def _load_stats(self) -> Dict:
        try:
            with open(self.stats_file) as f:
                data = json.load(f)
            # Merge in any missing keys from defaults
            for vertical, variants in DEFAULT_PERF_STATS.items():
                data.setdefault(vertical, {})
                for prompt_key, seed in variants.items():
                    data[vertical].setdefault(prompt_key, dict(seed))
            return data
        except Exception as exc:
            logger.warning("[SmartRouter] Could not load stats: %s — using defaults", exc)
            return dict(DEFAULT_PERF_STATS)

    def _save_stats(self, stats: Dict) -> None:
        try:
            with open(self.stats_file, "w") as f:
                json.dump(stats, f, indent=2)
        except Exception as exc:
            logger.warning("[SmartRouter] Could not save stats: %s", exc)

    @staticmethod
    def _last_prompt_for_account(account: Dict) -> Optional[str]:
        """
        Try to infer which prompt was last used for this account.
        Falls back to outcome_notes if we embedded the prompt path there.
        (orchestrator.py should pass this via complete_call)
        """
        notes = account.get("outcome_notes") or ""
        for candidate in [PROMPT_PAUL, PROMPT_COLD, PROMPT_K12]:
            if candidate in notes:
                return candidate
        return None

    # ─────────────────────────── human-readable reason ───────────────────────

    def _build_reason(
        self,
        account: Dict,
        vertical: str,
        prompt_file: str,
        in_flight_for_state: int,
        perf: Dict,
    ) -> str:
        parts = [f"vertical={vertical}"]

        # Performance context
        variants = perf.get(vertical, {})
        variant_stats = variants.get(prompt_file, {})
        calls = variant_stats.get("calls", 0)
        answered = variant_stats.get("answered", 0)

        if calls >= MIN_CALLS_FOR_PERF_ROUTING:
            rate = answered / calls
            parts.append(f"answer_rate={rate:.0%} over {calls} calls")
        else:
            parts.append(f"default policy (only {calls} calls, need {MIN_CALLS_FOR_PERF_ROUTING})")

        # State load context
        state = (account.get("state") or "").upper()
        if in_flight_for_state >= MAX_IN_FLIGHT_PER_STATE:
            parts.append(f"⚠️  {state} saturated ({in_flight_for_state} in-flight)")
        elif state:
            parts.append(f"{state} in-flight={in_flight_for_state}")

        return " | ".join(parts)

    # ─────────────────────────── time helper ─────────────────────────────────

    @staticmethod
    def _now() -> datetime:
        if ZoneInfo:
            return datetime.now(ZoneInfo(CALL_TZ))
        # Fallback: Arizona is UTC-7 year-round (no DST)
        return datetime.now(timezone(timedelta(hours=-7)))


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator integration shim
# ─────────────────────────────────────────────────────────────────────────────

def patch_orchestrator(args, stop_event) -> "SmartRouter":
    """
    Return a SmartRouter instance configured from orchestrator args.
    Drop-in replacement for the db.checkout() pattern in _agent_loop().

    Usage in orchestrator.py:
        from smart_router import patch_orchestrator
        router = patch_orchestrator(args, stop_event)
        # then replace:
        #   account = db.checkout(agent_id)
        # with:
        #   result = router.get_next_call(agent_id)
        #   if result: account, prompt_path, voice = result["account"], result["prompt_file"], result["voice"]
    """
    return SmartRouter(
        db_path=getattr(args, "db", None),
        bypass_time_windows=getattr(args, "bypass_time_windows", False),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI — standalone diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def _cli_main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="SmartRouter diagnostics — test routing decisions without placing calls"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_next = sub.add_parser("next", help="Show what get_next_call() would return")
    p_next.add_argument("--agent", default="agent-1")
    p_next.add_argument("--db", default=None)
    p_next.add_argument("--bypass-time", action="store_true", help="Ignore time windows")

    p_stats = sub.add_parser("stats", help="Show performance stats")

    p_classify = sub.add_parser("classify", help="Classify an account name")
    p_classify.add_argument("name", help="Account name to classify")

    p_seed = sub.add_parser("seed-stats", help="Reset performance_stats.json to defaults")

    p_time = sub.add_parser("time-check", help="Check current time windows")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "next":
        router = SmartRouter(
            db_path=args.db,
            bypass_time_windows=args.bypass_time,
        )
        result = router.get_next_call(args.agent)
        if result:
            acct = result["account"]
            print(f"\n{'═'*60}")
            print(f"  Account:  {acct.get('account_name')} ({acct.get('phone')})")
            print(f"  State:    {acct.get('state')}")
            print(f"  Vertical: {result['vertical']}")
            print(f"  Prompt:   {result['prompt_file']}")
            print(f"  Voice:    {result['voice']}")
            print(f"  Reason:   {result['reason']}")
            print(f"{'═'*60}")
            # Release so we don't corrupt the DB
            router.db.complete(acct["account_id"], "no_answer", "diagnostic dry-run")
        else:
            print("No callable accounts right now.")

    elif args.cmd == "stats":
        router = SmartRouter()
        perf = router._load_stats()
        print(json.dumps(perf, indent=2))

    elif args.cmd == "classify":
        router = SmartRouter()
        fake_account = {"account_name": args.name, "account_type": ""}
        vertical = router._classify_vertical(fake_account)
        prompt, voice = router._select_prompt_and_voice(vertical, router._load_stats())
        print(f"Name:     {args.name}")
        print(f"Vertical: {vertical}")
        print(f"Prompt:   {prompt}")
        print(f"Voice:    {voice}")

    elif args.cmd == "seed-stats":
        router = SmartRouter()
        router._save_stats(DEFAULT_PERF_STATS)
        print(f"Seeded {router.stats_file}")

    elif args.cmd == "time-check":
        router = SmartRouter()
        now = router._now()
        print(f"Current time (MST): {now.strftime('%A %H:%M')}")
        for vertical in ["k12", "government", "higher_ed", "other"]:
            callable_now = router._is_callable_now(vertical, now)
            status = "✅ CALLABLE" if callable_now else "⛔ BLOCKED"
            print(f"  {vertical:12} {status}")

    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
