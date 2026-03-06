#!/usr/bin/env python3
"""
orchestrator.py — Multi-agent call orchestrator for AI Voice Caller V2.

Behavior:
  - Spins up N agents (max 4)
  - Each agent gets next account via SmartRouter (vertical + time-of-day + performance)
  - Places call via make_call_v8.make_call()
  - Waits for webhook log entry and completes the account
  - Enforces 1 call/agent/5min and business hours (8am-6pm MST, M-F)

Smart routing (execution/smart_router.py):
  - K-12 + government → paul.txt prompt
  - Higher ed + other  → cold_outreach.txt prompt
  - K-12 callable only 8-10am or 1-3pm
  - Government callable only 9-11am
  - No calls 12-1pm (lunch block)
  - State load-balancing: max 3 in-flight per state (IA/NE/SD)
  - Performance-based: best answer_rate variant wins after 10+ calls

Dry run:
  python3 execution/orchestrator.py --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# --- path setup ---
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from account_db import AccountDB  # noqa: E402
from smart_router import SmartRouter  # noqa: E402
from performance_tracker import record_call_outcome  # noqa: E402
import make_call_v8  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "orchestrator.log"
CALL_SUMMARIES = ROOT / "logs" / "call_summaries.jsonl"

SLACK_CHANNEL = "C0AJWRGBW3B"  # #ai-caller
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

RATE_LIMIT_SECONDS = 300  # 1 call per agent per 5 minutes
BUSINESS_TZ = "America/Phoenix"

STATE_FROM_NUMBERS = {
    "SD": "+16053035984",  # 605
    "NE": "+14022755273",  # 402
    "IA": "+15152987809",  # 515
}
DEFAULT_FROM_NUMBER = "+16028985026"  # 602 primary fallback

PROMPT_K12 = "prompts/k12.txt"
PROMPT_GOV = "prompts/paul.txt"
PROMPT_COLD = "prompts/cold_outreach.txt"

K12_PATTERNS = [
    "school",
    "district",
    "school district",
    "usd",
    "k-12",
    "k12",
    "elementary",
    "high school",
    "middle school",
    "community school",
]

GOV_PATTERNS = [
    "municipal",
    "county",
    "city",
    "government",
]


def _setup_logging(verbose: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _to_e164(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if raw.startswith("+"):
        return raw
    return f"+{digits}" if digits else raw


def _now_mst() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BUSINESS_TZ))
    # Fallback: MST is UTC-7 year-round for Arizona
    return datetime.now(timezone(timedelta(hours=-7)))


def _is_business_hours(now: datetime | None = None) -> bool:
    now = now or _now_mst()
    if now.weekday() >= 5:
        return False
    return 8 <= now.hour < 18


def _seconds_until_next_window(now: datetime | None = None) -> int:
    now = now or _now_mst()
    if _is_business_hours(now):
        return 0

    # Move to next weekday 08:00 MST
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now.hour >= 18 or now.weekday() >= 5:
        # advance to next weekday
        days_ahead = 1
        while (now + timedelta(days=days_ahead)).weekday() >= 5:
            days_ahead += 1
        target = (now + timedelta(days=days_ahead)).replace(
            hour=8, minute=0, second=0, microsecond=0
        )
    elif now.hour < 8:
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)

    delta = target - now
    return max(60, int(delta.total_seconds()))


def _select_from_number(state: str | None) -> str:
    if not state:
        return DEFAULT_FROM_NUMBER
    return STATE_FROM_NUMBERS.get(state.strip().upper(), DEFAULT_FROM_NUMBER)


def _contains_pattern(text: str, patterns: list[str]) -> bool:
    s = (text or "").lower()
    return any(p in s for p in patterns)


def _select_prompt(account: dict, override_prompt: str | None = None) -> str:
    if override_prompt:
        return override_prompt

    account_type = str(account.get("account_type") or "")
    account_name = str(account.get("account_name") or "")
    haystack = f"{account_type} {account_name}".strip()

    if _contains_pattern(haystack, K12_PATTERNS):
        return PROMPT_K12
    if _contains_pattern(haystack, GOV_PATTERNS):
        return PROMPT_GOV
    return PROMPT_COLD


def _post_slack(text: str, blocks: list | None = None) -> bool:
    if not SLACK_TOKEN:
        logging.warning("SLACK_BOT_TOKEN not set; skipping Slack post.")
        return False
    try:
        import requests

        payload = {"channel": SLACK_CHANNEL, "text": text}
        if blocks:
            payload["blocks"] = blocks
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            json=payload,
            timeout=20,
        )
        data = r.json()
        if not data.get("ok"):
            logging.warning("Slack post failed: %s", data)
            return False
        return True
    except Exception as exc:
        logging.warning("Slack post error: %s", exc)
        return False


def _parse_outcome(summary: str) -> str:
    s = (summary or "").lower()
    # Direct outcome line
    m = re.search(r"call outcome:\s*([^\n]+)", s)
    if m:
        outcome = m.group(1).strip()
        if "voicemail" in outcome:
            return "voicemail"
        if "no answer" in outcome:
            return "no_answer"
        if "not interested" in outcome:
            return "not_interested"
        if "wrong number" in outcome or "do not call" in outcome:
            return "dnc"
        if "meeting booked" in outcome or "interested" in outcome:
            return "interested"

    if "voicemail" in s or "left a message" in s:
        return "voicemail"
    if "not interested" in s or "do not call" in s or "remove" in s:
        return "not_interested"
    if "wrong number" in s:
        return "dnc"
    if "referral" in s or "talk to" in s or "reach out to" in s:
        return "referral_given"

    # Interest level heuristic
    m = re.search(r"interest level:\s*(\d+)", s)
    if m:
        try:
            score = int(m.group(1))
            if score >= 4:
                return "interested"
            if score <= 1:
                return "not_interested"
        except ValueError:
            pass

    if "meeting booked" in s or "agreed to meet" in s:
        return "interested"

    if "no answer" in s or "did not answer" in s or "rang out" in s:
        return "no_answer"

    return "no_answer"


def _wait_for_webhook(target_phone: str, since_ts: datetime, timeout: int) -> dict | None:
    target_digits = _normalize_phone(target_phone)
    start = time.time()

    if not CALL_SUMMARIES.exists():
        logging.warning("Call summaries file missing: %s", CALL_SUMMARIES)
        time.sleep(5)
        return None

    try:
        with open(CALL_SUMMARIES, "r") as f:
            f.seek(0, os.SEEK_END)
            while time.time() - start < timeout:
                line = f.readline()
                if not line:
                    time.sleep(2)
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue

                ts_raw = entry.get("timestamp")
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now(timezone.utc)

                to_digits = _normalize_phone(entry.get("to", ""))
                if ts >= since_ts and to_digits == target_digits:
                    return entry
    except Exception as exc:
        logging.warning("Webhook wait error: %s", exc)
        return None

    return None


def _agent_loop(
    agent_id: str,
    args,
    stop_event: threading.Event,
    router: "SmartRouter",
) -> None:
    """
    Agent loop — now uses SmartRouter for intelligent account + prompt + voice selection.

    SmartRouter replaces the direct db.checkout() call and adds:
      - Vertical-aware prompt selection
      - Time-of-day call windows per vertical
      - State-based load balancing
      - Performance-based prompt variant selection
    """
    last_call_ts = 0.0

    while not stop_event.is_set():
        try:
            if not _is_business_hours():
                sleep_for = _seconds_until_next_window()
                logging.info("[%s] Outside business hours; sleeping %ss", agent_id, sleep_for)
                stop_event.wait(timeout=sleep_for)
                continue

            since_last = time.time() - last_call_ts
            if since_last < RATE_LIMIT_SECONDS:
                sleep_for = int(RATE_LIMIT_SECONDS - since_last)
                stop_event.wait(timeout=max(5, sleep_for))
                continue

            # ── SmartRouter: replaces db.checkout(agent_id) ──────────────────
            routing = router.get_next_call(agent_id)
            if not routing:
                logging.debug("[%s] No callable accounts (router returned None)", agent_id)
                stop_event.wait(timeout=args.poll_interval)
                continue

            account     = routing["account"]
            prompt_path = args.prompt or routing["prompt_file"]   # CLI override wins
            voice       = args.voice or routing["voice"]          # CLI override wins

            # ── Referral prompt injection ─────────────────────────────────────
            # If account was added by referral_processor, outcome_notes holds
            # a JSON blob with "referral_prompt_file". Use it instead of the
            # default prompt so the AI opens with "I was referred to you by X".
            if not args.prompt:  # Only override if no CLI prompt given
                try:
                    ref_notes = json.loads(account.get("outcome_notes") or "{}")
                    ref_prompt = ref_notes.get("referral_prompt_file")
                    if ref_prompt:
                        candidate = ROOT / ref_prompt
                        if candidate.exists():
                            prompt_path = str(candidate.relative_to(ROOT))
                            logging.info(
                                "[%s] Referral prompt override: %s",
                                agent_id, prompt_path,
                            )
                except Exception:
                    pass  # Malformed notes — keep default prompt
            # ─────────────────────────────────────────────────────────────────

            account_id   = account["account_id"]
            account_name = account.get("account_name", "unknown")
            to_number    = _to_e164(account.get("phone", ""))
            account_state = account.get("state")
            from_number  = args.from_number or _select_from_number(account_state)

            logging.info(
                "[%s] Routing: %s | vertical=%s | prompt=%s | voice=%s | %s",
                agent_id,
                account_name,
                routing["vertical"],
                prompt_path,
                voice,
                routing["reason"],
            )

            if args.dry_run:
                logging.info(
                    "[%s] DRY RUN — would call %s (%s) state=%s -> %s from=%s",
                    agent_id,
                    account_name,
                    account.get("phone"),
                    account_state,
                    to_number,
                    from_number,
                )
                # Release without corrupting perf stats in dry-run
                router.db.complete(account_id, "no_answer", "dry-run release")
                with router._lock:
                    for ids in router._in_flight.values():
                        ids.discard(account_id)
                last_call_ts = time.time()
                continue

            logging.info(
                "[%s] Calling %s (%s) state=%s from=%s prompt=%s",
                agent_id,
                account_name,
                to_number,
                account_state,
                from_number,
                prompt_path,
            )
            call_started = datetime.now(timezone.utc)

            try:
                make_call_v8.make_call(
                    to_number,
                    from_number,
                    voice,
                    prompt_path,
                )
            except Exception as exc:
                logging.exception("[%s] make_call failed: %s", agent_id, exc)
                router.complete_call(account_id, "no_answer", f"call error: {exc}", answered=False)
                record_call_outcome(
                    outcome="no_answer",
                    prompt_file=prompt_path,
                    vertical=routing.get("vertical", "other"),
                    voice=voice,
                    state=account_state or "XX",
                )
                last_call_ts = time.time()
                continue

            # Wait for webhook result
            entry = _wait_for_webhook(to_number, call_started, args.webhook_timeout)
            if entry:
                summary = entry.get("summary", "")
                outcome = _parse_outcome(summary)
                answered = outcome not in ("no_answer",)

                # Complete via router so performance stats get updated
                router.complete_call(
                    account_id,
                    outcome,
                    # Embed prompt path in notes so perf tracker can attribute it
                    notes=f"{summary}\n[prompt:{prompt_path}]",
                    answered=answered,
                )
                record_call_outcome(
                    outcome=outcome,
                    prompt_file=prompt_path,
                    vertical=routing.get("vertical", "other"),
                    voice=voice,
                    state=account_state or "XX",
                )
                logging.info("[%s] Completed %s with outcome=%s", agent_id, account_name, outcome)

                if outcome == "interested":
                    blocks = [
                        {"type": "section", "text": {"type": "mrkdwn",
                                                     "text": f"*Interested Lead*\n*Account:* {account_name}\n*Phone:* {to_number}"}},
                        {"type": "section", "text": {"type": "mrkdwn",
                                                     "text": f"*Summary:*\n{summary[:1500]}"}}
                    ]
                    _post_slack(f"Interested lead: {account_name}", blocks=blocks)
            else:
                router.complete_call(account_id, "no_answer", "webhook timeout", answered=False)
                record_call_outcome(
                    outcome="no_answer",
                    prompt_file=prompt_path,
                    vertical=routing.get("vertical", "other"),
                    voice=voice,
                    state=account_state or "XX",
                )
                logging.warning("[%s] Webhook timeout for %s", agent_id, account_name)

            last_call_ts = time.time()

        except Exception as exc:
            logging.exception("[%s] Unhandled error: %s", agent_id, exc)
            stop_event.wait(timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Voice Caller orchestrator")
    parser.add_argument("--agents", type=int, default=4, help="Number of agents (max 4)")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds to wait when idle")
    parser.add_argument("--webhook-timeout", type=int, default=600, help="Seconds to wait for webhook")
    parser.add_argument("--from-number", default=None, help="Override FROM number")
    parser.add_argument("--voice", default=None, help="Override voice")
    parser.add_argument("--prompt", default=None, help="Override prompt path")
    parser.add_argument("--db", default=None, help="Override DB path")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without calling")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--bypass-time-windows", action="store_true",
                        help="Ignore vertical-specific time windows (useful for testing)")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # ── Instantiate SmartRouter (shared across all agent threads) ─────────────
    router = SmartRouter(
        db_path=args.db,
        bypass_time_windows=getattr(args, "bypass_time_windows", False),
    )
    logging.info("SmartRouter initialized — stats file: %s", router.stats_file)

    if args.dry_run:
        due = router.db.get_due(limit=max(1, min(args.agents, 4)))
        logging.info("DRY RUN — %d accounts due", len(due))
        for a in due:
            vertical = router._classify_vertical(a)
            prompt, voice = router._select_prompt_and_voice(vertical, router._load_stats())
            callable_now = router.is_callable_now(vertical)
            logging.info(
                "Would call: %-35s  state=%-2s  vertical=%-10s  prompt=%-30s  voice=%-16s  %s",
                a.get("account_name", "?"), a.get("state", "?"),
                vertical, prompt, voice,
                "✅ callable now" if callable_now else "⛔ outside time window",
            )
        return 0

    agent_count = max(1, min(args.agents, 4))
    stop_event = threading.Event()
    threads = []

    logging.info("Starting orchestrator with %d agents", agent_count)

    try:
        for i in range(agent_count):
            agent_id = f"agent-{i+1}"
            t = threading.Thread(
                target=_agent_loop,
                args=(agent_id, args, stop_event, router),
                daemon=True,
            )
            t.start()
            threads.append(t)

        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info("Shutting down orchestrator...")
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        return 0


class Orchestrator:
    """Threaded orchestrator for state-aware outbound AI calling campaigns."""

    @staticmethod
    def run() -> int:
        return main()


if __name__ == "__main__":
    raise SystemExit(main())
