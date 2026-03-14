#!/usr/bin/env python3
"""
post_campaign_results.py — Analyze today's K-12 campaign results and post to Slack.

Usage:
  python3 post_campaign_results.py [--dry-run]
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Load .env
for env_path in [ROOT / ".env", ROOT.parent.parent / ".env"]:
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

import requests

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = "C0AFQ0FPYGM"  # #call-blitz
DRY_RUN = "--dry-run" in sys.argv


def post_slack(text: str):
    if DRY_RUN:
        print(f"\n[DRY RUN] Slack message:\n{text}\n")
        return True
    if not SLACK_TOKEN:
        print("[WARN] No SLACK_BOT_TOKEN")
        return False
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_TOKEN}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=10,
        )
        result = resp.json()
        if result.get("ok"):
            print(f"[slack] ✅ Posted to #call-blitz")
            return True
        else:
            print(f"[slack] ❌ Error: {result}")
            return False
    except Exception as e:
        print(f"[slack] ❌ Failed: {e}")
        return False


def parse_summary_field(summary_text: str, field: str, default="unknown"):
    """Extract a field value from bullet-list summary text."""
    for line in summary_text.lower().split("\n"):
        if f"{field.lower()}:" in line:
            val = line.split(":", 1)[-1].strip()
            return val if val and val != "unknown" else default
    return default


def analyze_campaign():
    """Load and analyze today's campaign results."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Load campaign log ---
    log_entries = []
    log_path = ROOT / "logs" / "campaign_log.jsonl"
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                if line.strip() and today in line:
                    try:
                        log_entries.append(json.loads(line))
                    except Exception:
                        pass

    total_calls = len(log_entries)
    success_calls = [e for e in log_entries if e.get("result") == "success"]
    failed_calls = [e for e in log_entries if e.get("result") == "failed"]

    # Map call_id → account name
    call_id_to_account = {
        e["call_id"]: e["account"]
        for e in success_calls
        if e.get("call_id")
    }

    # --- Load summaries ---
    summaries_path = ROOT / "logs" / "call_summaries.jsonl"
    all_summaries = []
    if summaries_path.exists():
        with open(summaries_path) as f:
            for line in f:
                if line.strip():
                    try:
                        all_summaries.append(json.loads(line))
                    except Exception:
                        pass

    # Filter to today's calls using call_ids
    today_summaries = [
        s for s in all_summaries
        if s.get("call_id") in call_id_to_account
    ]

    # --- Analyze outcomes ---
    connected = 0
    voicemails = 0
    no_answers = 0
    meetings_booked = []
    hot_leads = []

    for s in today_summaries:
        summary_text = s.get("summary", "")
        outcome = parse_summary_field(summary_text, "call outcome")
        meeting = parse_summary_field(summary_text, "meeting booked")
        interest_raw = parse_summary_field(summary_text, "interest level", "1")
        try:
            interest = int(str(interest_raw).strip().split()[0])
        except Exception:
            interest = 1

        spoke_with = parse_summary_field(summary_text, "spoke with")
        role = parse_summary_field(summary_text, "role")
        org = call_id_to_account.get(s.get("call_id"), "Unknown")
        contact_email = parse_summary_field(summary_text, "contact email")
        contact_phone = parse_summary_field(summary_text, "contact direct phone")

        if "connected" in outcome or "answered" in outcome:
            connected += 1
        elif "voicemail" in outcome:
            voicemails += 1
        else:
            no_answers += 1

        if meeting in ("yes", "true", "booked"):
            meetings_booked.append({
                "account": org,
                "call_id": s.get("call_id"),
                "to": s.get("to"),
                "spoke_with": spoke_with,
                "role": role,
                "contact_email": contact_email,
                "contact_phone": contact_phone,
                "summary": summary_text,
            })

        if interest >= 4:
            hot_leads.append({
                "account": org,
                "interest": interest,
                "to": s.get("to"),
                "spoke_with": spoke_with,
                "role": role,
                "summary": summary_text[:300],
            })

    # Connection rate
    conn_rate = f"{(connected / total_calls * 100):.0f}%" if total_calls else "0%"

    return {
        "date": today,
        "total_calls": total_calls,
        "success_calls": len(success_calls),
        "failed_calls": len(failed_calls),
        "connected": connected,
        "voicemails": voicemails,
        "no_answers": no_answers,
        "connection_rate": conn_rate,
        "meetings_booked": meetings_booked,
        "hot_leads": hot_leads,
        "today_summaries": today_summaries,
    }


