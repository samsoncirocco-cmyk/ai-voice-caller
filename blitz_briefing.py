#!/usr/bin/env python3
"""
blitz_briefing.py — Send a pre-blitz Slack briefing with call sheet summary.

Runs at 6:45 AM MST day-of to brief Samson on today's call targets.
Includes: deal follow-ups with urgency, E-Rate targets, launch instructions.

Usage:
  python3 blitz_briefing.py campaigns/blitz-mar19-2026-v2.csv
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_DM_SAMSON = "D0AFT6P7N92"


def post_to_slack(text: str, blocks=None):
    if not SLACK_BOT_TOKEN:
        print("No SLACK_BOT_TOKEN — printing instead:")
        print(text)
        return
    payload = {"channel": SLACK_DM_SAMSON, "text": text}
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=10
    )
    data = resp.json()
    if data.get("ok"):
        print(f"✅ Posted to Slack")
    else:
        print(f"❌ Slack error: {data.get('error')}")


def count_cached(csv_path: str) -> tuple[int, int]:
    """Return (cached_count, total_count) for blitz targets."""
    cache_dir = BASE_DIR / "campaigns" / ".research_cache"
    import re
    from datetime import timezone
    
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    
    state_map = {"SD": "South Dakota", "NE": "Nebraska", "IA": "Iowa"}
    cached = 0
    
    for row in rows:
        acct = row.get("account_name", "").strip()
        state_raw = row.get("state", "SD")
        state = state_map.get(state_raw.upper(), state_raw)
        
        normalized = re.sub(r"[^\w]", "_", acct.lower())
        normalized = re.sub(r"_+", "_", normalized).strip("_")[:60]
        state_clean = re.sub(r"[^\w]", "", state.lower())[:4]
        cache_key = f"{state_clean}__{normalized}"
        cache_file = cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                cached_at = data.get("_cached_at", "")
                if cached_at:
                    from datetime import timezone
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
                    if age < 7 * 86400 and data.get("_source") != "generic_fallback":
                        cached += 1
            except Exception:
                pass
    
    return cached, len(rows)


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "campaigns/blitz-mar19-2026-v2.csv"
    
    if not Path(csv_path).exists():
        print(f"❌ CSV not found: {csv_path}")
        sys.exit(1)
    
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    
    # Separate deal follow-ups from E-Rate prospecting
    deals = [r for r in rows if r.get("call_type") == "deal_followup"]
    erate = [r for r in rows if r.get("call_type") == "erate"]
    
    cached_count, total = count_cached(csv_path)
    
    now = datetime.now()
    date_str = now.strftime("%A, %B %d")
    
    # Build Slack blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📞 Call Blitz Ready — {date_str}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{total} targets loaded* | {cached_count}/{total} pre-researched ✅ | Research cache: READY"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🎯 Deal Follow-Ups ({len(deals)} accounts)*"
            }
        }
    ]
    
    # Add deal targets
    deal_lines = []
    for d in deals:
        acct = d.get("account_name", "")
        phone = d.get("phone", "")
        state = d.get("state", "")
        # Highlight Christ Lutheran as URGENT
        if "Christ Lutheran" in acct:
            deal_lines.append(f"• 🔴 *{acct}* — {phone} ({state}) ← E-RATE CLOSES TODAY!")
        else:
            deal_lines.append(f"• {acct} — {phone} ({state})")
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(deal_lines)
        }
    })
    
    blocks.extend([
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📚 E-Rate Prospecting ({len(erate)} accounts)* — SD/NE/IA schools and libraries"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Full list in `campaigns/blitz-mar19-2026-v2.csv`"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🚀 Launch Commands:*\n```bash\ncd ~/openclaw/workspace/projects/ai-voice-caller\n\n# Full blitz (33 accounts, 2 min intervals):\nbash launch_blitz.sh\n\n# Dry run first to verify:\nbash launch_blitz.sh --dry-run\n\n# Deal follow-ups only (9 accounts):\npython3 campaign_runner_v2.py campaigns/blitz-mar19-2026-v2.csv --limit 9 --interval 90\n```"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Dashboard: <https://brain.6eyes.dev/call-blitz|Call Blitz> | <https://brain.6eyes.dev/caller-analytics|Analytics> | <https://brain.6eyes.dev/close-now|Close This Week>"
                }
            ]
        }
    ])
    
    fallback_text = f"📞 Call Blitz Ready — {date_str}: {total} targets, {cached_count} pre-researched. Christ Lutheran School NE ($14.8K E-Rate) closes TODAY. bash launch_blitz.sh to start."
    
    post_to_slack(fallback_text, blocks)
    print(f"\n{fallback_text}")


if __name__ == "__main__":
    main()
