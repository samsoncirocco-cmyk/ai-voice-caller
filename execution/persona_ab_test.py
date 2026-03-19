#!/usr/bin/env python3
"""
persona_ab_test.py — Multi-persona A/B test dashboard and configuration tool.

Shows which AI voice persona (Paul, Mary, Jackson, Alex) is performing best
per vertical based on answer rate, engagement rate, and conversion to meeting.
Reads from both campaigns/performance_stats.json and logs/performance_stats.json.

Usage:
  python3 execution/persona_ab_test.py show              # Show current A/B stats
  python3 execution/persona_ab_test.py show --vertical k12
  python3 execution/persona_ab_test.py reset             # Reset all counters
  python3 execution/persona_ab_test.py winner            # Print winner per vertical
  python3 execution/persona_ab_test.py simulate k12 10   # Simulate 10 A/B assignments
  python3 execution/persona_ab_test.py slack             # Post digest to Slack

Personas tracked:
  paul    → prompts/paul.txt    + openai.onyx    — authority/compliance (K-12, Gov)
  mary    → prompts/mary.txt    + openai.nova    — warm/direct female (K-12, Gov)
  jackson → prompts/jackson.txt + openai.echo    — efficient male (K-12, Gov, Higher Ed)
  alex    → prompts/cold_outreach.txt + openai.shimmer — cold open (Higher Ed, Other)

Design note:
  - Round-robin rotation until any variant hits MIN_CALLS (10) with data
  - First variant to reach statistical confidence wins for that vertical
  - Winners are locked until manually reset or confidence drops
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    MST = ZoneInfo("America/Phoenix")
except ImportError:
    MST = timezone(timedelta(hours=-7))  # type: ignore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CAMPAIGN_STATS = ROOT / "campaigns" / "performance_stats.json"
LOG_STATS      = ROOT / "logs" / "performance_stats.json"

SLACK_TOKEN   = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = "C0AG2ML0C57"  # #activity-log

MIN_CALLS = 10  # calls before we trust a variant's rate

PERSONA_DISPLAY = {
    "prompts/paul.txt":          "Paul    (openai.onyx)    — authority/compliance",
    "prompts/k12.txt":           "Paul/K12 (openai.onyx)   — K-12 specialized",
    "prompts/mary.txt":          "Mary    (openai.nova)    — warm/direct female",
    "prompts/jackson.txt":       "Jackson (openai.echo)    — efficient senior male",
    "prompts/cold_outreach.txt": "Alex    (openai.shimmer) — cold open/qualify",
}

VERTICAL_DISPLAY = {
    "k12":        "K-12 Education",
    "government": "Government/Municipal",
    "higher_ed":  "Higher Education",
    "other":      "Other/Unknown",
}


def _now_mst() -> datetime:
    return datetime.now(MST)


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _post_slack(text: str) -> bool:
    if not SLACK_TOKEN:
        print("[WARN] SLACK_BOT_TOKEN not set")
        return False
    try:
        import requests
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=20,
        )
        return r.json().get("ok", False)
    except Exception as exc:
        print(f"[WARN] Slack failed: {exc}")
        return False


def _merge_stats(campaign: Dict, log: Dict) -> Dict:
    """
    Merge campaign (simple calls/answered) and log (rich outcome breakdown) stats.
    Campaign stats are the primary source for A/B routing decisions.
    Log stats (PerformanceTracker) have richer breakdown (voicemail, interested, etc.)
    """
    merged: Dict = {}
    all_verticals = set(list(campaign.keys()) + list(log.get("prompt_variant", {}).keys()))
    all_verticals.discard("_meta")

    for vertical in all_verticals:
        merged[vertical] = {}
        # Pull from campaign stats (simple answer_rate tracking)
        for prompt, stats in campaign.get(vertical, {}).items():
            merged[vertical][prompt] = {
                "calls":    stats.get("calls", 0),
                "answered": stats.get("answered", 0),
                "voicemail": 0, "interested": 0, "not_interested": 0,
            }
        # Enrich from PerformanceTracker (logs/performance_stats.json)
        pv = log.get("prompt_variant", {})
        for prompt_key, verticals in pv.items():
            vdata = verticals.get(vertical, {})
            if not vdata:
                continue
            if prompt_key not in merged[vertical]:
                merged[vertical][prompt_key] = {
                    "calls": 0, "answered": 0,
                    "voicemail": 0, "interested": 0, "not_interested": 0,
                }
            slot = merged[vertical][prompt_key]
            for outcome in ("answered", "voicemail", "interested", "not_interested"):
                slot[outcome] = slot.get(outcome, 0) + vdata.get(outcome, 0)
            # Recount calls from rich data if richer
            rich_total = sum(vdata.get(o, 0) for o in (
                "answered", "voicemail", "interested", "not_interested", "no_answer"))
            if rich_total > slot["calls"]:
                slot["calls"] = rich_total

    return merged


def _compute_rates(stats: Dict) -> Tuple[float, float, float]:
    """Return (answer_rate, engagement_rate, conversion_rate) for a stats dict."""
    calls      = stats.get("calls", 0)
    answered   = stats.get("answered", 0)
    interested = stats.get("interested", 0)
    if calls == 0:
        return 0.0, 0.0, 0.0
    return (
        answered / calls,
        (answered + interested) / calls,
        interested / calls,
    )


def cmd_show(args: argparse.Namespace) -> None:
    campaign = _load_json(CAMPAIGN_STATS)
    log      = _load_json(LOG_STATS)
    merged   = _merge_stats(campaign, log)

    target_verticals = [args.vertical] if args.vertical else list(merged.keys())
    total_calls = 0

    for vertical in target_verticals:
        vdata = merged.get(vertical, {})
        if not vdata:
            continue
        print(f"\n{'='*70}")
        print(f"  {VERTICAL_DISPLAY.get(vertical, vertical.upper())}")
        print(f"{'='*70}")
        print(f"  {'PERSONA':<44} {'CALLS':>6} {'ANS%':>6} {'ENG%':>6} {'CONV%':>6}  STATUS")
        print(f"  {'-'*44} {'-'*6} {'-'*6} {'-'*6} {'-'*6}  {'-'*10}")

        best_rate = -1.0
        best_prompt = None
        sorted_prompts = sorted(
            vdata.items(),
            key=lambda kv: kv[1].get("calls", 0),
            reverse=True,
        )
        for prompt, stats in sorted_prompts:
            calls = stats.get("calls", 0)
            total_calls += calls
            ar, er, cr = _compute_rates(stats)
            if calls >= MIN_CALLS and ar > best_rate:
                best_rate = ar
                best_prompt = prompt

        for prompt, stats in sorted_prompts:
            calls = stats.get("calls", 0)
            ar, er, cr = _compute_rates(stats)
            display = PERSONA_DISPLAY.get(prompt, prompt)[:44]
            status = ""
            if calls == 0:
                status = "no data"
            elif calls < MIN_CALLS:
                status = f"testing ({calls}/{MIN_CALLS})"
            elif prompt == best_prompt:
                status = "✅ WINNER"
            else:
                status = "candidate"
            print(f"  {display:<44} {calls:>6} {ar*100:>5.1f}% {er*100:>5.1f}% {cr*100:>5.1f}%  {status}")

    print(f"\n  Total calls logged: {total_calls}")
    if total_calls < MIN_CALLS:
        remaining = MIN_CALLS - total_calls
        print(f"  A/B test in progress — need {remaining} more call(s) before winner can be declared.")
    print()


def cmd_winner(args: argparse.Namespace) -> None:
    campaign = _load_json(CAMPAIGN_STATS)
    log      = _load_json(LOG_STATS)
    merged   = _merge_stats(campaign, log)

    print("\n  Persona winners (requires 10+ calls per variant):")
    for vertical, vdata in merged.items():
        best_rate  = -1.0
        best_prompt = None
        for prompt, stats in vdata.items():
            calls = stats.get("calls", 0)
            if calls < MIN_CALLS:
                continue
            ar, _, _ = _compute_rates(stats)
            if ar > best_rate:
                best_rate  = ar
                best_prompt = prompt
        if best_prompt:
            display = PERSONA_DISPLAY.get(best_prompt, best_prompt)
            print(f"  {VERTICAL_DISPLAY.get(vertical, vertical):<24} → {display}  ({best_rate*100:.1f}% answer rate)")
        else:
            print(f"  {VERTICAL_DISPLAY.get(vertical, vertical):<24} → still testing (not enough data)")
    print()


def cmd_reset(args: argparse.Namespace) -> None:
    """Reset campaign performance stats (not log stats — those are audit trail)."""
    fresh: Dict = {
        "k12": {
            "prompts/paul.txt":          {"calls": 0, "answered": 0},
            "prompts/k12.txt":           {"calls": 0, "answered": 0},
            "prompts/mary.txt":          {"calls": 0, "answered": 0},
            "prompts/jackson.txt":       {"calls": 0, "answered": 0},
            "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
        },
        "government": {
            "prompts/paul.txt":          {"calls": 0, "answered": 0},
            "prompts/mary.txt":          {"calls": 0, "answered": 0},
            "prompts/jackson.txt":       {"calls": 0, "answered": 0},
            "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
        },
        "higher_ed": {
            "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
            "prompts/jackson.txt":       {"calls": 0, "answered": 0},
            "prompts/paul.txt":          {"calls": 0, "answered": 0},
        },
        "other": {
            "prompts/cold_outreach.txt": {"calls": 0, "answered": 0},
            "prompts/jackson.txt":       {"calls": 0, "answered": 0},
            "prompts/paul.txt":          {"calls": 0, "answered": 0},
        },
    }
    _save_json(CAMPAIGN_STATS, fresh)
    print("  ✅ Campaign performance_stats.json reset. A/B rotation starts fresh.")


def cmd_simulate(args: argparse.Namespace) -> None:
    """Simulate A/B persona assignments for a vertical without placing calls."""
    vertical = args.vertical or "k12"
    count    = args.count or 10

    sys.path.insert(0, str(HERE))
    try:
        from smart_router import SmartRouter, AB_POOL, PERSONA_MAP, _AB_COUNTERS, _AB_LOCK
        import threading

        pool = [p for p in AB_POOL.get(vertical, []) if (ROOT / p).exists()]
        if not pool:
            print(f"  No A/B pool defined for vertical: {vertical}")
            return

        print(f"\n  Simulating {count} A/B assignments for vertical: {vertical}")
        print(f"  Pool: {pool}")
        print()

        _AB_COUNTERS[vertical] = 0
        assignments: Dict[str, int] = {p: 0 for p in pool}
        for i in range(count):
            with _AB_LOCK:
                idx = _AB_COUNTERS[vertical] % len(pool)
                _AB_COUNTERS[vertical] += 1
            chosen = pool[idx]
            voice, persona = PERSONA_MAP.get(chosen, ("?", "?"))
            assignments[chosen] += 1
            print(f"  Call {i+1:>3}: {persona:<10} ({chosen:<30}) voice={voice}")

        print(f"\n  Distribution:")
        for p, n in assignments.items():
            _, persona = PERSONA_MAP.get(p, ("?", p))
            print(f"    {persona:<10}: {n}/{count} ({n/count*100:.0f}%)")
    except ImportError as exc:
        print(f"  Could not import SmartRouter: {exc}")


def cmd_slack(args: argparse.Namespace) -> None:
    """Post A/B test digest to Slack #activity-log."""
    campaign = _load_json(CAMPAIGN_STATS)
    log      = _load_json(LOG_STATS)
    merged   = _merge_stats(campaign, log)

    total_calls = sum(
        s.get("calls", 0)
        for vdata in merged.values()
        for s in vdata.values()
    )

    lines = [f"*AI Caller Persona A/B Test Digest* — {_now_mst().strftime('%b %d, %Y %I:%M %p MST')}",
             f"Total calls in dataset: {total_calls}",
             ""]
    for vertical, vdata in merged.items():
        lines.append(f"*{VERTICAL_DISPLAY.get(vertical, vertical)}*")
        for prompt, stats in sorted(vdata.items(), key=lambda kv: kv[1].get("calls", 0), reverse=True):
            calls = stats.get("calls", 0)
            if calls == 0:
                continue
            ar, er, _ = _compute_rates(stats)
            _, persona = {
                "prompts/paul.txt": (None, "Paul"),
                "prompts/k12.txt":  (None, "Paul/K12"),
                "prompts/mary.txt": (None, "Mary"),
                "prompts/jackson.txt": (None, "Jackson"),
                "prompts/cold_outreach.txt": (None, "Alex"),
            }.get(prompt, (None, prompt))
            lines.append(f"  • {persona}: {calls} calls | ans {ar*100:.0f}% | eng {er*100:.0f}%")
        lines.append("")

    if total_calls < MIN_CALLS:
        lines.append(f"_A/B test in progress — {MIN_CALLS - total_calls} more calls needed to declare winners._")

    text = "\n".join(lines)
    if _post_slack(text):
        print("  ✅ Posted to Slack #activity-log")
    else:
        print(text)


def main() -> None:
    # Load .env
    for env_path in [ROOT / ".env", ROOT.parent.parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(
        description="Persona A/B test dashboard for AI Voice Caller"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="Show current A/B test stats")
    p_show.add_argument("--vertical", choices=["k12", "government", "higher_ed", "other"],
                        help="Filter to one vertical")

    sub.add_parser("winner", help="Print winner per vertical")
    sub.add_parser("reset", help="Reset campaign performance_stats.json")

    p_sim = sub.add_parser("simulate", help="Simulate A/B rotation assignments")
    p_sim.add_argument("vertical", nargs="?", default="k12",
                       choices=["k12", "government", "higher_ed", "other"])
    p_sim.add_argument("count", nargs="?", type=int, default=10)

    sub.add_parser("slack", help="Post digest to Slack #activity-log")

    args = parser.parse_args()

    {
        "show":     cmd_show,
        "winner":   cmd_winner,
        "reset":    cmd_reset,
        "simulate": cmd_simulate,
        "slack":    cmd_slack,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