def build_slack_message(r: dict) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M MST")
    lines = [
        f":school: *K-12 Voice Campaign Results — {now_str}*",
        "",
        "*📊 Call Stats*",
        f">• Calls placed: *{r['total_calls']}* ({r['success_calls']} connected, {r['failed_calls']} failed/bad #)",
        f">• Connected live: *{r['connected']}* | Voicemails: *{r['voicemails']}* | No answer: *{r['no_answers']}*",
        f">• Connection rate: *{r['connection_rate']}*",
        f">• Meetings booked: *{len(r['meetings_booked'])}*",
    ]

    if r["meetings_booked"]:
        lines.append("")
        lines.append("*🤝 Meetings Booked*")
        for m in r["meetings_booked"]:
            lines.append(f">• *{m['account']}* — spoke with {m['spoke_with']} ({m['role']})")
            if m["contact_email"] and m["contact_email"] != "none":
                lines.append(f">  📧 {m['contact_email']}")
            if m["contact_phone"] and m["contact_phone"] != "none":
                lines.append(f">  📞 {m['contact_phone']}")

    if r["hot_leads"]:
        lines.append("")
        lines.append("*🔥 Hot Leads (Interest ≥ 4)*")
        for h in r["hot_leads"]:
            lines.append(f">• *{h['account']}* — Interest: {h['interest']}/5 | Contact: {h['spoke_with']} ({h['role']})")
    else:
        lines.append("")
        lines.append(">_No hot leads this batch — Saturday calls, schools closed, voicemails only expected._")

    lines.append("")
    lines.append(f":clock4: Vertical: K-12 (SD/NE/IA school districts) | Caller: Paul/Fortinet AI")

    return "\n".join(lines)


def create_sfdc_tasks(meetings: list):
    """Create Salesforce follow-up tasks for meeting-booked calls."""
    if not meetings:
        print("[sfdc] No meetings booked — skipping SFDC task creation.")
        return

    print(f"[sfdc] Creating {len(meetings)} SFDC follow-up task(s)...")

    for m in meetings:
        account = m["account"]
        spoke_with = m["spoke_with"]
        role = m["role"]
        contact_email = m.get("contact_email", "")
        notes = m.get("summary", "")[:500]

        # Build SF CLI command to create a Task
        subject = f"K-12 AI Call Follow-up — {account}"
        description = (
            f"Meeting booked via AI voice campaign.\n"
            f"Account: {account}\n"
            f"Spoke with: {spoke_with} ({role})\n"
            f"Contact: {contact_email}\n"
            f"Notes: {notes}"
        )

        # sf CLI: create a task in SFDC
        cmd = [
            "sf", "data", "create", "record",
            "--sobject", "Task",
            "--values",
            f"Subject='{subject}' Status='Not Started' Priority='High' "
            f"ActivityDate='{datetime.now().strftime('%Y-%m-%d')}' "
            f"Description='{description[:1000].replace(chr(39), chr(34))}'",
            "--target-org", "production"
        ]

        if DRY_RUN:
            print(f"[sfdc][DRY RUN] Would create task: {subject}")
            continue

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"[sfdc] ✅ Task created: {subject}")
            else:
                print(f"[sfdc] ❌ Failed: {result.stderr[:200]}")
        except Exception as e:
            print(f"[sfdc] ❌ Error: {e}")


def main():
    print(f"\n{'='*60}")
    print(f"K-12 Campaign Post-Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    results = analyze_campaign()

    print(f"\nTotal calls today: {results['total_calls']}")
    print(f"Success: {results['success_calls']}, Failed: {results['failed_calls']}")
    print(f"Connected live: {results['connected']}")
    print(f"Voicemails: {results['voicemails']}")
    print(f"No answer: {results['no_answers']}")
    print(f"Connection rate: {results['connection_rate']}")
    print(f"Meetings booked: {len(results['meetings_booked'])}")
    print(f"Hot leads: {len(results['hot_leads'])}")

    # Build and post Slack message
    slack_msg = build_slack_message(results)
    post_slack(slack_msg)

    # Create SFDC tasks for meetings
    create_sfdc_tasks(results["meetings_booked"])

    print(f"\n✅ Done.")
    return results


if __name__ == "__main__":
    main()
