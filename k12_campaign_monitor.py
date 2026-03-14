#!/usr/bin/env python3
"""
k12_campaign_monitor.py — Waits for the K-12 campaign to reach target calls,
then reads call_summaries.jsonl, posts results to Slack #call-blitz,
and creates SFDC Tasks for any Meeting Booked outcomes.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CAMPAIGN_LOG = BASE_DIR / "logs" / "campaign_log.jsonl"
SUMMARIES_LOG = BASE_DIR / "logs" / "call_summaries.jsonl"
STATE_FILE = BASE_DIR / "campaigns" / ".state" / "k12-accounts.json"

TARGET_CALLS = 20
POLL_INTERVAL = 60  # check every 60s
MAX_WAIT_MINUTES = 120  # give up after 2h past target

SLACK_CHANNEL = "C0AFQ0FPYGM"  # #call-blitz
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Load .env
env_file = BASE_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")


def load_campaign_log():
    if not CAMPAIGN_LOG.exists():
        return []
    with open(CAMPAIGN_LOG) as f:
        return [json.loads(l) for l in f if l.strip()]


def load_state():
    if not STATE_FILE.exists():
        return {"completed": [], "failed": []}
    with open(STATE_FILE) as f:
        return json.load(f)


def load_recent_summaries(since_ts=None):
    """Load call summaries from the webhook log."""
    if not SUMMARIES_LOG.exists():
        return []
    entries = []
    with open(SUMMARIES_LOG) as f:
        for line in f:
            try:
                d = json.loads(line)
                if since_ts and d.get("timestamp", "") < since_ts:
                    continue
                # Only include real entries (not test ones)
                if d.get("call_id") == "test-123":
                    continue
                entries.append(d)
            except:
                pass
    return entries


def parse_outcome(summary_text):
    """Parse outcome from free-text summary."""
    if not summary_text:
        return "No Answer"
    text = summary_text.lower()
    if any(x in text for x in ["meeting", "booked", "scheduled", "appointment", "demo", "follow-up call"]):
        return "Meeting Booked"
    elif any(x in text for x in ["interested", "send info", "send over", "sounds good", "yes", "callback"]):
        return "Interested"
    elif any(x in text for x in ["voicemail", "left message", "message left"]):
        return "Voicemail"
    elif any(x in text for x in ["not interested", "no thanks", "remove", "don't call", "dnc"]):
        return "Not Interested"
    elif any(x in text for x in ["no answer", "rang", "unanswered"]):
        return "No Answer"
    return "Connected"


def post_slack(text, blocks=None):
    """Post to Slack #call-blitz."""
    import requests
    if not SLACK_TOKEN:
        print("[slack] No token — printing message:\n" + text)
        return
    payload = {
        "channel": SLACK_CHANNEL,
        "text": text,
    }
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload,
        timeout=15,
    )
    result = resp.json()
    if result.get("ok"):
        print("[slack] Posted successfully.")
    else:
        print(f"[slack] Error: {result.get('error')}")


def create_sfdc_task(account_name, phone, summary):
    """Create a Salesforce Task via sf CLI."""
    print(f"[sfdc] Creating task for: {account_name}")
    # Build task description
    desc = f"K-12 Voice Campaign — Meeting Booked\nPhone: {phone}\nCall Summary: {summary}"
    subject = f"K-12 Follow-Up: {account_name}"

    # sf CLI command — creates a Task record
    cmd = [
        "sf", "data", "create", "record",
        "--sobject", "Task",
        "--values",
        f'Subject="{subject}" Status="Not Started" Priority="High" Description="{desc}" ActivityDate={datetime.now(timezone.utc).strftime("%Y-%m-%d")}',
        "--target-org", "production",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"[sfdc] ✅ Task created: {result.stdout.strip()[:80]}")
            return True
        else:
            print(f"[sfdc] ❌ Failed: {result.stderr.strip()[:120]}")
            return False
    except Exception as e:
        print(f"[sfdc] Exception: {e}")
        return False


