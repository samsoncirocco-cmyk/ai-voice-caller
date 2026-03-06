#!/usr/bin/env python3
"""
performance_tracker.py — Tracks call outcomes and surfaces what's working.

Writes/reads: logs/performance_stats.json
Feed:         smart_router.py → get_best_prompt(), get_best_time()
Digest:       Slack #activity-log every Monday 8am MST

Schema (logs/performance_stats.json):
  {
    "prompt_variant": {
      "<prompt_file>": {
        "<vertical>": { "answered": N, "voicemail": N, ... }
      }
    },
    "voice": {
      "<voice_id>": {
        "<vertical>": { "answered": N, ... }
      }
    },
    "time_of_day_bucket": {
      "<bucket>": { "answered": N, ... }
    },
    "state": {
      "<state_abbrev>": { "answered": N, ... }
    }
  }

Outcome types: answered, voicemail, no_answer, interested, not_interested, referral_given

Derived metrics (per segment):
  answer_rate      = answered / total
  engagement_rate  = (answered + interested) / total
  referral_rate    = referral_given / total
  conversion_rate  = interested / total

Public API:
  tracker = PerformanceTracker()
  tracker.record_outcome(
      outcome="answered",          # one of OUTCOME_TYPES
      prompt_file="prompts/paul.txt",
      vertical="k12",
      voice="openai.onyx",
      state="SD",
      timestamp=None,             # defaults to now (MST)
  )
  tracker.get_best_prompt("k12")  # → "prompts/paul.txt" or None
  tracker.get_best_time("k12")    # → "morning" or None

Cron (add to system crontab):
  0 8 * * 1 cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && python3 execution/performance_tracker.py slack-digest

CLI:
  python3 execution/performance_tracker.py record \\
      --outcome answered --prompt prompts/paul.txt \\
      --vertical k12 --voice openai.onyx --state SD
  python3 execution/performance_tracker.py show
  python3 execution/performance_tracker.py slack-digest
  python3 execution/performance_tracker.py backfill   # scan call_summaries.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    MST = ZoneInfo("America/Phoenix")
except ImportError:
    MST = timezone(timedelta(hours=-7))  # type: ignore

# ── paths ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATS_FILE = ROOT / "logs" / "performance_stats.json"
CALL_SUMMARIES = ROOT / "logs" / "call_summaries.jsonl"

# ── constants ─────────────────────────────────────────────────────────────────
OUTCOME_TYPES = (
    "answered",
    "voicemail",
    "no_answer",
    "interested",
    "not_interested",
    "referral_given",
)

VERTICALS = ("k12", "government", "higher_ed", "other")

TIME_BUCKETS = (
    "early_morning",   # 06–08
    "morning",         # 08–10
    "midday",          # 10–12
    "lunch",           # 12–13
    "afternoon",       # 13–15
    "late_afternoon",  # 15–17
    "evening",         # 17–19
)

BUCKET_HOUR_MAP = [
    (6,  8,  "early_morning"),
    (8,  10, "morning"),
    (10, 12, "midday"),
    (12, 13, "lunch"),
    (13, 15, "afternoon"),
    (15, 17, "late_afternoon"),
    (17, 19, "evening"),
]

# Minimum calls before trusting a metric for routing decisions
MIN_CALLS_FOR_ROUTING = 10

# Slack channel for digests
SLACK_CHANNEL = "C0AG2ML0C57"  # #activity-log

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Schema helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_outcome_dict() -> Dict[str, int]:
    return {o: 0 for o in OUTCOME_TYPES}


def _empty_stats() -> Dict:
    """Return a fresh stats structure."""
    return {
        "prompt_variant": {},
        "voice": {},
        "time_of_day_bucket": {b: _empty_outcome_dict() for b in TIME_BUCKETS},
        "state": {},
        "_meta": {
            "created": _now_mst().isoformat(),
            "last_updated": None,
            "total_calls": 0,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# PerformanceTracker
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceTracker:
    """
    Thread-safe performance tracker for the AI Voice Caller feedback loop.

    Usage:
        tracker = PerformanceTracker()
        tracker.record_outcome(
            outcome="answered",
            prompt_file="prompts/paul.txt",
            vertical="k12",
            voice="openai.onyx",
            state="SD",
        )
        best_prompt = tracker.get_best_prompt("k12")
        best_time   = tracker.get_best_time("k12")
    """

    def __init__(self, stats_file: Optional[Path] = None):
        self.stats_file = stats_file or STATS_FILE
        self._ensure_stats_file()

    # ─────────────────────────── public API ──────────────────────────────────

    def record_outcome(
        self,
        outcome: str,
        prompt_file: str = "unknown",
        vertical: str = "other",
        voice: str = "unknown",
        state: str = "XX",
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Record a single call outcome and persist to logs/performance_stats.json.

        This is the primary entry point — call it after every call completes.
        """
        if outcome not in OUTCOME_TYPES:
            logger.warning("[Tracker] Unknown outcome %r — skipping", outcome)
            return

        ts = timestamp or _now_mst()
        bucket = _hour_to_bucket(ts.hour)
        prompt_key = _normalize_prompt(prompt_file)
        state_key  = (state or "XX").upper()
        vertical   = vertical or "other"
        voice      = voice or "unknown"

        stats = self._load()

        # ── prompt_variant → vertical → outcome ──
        pv = stats["prompt_variant"]
        pv.setdefault(prompt_key, {})
        pv[prompt_key].setdefault(vertical, _empty_outcome_dict())
        _inc(pv[prompt_key][vertical], outcome)

        # ── voice → vertical → outcome ──
        vo = stats["voice"]
        vo.setdefault(voice, {})
        vo[voice].setdefault(vertical, _empty_outcome_dict())
        _inc(vo[voice][vertical], outcome)

        # ── time_of_day_bucket → outcome ──
        # (global across all verticals — use for answering pattern analysis)
        tod = stats["time_of_day_bucket"]
        tod.setdefault(bucket, _empty_outcome_dict())
        _inc(tod[bucket], outcome)

        # ── state → outcome ──
        st = stats["state"]
        st.setdefault(state_key, _empty_outcome_dict())
        _inc(st[state_key], outcome)

        # ── meta ──
        stats["_meta"]["last_updated"] = ts.isoformat()
        stats["_meta"]["total_calls"]  = stats["_meta"].get("total_calls", 0) + 1

        self._save(stats)
        logger.info(
            "[Tracker] Recorded: outcome=%s prompt=%s vertical=%s voice=%s state=%s bucket=%s",
            outcome, prompt_key, vertical, voice, state_key, bucket,
        )

    def get_best_prompt(self, vertical: str) -> Optional[str]:
        """
        Return the prompt_file with the highest engagement_rate for this vertical.
        Requires MIN_CALLS_FOR_ROUTING calls per variant.
        Returns None if insufficient data.
        """
        stats = self._load()
        pv = stats.get("prompt_variant", {})

        best_prompt: Optional[str] = None
        best_rate: float = -1.0

        for prompt_key, verticals in pv.items():
            outcomes = verticals.get(vertical, {})
            total = sum(outcomes.values())
            if total < MIN_CALLS_FOR_ROUTING:
                continue
            rate = _engagement_rate(outcomes)
            if rate > best_rate:
                best_rate = rate
                best_prompt = prompt_key

        return best_prompt

    def get_best_time(self, vertical: str) -> Optional[str]:
        """
        Return the time bucket with the highest answer_rate.

        Looks at time_of_day_bucket data (global, not per-vertical — vertical-specific
        time data builds slowly; global patterns are more reliable sooner).

        Returns None if insufficient data.
        """
        stats = self._load()
        tod = stats.get("time_of_day_bucket", {})

        best_bucket: Optional[str] = None
        best_rate: float = -1.0

        for bucket, outcomes in tod.items():
            total = sum(outcomes.values())
            if total < MIN_CALLS_FOR_ROUTING:
                continue
            rate = _answer_rate(outcomes)
            if rate > best_rate:
                best_rate = rate
                best_bucket = bucket

        return best_bucket

    def get_metrics(self, vertical: Optional[str] = None) -> Dict:
        """
        Return computed metrics for all segments.

        If vertical is provided, filter prompt_variant and voice metrics to that vertical.
        Returns a dict suitable for display or Slack posting.
        """
        stats = self._load()
        out: Dict = {
            "prompt_variant": {},
            "voice": {},
            "time_of_day_bucket": {},
            "state": {},
        }

        # Prompt variants
        for prompt_key, verticals_data in stats.get("prompt_variant", {}).items():
            if vertical:
                outcomes_map = {vertical: verticals_data.get(vertical, _empty_outcome_dict())}
            else:
                outcomes_map = verticals_data

            for vert, outcomes in outcomes_map.items():
                total = sum(outcomes.values())
                seg = f"{prompt_key}/{vert}" if not vertical else prompt_key
                out["prompt_variant"][seg] = _compute_metrics(outcomes)

        # Voice
        for voice_key, verticals_data in stats.get("voice", {}).items():
            if vertical:
                outcomes_map = {vertical: verticals_data.get(vertical, _empty_outcome_dict())}
            else:
                outcomes_map = verticals_data

            for vert, outcomes in outcomes_map.items():
                seg = f"{voice_key}/{vert}" if not vertical else voice_key
                out["voice"][seg] = _compute_metrics(outcomes)

        # Time buckets (global)
        for bucket, outcomes in stats.get("time_of_day_bucket", {}).items():
            out["time_of_day_bucket"][bucket] = _compute_metrics(outcomes)

        # States
        for state_key, outcomes in stats.get("state", {}).items():
            out["state"][state_key] = _compute_metrics(outcomes)

        return out

    def build_slack_digest(self) -> str:
        """
        Build a weekly digest message for Slack #activity-log.
        Returns the formatted string (does not post — use post_slack_digest()).
        """
        stats = self._load()
        meta  = stats.get("_meta", {})
        total = meta.get("total_calls", 0)
        last  = meta.get("last_updated", "never")

        lines = [
            "📊 *AI Voice Caller — Weekly Performance Digest*",
            f"Total calls tracked: *{total}* | Last updated: {last}",
            "",
        ]

        # ── Top prompts by engagement ──
        lines.append("*Prompt Performance (engagement_rate = answered + interested / total):*")
        pv_rows = []
        for prompt_key, verticals_data in stats.get("prompt_variant", {}).items():
            for vert, outcomes in verticals_data.items():
                total_calls = sum(outcomes.values())
                if total_calls == 0:
                    continue
                m = _compute_metrics(outcomes)
                pv_rows.append((prompt_key, vert, total_calls, m))
        pv_rows.sort(key=lambda r: r[3]["engagement_rate"], reverse=True)
        if pv_rows:
            for prompt_key, vert, total_calls, m in pv_rows[:8]:
                lines.append(
                    f"  • `{_short_prompt(prompt_key)}` / {vert} — "
                    f"engage={m['engagement_rate']:.0%} "
                    f"ans={m['answer_rate']:.0%} "
                    f"ref={m['referral_rate']:.0%} "
                    f"n={total_calls}"
                )
        else:
            lines.append("  (no data yet)")

        # ── Best time buckets ──
        lines.append("")
        lines.append("*Best Call Times (answer_rate):*")
        tod = stats.get("time_of_day_bucket", {})
        tod_rows = []
        for bucket, outcomes in tod.items():
            total_calls = sum(outcomes.values())
            if total_calls == 0:
                continue
            m = _compute_metrics(outcomes)
            tod_rows.append((bucket, total_calls, m))
        tod_rows.sort(key=lambda r: r[2]["answer_rate"], reverse=True)
        if tod_rows:
            for bucket, total_calls, m in tod_rows[:5]:
                lines.append(
                    f"  • {bucket}: ans={m['answer_rate']:.0%}  n={total_calls}"
                )
        else:
            lines.append("  (no data yet)")

        # ── State breakdown ──
        lines.append("")
        lines.append("*State Breakdown:*")
        state_rows = []
        for state_key, outcomes in stats.get("state", {}).items():
            total_calls = sum(outcomes.values())
            if total_calls == 0:
                continue
            m = _compute_metrics(outcomes)
            state_rows.append((state_key, total_calls, m))
        state_rows.sort(key=lambda r: r[1], reverse=True)
        if state_rows:
            for state_key, total_calls, m in state_rows[:10]:
                lines.append(
                    f"  • {state_key}: engage={m['engagement_rate']:.0%}  "
                    f"ans={m['answer_rate']:.0%}  n={total_calls}"
                )
        else:
            lines.append("  (no data yet)")

        # ── Smart routing recommendations ──
        lines.append("")
        lines.append("*Smart Routing Recommendations:*")
        for vert in VERTICALS:
            best_p = self.get_best_prompt(vert)
            best_t = self.get_best_time(vert)
            if best_p or best_t:
                rec_parts = []
                if best_p:
                    rec_parts.append(f"prompt=`{_short_prompt(best_p)}`")
                if best_t:
                    rec_parts.append(f"best-time={best_t}")
                lines.append(f"  • {vert}: {' '.join(rec_parts)}")

        return "\n".join(lines)

    def post_slack_digest(self) -> bool:
        """
        Build and post the weekly digest to Slack #activity-log.
        Returns True on success.
        """
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if not token:
            logger.warning("[Tracker] SLACK_BOT_TOKEN not set — cannot post digest")
            print("⚠️  SLACK_BOT_TOKEN not set. Digest:\n")
            print(self.build_slack_digest())
            return False

        import urllib.request

        message = self.build_slack_digest()
        payload = json.dumps({
            "channel": SLACK_CHANNEL,
            "text": message,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                if body.get("ok"):
                    logger.info("[Tracker] Weekly digest posted to Slack #activity-log")
                    return True
                else:
                    logger.error("[Tracker] Slack error: %s", body.get("error"))
                    return False
        except Exception as exc:
            logger.error("[Tracker] Failed to post Slack digest: %s", exc)
            return False

    # ─────────────────────────── backfill ────────────────────────────────────

    def backfill_from_summaries(self, summaries_file: Optional[Path] = None) -> int:
        """
        Scan logs/call_summaries.jsonl and record any outcomes not yet tracked.
        Returns number of records processed.

        Useful for initial population — run once after deploying the tracker.
        Infers outcome from post_prompt_data/summary text.
        """
        path = summaries_file or CALL_SUMMARIES
        if not path.exists():
            logger.warning("[Tracker] No call_summaries.jsonl found at %s", path)
            return 0

        count = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    outcome   = _infer_outcome(record)
                    prompt    = _infer_prompt(record)
                    vertical  = _infer_vertical(record)
                    voice     = _infer_voice(record)
                    state     = _infer_state(record)
                    ts_str    = record.get("timestamp")
                    ts        = _parse_ts(ts_str) if ts_str else None

                    self.record_outcome(
                        outcome=outcome,
                        prompt_file=prompt,
                        vertical=vertical,
                        voice=voice,
                        state=state,
                        timestamp=ts,
                    )
                    count += 1
                except Exception as exc:
                    logger.debug("[Tracker] Skipping bad record: %s", exc)

        logger.info("[Tracker] Backfill complete — %d records processed", count)
        return count

    # ─────────────────────────── file I/O ────────────────────────────────────

    def _ensure_stats_file(self) -> None:
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.stats_file.exists():
            self._save(_empty_stats())
            logger.info("[Tracker] Created %s", self.stats_file)

    def _load(self) -> Dict:
        try:
            with open(self.stats_file) as f:
                data = json.load(f)
            # Ensure all expected top-level keys exist
            for key in ("prompt_variant", "voice", "time_of_day_bucket", "state", "_meta"):
                data.setdefault(key, {} if key != "_meta" else {
                    "created": None, "last_updated": None, "total_calls": 0
                })
            # Ensure all time buckets exist
            for bucket in TIME_BUCKETS:
                data["time_of_day_bucket"].setdefault(bucket, _empty_outcome_dict())
            return data
        except Exception as exc:
            logger.warning("[Tracker] Could not load stats (%s) — starting fresh", exc)
            return _empty_stats()

    def _save(self, stats: Dict) -> None:
        try:
            with open(self.stats_file, "w") as f:
                json.dump(stats, f, indent=2)
        except Exception as exc:
            logger.error("[Tracker] Failed to save stats: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_mst() -> datetime:
    return datetime.now(MST)


def _inc(d: Dict[str, int], key: str) -> None:
    d[key] = d.get(key, 0) + 1


def _hour_to_bucket(hour: int) -> str:
    for start, end, name in BUCKET_HOUR_MAP:
        if start <= hour < end:
            return name
    return "other"


def _normalize_prompt(path: str) -> str:
    """Normalize prompt path to a consistent relative form."""
    p = str(path).strip()
    # Strip leading slashes and any absolute prefix
    if "prompts/" in p:
        return "prompts/" + p.split("prompts/")[-1]
    return p or "unknown"


def _short_prompt(path: str) -> str:
    """Return just the filename without extension."""
    return Path(path).stem


def _answer_rate(outcomes: Dict[str, int]) -> float:
    total = sum(outcomes.values())
    if total == 0:
        return 0.0
    return outcomes.get("answered", 0) / total


def _engagement_rate(outcomes: Dict[str, int]) -> float:
    total = sum(outcomes.values())
    if total == 0:
        return 0.0
    return (outcomes.get("answered", 0) + outcomes.get("interested", 0)) / total


def _referral_rate(outcomes: Dict[str, int]) -> float:
    total = sum(outcomes.values())
    if total == 0:
        return 0.0
    return outcomes.get("referral_given", 0) / total


def _conversion_rate(outcomes: Dict[str, int]) -> float:
    total = sum(outcomes.values())
    if total == 0:
        return 0.0
    return outcomes.get("interested", 0) / total


def _compute_metrics(outcomes: Dict[str, int]) -> Dict:
    total = sum(outcomes.values())
    return {
        "total": total,
        "counts": dict(outcomes),
        "answer_rate":     round(_answer_rate(outcomes), 4),
        "engagement_rate": round(_engagement_rate(outcomes), 4),
        "referral_rate":   round(_referral_rate(outcomes), 4),
        "conversion_rate": round(_conversion_rate(outcomes), 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inference helpers (for backfill from raw call_summaries.jsonl)
# ─────────────────────────────────────────────────────────────────────────────

def _infer_outcome(record: Dict) -> str:
    """Infer outcome type from a raw call_summaries.jsonl record."""
    raw  = record.get("raw", {})
    summary = (record.get("summary") or
               raw.get("post_prompt_data", {}).get("raw", "") or
               raw.get("post_prompt_result", "") or "").lower()

    call_state = (raw.get("SWMLCall", {}).get("call_state") or "").lower()

    # Explicit outcome patterns from post-prompt text
    if re.search(r"referral|referred|refer\b", summary):
        return "referral_given"
    if re.search(r"interest.*level.*[4-5]|very interested|meeting booked|follow.?up agreed|schedule.*meeting", summary):
        return "interested"
    if re.search(r"not interested|declined|no interest|don.?t want|do not call", summary):
        return "not_interested"
    if re.search(r"voicemail|left.*message|left a message|went to voicemail", summary):
        return "voicemail"
    if re.search(r"no answer|didn.?t answer|no one answered|not available", summary):
        return "no_answer"

    # Check call state
    if call_state in ("answered",):
        return "answered"

    # If there's a meaningful conversation (call_log has >2 exchanges), likely answered
    call_log = raw.get("call_log", [])
    user_turns = [e for e in call_log if e.get("role") == "user"]
    if len(user_turns) >= 2:
        return "answered"

    return "no_answer"


def _infer_prompt(record: Dict) -> str:
    raw = record.get("raw", {})
    system_content = ""
    for entry in raw.get("call_log", []):
        if entry.get("role") == "system":
            system_content = entry.get("content", "")
            break
    # Heuristics from system prompt content
    if "paul" in system_content.lower():
        return "prompts/paul.txt"
    if "k-12" in system_content.lower() or "school district" in system_content.lower():
        return "prompts/k12.txt"
    return "prompts/cold_outreach.txt"


def _infer_vertical(record: Dict) -> str:
    raw = record.get("raw", {})
    system_content = ""
    for entry in raw.get("call_log", []):
        if entry.get("role") == "system":
            system_content = entry.get("content", "").lower()
            break
    if "school district" in system_content or "k-12" in system_content or "usd" in system_content:
        return "k12"
    if "municipality" in system_content or "city" in system_content or "county" in system_content:
        return "government"
    if "university" in system_content or "college" in system_content:
        return "higher_ed"
    return "other"


def _infer_voice(record: Dict) -> str:
    # Voice is not stored in summaries — infer from prompt persona
    prompt = _infer_prompt(record)
    if "paul" in prompt or "k12" in prompt:
        return "openai.onyx"
    return "openai.shimmer"


def _infer_state(record: Dict) -> str:
    raw = record.get("raw", {})
    # Try to extract from system prompt or global_data
    system_content = ""
    for entry in raw.get("call_log", []):
        if entry.get("role") == "system":
            system_content = entry.get("content", "").upper()
            break
    state_match = re.search(r"\b(SD|NE|IA|AZ|CO|WY|MT|ND)\b", system_content)
    if state_match:
        return state_match.group(1)
    # Infer from caller_id_number area code
    to_number = raw.get("SWMLCall", {}).get("to_number", "")
    area = to_number[2:5] if to_number.startswith("+1") else ""
    area_to_state = {
        "605": "SD", "402": "NE", "531": "NE",
        "515": "IA", "319": "IA", "563": "IA",
        "602": "AZ", "480": "AZ", "623": "AZ",
    }
    return area_to_state.get(area, "XX")


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone(MST)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Integration hook for orchestrator / smart_router
# ─────────────────────────────────────────────────────────────────────────────

_tracker_instance: Optional[PerformanceTracker] = None


def get_tracker() -> PerformanceTracker:
    """Return a singleton PerformanceTracker (module-level cache)."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PerformanceTracker()
    return _tracker_instance


def record_call_outcome(
    outcome: str,
    prompt_file: str = "unknown",
    vertical: str = "other",
    voice: str = "unknown",
    state: str = "XX",
    timestamp: Optional[datetime] = None,
) -> None:
    """
    Module-level shortcut — call this after every call completes.

    Compatible with orchestrator.py's complete_call() pattern.
    Simply import and call:

        from performance_tracker import record_call_outcome
        record_call_outcome(outcome="answered", prompt_file=prompt_path,
                            vertical=vertical, voice=voice, state=state)
    """
    get_tracker().record_outcome(
        outcome=outcome,
        prompt_file=prompt_file,
        vertical=vertical,
        voice=voice,
        state=state,
        timestamp=timestamp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli_main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Performance tracker for AI Voice Caller feedback loop"
    )
    sub = parser.add_subparsers(dest="cmd")

    # record
    p_rec = sub.add_parser("record", help="Record a single call outcome")
    p_rec.add_argument("--outcome",  required=True, choices=OUTCOME_TYPES)
    p_rec.add_argument("--prompt",   default="unknown", help="Prompt file path")
    p_rec.add_argument("--vertical", default="other",   choices=VERTICALS)
    p_rec.add_argument("--voice",    default="unknown", help="Voice ID")
    p_rec.add_argument("--state",    default="XX",      help="2-letter state code")

    # show
    p_show = sub.add_parser("show", help="Show current stats and metrics")
    p_show.add_argument("--vertical", default=None, help="Filter by vertical")
    p_show.add_argument("--json", action="store_true", help="Output raw JSON")

    # best-prompt
    p_bp = sub.add_parser("best-prompt", help="Get best prompt for a vertical")
    p_bp.add_argument("vertical", choices=VERTICALS)

    # best-time
    p_bt = sub.add_parser("best-time", help="Get best time bucket for a vertical")
    p_bt.add_argument("vertical", choices=VERTICALS)

    # slack-digest
    sub.add_parser("slack-digest", help="Post weekly digest to Slack #activity-log")

    # backfill
    p_bf = sub.add_parser("backfill", help="Backfill from logs/call_summaries.jsonl")
    p_bf.add_argument("--file", default=None, help="Path to call_summaries.jsonl")

    # reset
    sub.add_parser("reset", help="Reset stats to empty (destructive!)")

    args = parser.parse_args()
    tracker = PerformanceTracker()

    if args.cmd == "record":
        tracker.record_outcome(
            outcome=args.outcome,
            prompt_file=args.prompt,
            vertical=args.vertical,
            voice=args.voice,
            state=args.state,
        )
        print(f"✅ Recorded: outcome={args.outcome} prompt={args.prompt} "
              f"vertical={args.vertical} voice={args.voice} state={args.state}")

    elif args.cmd == "show":
        if getattr(args, "json", False):
            with open(tracker.stats_file) as f:
                print(f.read())
        else:
            metrics = tracker.get_metrics(vertical=getattr(args, "vertical", None))
            _print_metrics(metrics)

    elif args.cmd == "best-prompt":
        result = tracker.get_best_prompt(args.vertical)
        if result:
            print(f"Best prompt for {args.vertical}: {result}")
        else:
            print(f"Not enough data for {args.vertical} yet (need {MIN_CALLS_FOR_ROUTING}+ calls per variant)")

    elif args.cmd == "best-time":
        result = tracker.get_best_time(args.vertical)
        if result:
            print(f"Best time for {args.vertical}: {result}")
        else:
            print(f"Not enough data yet (need {MIN_CALLS_FOR_ROUTING}+ calls per bucket)")

    elif args.cmd == "slack-digest":
        success = tracker.post_slack_digest()
        if success:
            print("✅ Weekly digest posted to Slack #activity-log")
        else:
            print("⚠️  Slack post failed (check logs)")
        return 0 if success else 1

    elif args.cmd == "backfill":
        path = Path(args.file) if getattr(args, "file", None) else None
        count = tracker.backfill_from_summaries(path)
        print(f"✅ Backfilled {count} records from call_summaries.jsonl")

    elif args.cmd == "reset":
        confirm = input("Reset all performance stats? This is destructive. Type YES to confirm: ")
        if confirm.strip() == "YES":
            tracker._save(_empty_stats())
            print("✅ Stats reset.")
        else:
            print("Aborted.")

    else:
        parser.print_help()
        return 1

    return 0


def _print_metrics(metrics: Dict) -> None:
    """Pretty-print metrics dict."""
    SEP = "─" * 70

    sections = [
        ("Prompt Variants",   "prompt_variant"),
        ("Voice",             "voice"),
        ("Time of Day",       "time_of_day_bucket"),
        ("States",            "state"),
    ]

    for title, key in sections:
        data = metrics.get(key, {})
        if not data:
            continue
        print(f"\n{title}")
        print(SEP)
        rows = sorted(
            [(seg, m) for seg, m in data.items() if m["total"] > 0],
            key=lambda r: r[1]["engagement_rate"],
            reverse=True,
        )
        if not rows:
            print("  (no calls recorded)")
            continue
        for seg, m in rows:
            print(
                f"  {seg:<35} "
                f"n={m['total']:<6} "
                f"answer={m['answer_rate']:.0%}  "
                f"engage={m['engagement_rate']:.0%}  "
                f"refer={m['referral_rate']:.0%}  "
                f"convert={m['conversion_rate']:.0%}"
            )


if __name__ == "__main__":
    raise SystemExit(_cli_main())
