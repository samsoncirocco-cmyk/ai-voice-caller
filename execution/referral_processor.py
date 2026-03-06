#!/usr/bin/env python3
"""
referral_processor.py — Scan call summaries for referral signals and post to Slack.

Usage:
  python3 execution/referral_processor.py --dry-run
  python3 execution/referral_processor.py --from-start
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "call_summaries.jsonl"
STATE_FILE = Path(__file__).resolve().parent.parent / "logs" / "referral_state.json"

SLACK_CHANNEL = "C0AJWRGBW3B"  # #ai-caller
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

REFERRAL_KEYWORDS = [
    "talk to",
    "reach out to",
    "contact our",
    "contact",
    "referred to",
    "referral",
]

REFERRAL_PATTERNS = [
    re.compile(
        r"(?:talk to|reach out to|contact)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:at|from)\s+([A-Za-z0-9&.,' \-]{3,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:referred to|referral to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:at|from)?\s*([A-Za-z0-9&.,' \-]{3,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:contact our|talk with|speak with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:in|at|from)\s+([A-Za-z0-9&.,' \-]{3,})",
        re.IGNORECASE,
    ),
]


def _post_slack(text: str, blocks: list | None = None) -> bool:
    if not SLACK_TOKEN:
        print("SLACK_BOT_TOKEN not set; skipping Slack post.")
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
            print(f"Slack error: {data}")
            return False
        return True
    except Exception as exc:
        print(f"Slack post failed: {exc}")
        return False


def _load_state() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        data = json.loads(STATE_FILE.read_text())
        return int(data.get("last_offset", 0))
    except Exception:
        return 0


def _save_state(offset: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_offset": offset}, indent=2))


def _extract_referral(summary: str) -> Tuple[Optional[str], Optional[str], str]:
    text = summary or ""
    for pattern in REFERRAL_PATTERNS:
        m = pattern.search(text)
        if m:
            name = (m.group(1) or "").strip()
            org = (m.group(2) or "").strip()
            context = text[max(0, m.start() - 80): m.end() + 80].strip()
            return name or None, org or None, context

    # Fallback: look for Organization line
    org_match = re.search(r"organization:\s*([^\n]+)", text, re.IGNORECASE)
    org = org_match.group(1).strip() if org_match else None
    context = text[:240].strip()
    return None, org, context


def _has_referral_signal(summary: str) -> bool:
    s = (summary or "").lower()
    return any(k in s for k in REFERRAL_KEYWORDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Referral processor for AI Voice Caller")
    parser.add_argument("--dry-run", action="store_true", help="Print referrals only")
    parser.add_argument("--from-start", action="store_true", help="Process file from start")
    args = parser.parse_args()

    if not LOG_FILE.exists():
        print(f"Log file missing: {LOG_FILE}")
        return 1

    offset = 0 if args.from_start else _load_state()
    referrals = 0

    with open(LOG_FILE, "r") as f:
        if offset:
            f.seek(offset)
        for line in f:
            offset = f.tell()
            try:
                entry = json.loads(line)
            except Exception:
                continue

            summary = entry.get("summary", "")
            if not summary or not _has_referral_signal(summary):
                continue

            name, org, context = _extract_referral(summary)
            if not name and not org:
                continue

            ref = {
                "referral_name": name or "Unknown",
                "referral_org": org or "Unknown",
                "context": context,
                "call_id": entry.get("call_id"),
                "to": entry.get("to"),
                "from": entry.get("from"),
                "timestamp": entry.get("timestamp"),
            }

            if args.dry_run:
                print(json.dumps(ref, indent=2))
                referrals += 1
                continue

            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Referral detected*\n"
                            f"*Name:* {ref['referral_name']}\n"
                            f"*Org:* {ref['referral_org']}\n"
                            f"*Context:* {ref['context'][:400]}"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "primary",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "value": json.dumps(ref),
                            "action_id": "approve_referral",
                        },
                        {
                            "type": "button",
                            "style": "danger",
                            "text": {"type": "plain_text", "text": "Skip"},
                            "value": json.dumps(ref),
                            "action_id": "skip_referral",
                        },
                    ],
                },
            ]

            ok = _post_slack(
                f"Referral detected: {ref['referral_name']} at {ref['referral_org']}",
                blocks=blocks,
            )
            if ok:
                referrals += 1

    _save_state(offset)
    print(f"Referrals processed: {referrals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