def build_slack_report(calls, summaries, state, campaign_start_ts):
    """Build the Slack summary message."""
    total = len(calls)
    success = sum(1 for c in calls if c.get("result") == "success")
    failed = len(state.get("failed", []))

    # Map call_id → campaign log entry
    call_map = {c["call_id"]: c for c in calls if c.get("call_id")}

    # Parse outcomes from summaries
    outcomes = {
        "Meeting Booked": [],
        "Interested": [],
        "Voicemail": [],
        "Not Interested": [],
        "No Answer": [],
        "Connected": [],
    }
    
    for s in summaries:
        raw = s.get("summary") or s.get("raw", {}).get("post_prompt_result", "")
        outcome = parse_outcome(raw)
        account = call_map.get(s.get("call_id"), {}).get("account", "Unknown")
        outcomes[outcome].append({
            "account": account,
            "call_id": s.get("call_id"),
            "summary": raw[:200] if raw else "",
        })

    connected = success  # calls that got through to SignalWire
    connection_rate = f"{(connected/total*100):.0f}%" if total else "N/A"
    meetings = len(outcomes["Meeting Booked"])
    hot_leads = len(outcomes["Interested"])

    lines = [
        f":school: *K-12 Campaign Batch Complete* — {datetime.now().strftime('%Y-%m-%d %H:%M MST')}",
        "",
        f"📞 *Calls Made:* {total}  |  *Connected:* {connected} ({connection_rate})",
        f"🤝 *Meetings Booked:* {meetings}  |  🔥 *Hot Leads:* {hot_leads}",
        f"📬 *Voicemails:* {len(outcomes['Voicemail'])}  |  ❌ *Not Interested:* {len(outcomes['Not Interested'])}",
        "",
    ]

    if outcomes["Meeting Booked"]:
        lines.append("*🏆 MEETINGS BOOKED:*")
        for m in outcomes["Meeting Booked"]:
            lines.append(f"  • {m['account']}")
            if m["summary"]:
                lines.append(f"    _{m['summary'][:120]}_")
        lines.append("")

    if outcomes["Interested"]:
        lines.append("*🔥 HOT LEADS:*")
        for h in outcomes["Interested"][:5]:
            lines.append(f"  • {h['account']}")
        lines.append("")

    if failed:
        lines.append(f"⚠️ *Failed/Dropped:* {failed}")

    return "\n".join(lines), outcomes


def main():
    print(f"[monitor] K-12 Campaign Monitor started at {datetime.now().strftime('%H:%M MST')}")
    print(f"[monitor] Watching for {TARGET_CALLS} calls in {CAMPAIGN_LOG}")

    # Record start time to filter summaries
    campaign_start_ts = datetime.now(timezone.utc).isoformat()
    
    start_time = time.time()
    max_wait = MAX_WAIT_MINUTES * 60

    while True:
        calls = load_campaign_log()
        state = load_state()
        total_processed = len(state.get("completed", [])) + len(state.get("failed", []))

        elapsed = (time.time() - start_time) / 60
        print(f"[monitor] {datetime.now().strftime('%H:%M')} — {total_processed}/{TARGET_CALLS} calls processed ({elapsed:.0f}m elapsed)")

        if total_processed >= TARGET_CALLS:
            print(f"[monitor] ✅ Target reached! Waiting 120s for final webhooks...")
            time.sleep(120)
            break

        if time.time() - start_time > max_wait:
            print(f"[monitor] ⏰ Max wait exceeded. Proceeding with {total_processed} calls.")
            break

        time.sleep(POLL_INTERVAL)

    # Final read
    calls = load_campaign_log()
    state = load_state()
    # Get summaries that came in since campaign started
    summaries = load_recent_summaries(since_ts=campaign_start_ts[:19])
    
    print(f"\n[monitor] Final: {len(calls)} calls, {len(summaries)} webhook summaries")

    # Build and post Slack report
    message, outcomes = build_slack_report(calls, summaries, state, campaign_start_ts)
    print("\n" + "="*60)
    print(message)
    print("="*60 + "\n")
    post_slack(message)

    # SFDC Tasks for meetings booked
    meetings = outcomes.get("Meeting Booked", [])
    if meetings:
        print(f"[sfdc] Creating {len(meetings)} SFDC Task(s) for meetings booked...")
        sfdc_results = []
        for m in meetings:
            # Find phone from campaign log
            phone = next((c["phone"] for c in calls if c.get("account") == m["account"]), "unknown")
            success = create_sfdc_task(m["account"], phone, m["summary"])
            sfdc_results.append((m["account"], success))

        # Post SFDC follow-up to Slack
        sfdc_lines = ["\n:salesforce: *SFDC Tasks Created:*"]
        for acct, ok in sfdc_results:
            sfdc_lines.append(f"  {'✅' if ok else '❌'} {acct}")
        post_slack("\n".join(sfdc_lines))
    else:
        print("[sfdc] No meetings booked — no SFDC tasks needed.")

    # Log completion
    print(f"[monitor] Done at {datetime.now().strftime('%H:%M MST')}")


if __name__ == "__main__":
    main()
