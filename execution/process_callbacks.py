#!/usr/bin/env python3
"""
process_callbacks.py — Post-call processing pipeline for AI Voice Caller.

This script handles everything that should happen AFTER a call ends:
  1. Parse the structured summary from SignalWire's post_prompt callback
  2. Detect and queue referrals for follow-up
  3. Detect meeting bookings and create calendar-ready entries
  4. Queue follow-up emails when the AI promised to send info
  5. Update the performance tracker with call outcomes
  6. Push to Salesforce (via sfdc_push.py)
  7. Post high-value call alerts to Slack

Can be run:
  - As a standalone batch processor (scan all unprocessed entries)
  - Called from webhook_server.py after each call (single entry)
  - As a periodic cron job to catch anything missed

Usage:
  python3 execution/process_callbacks.py --scan                  # Process all unprocessed
  python3 execution/process_callbacks.py --call-id <uuid>        # Process single call
  python3 execution/process_callbacks.py --scan --dry-run        # Preview without actions
  python3 execution/process_callbacks.py --stats                 # Show processing stats
  python3 execution/process_callbacks.py --reprocess --since 24h # Reprocess last 24h
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
SUMMARIES_FILE = LOGS_DIR / "call_summaries.jsonl"
ARCHIVE_FILE = LOGS_DIR / "call_summaries_test_archive_mar13.jsonl"
PROCESSING_STATE = LOGS_DIR / "processing-state.json"
FOLLOW_UP_QUEUE = LOGS_DIR / "follow-up-queue.jsonl"
MEETING_QUEUE = LOGS_DIR / "meetings-detected.jsonl"
EMAIL_QUEUE = LOGS_DIR / "email-queue.jsonl"
ALERTS_LOG = LOGS_DIR / "high-value-alerts.jsonl"

sys.path.insert(0, str(ROOT / "execution"))
sys.path.insert(0, str(ROOT))

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_DM = "D0AFT6P7N92"  # Samson DM
SLACK_ACTIVITY = "C0AG2ML0C57"  # #activity-log

# ── Summary Parser ─────────────────────────────────────────────────────────────

OUTCOME_MAP = {
    "connected": "Connected",
    "left voicemail": "Voicemail",
    "voicemail": "Voicemail",
    "no answer": "No Answer",
    "not interested": "Not Interested",
    "wrong number": "Wrong Number",
    "meeting booked": "Meeting Booked",
    "meeting scheduled": "Meeting Booked",
    "demo booked": "Meeting Booked",
}


def parse_structured_summary(summary: str) -> Dict[str, Any]:
    """
    Parse the AI's structured post-prompt summary into a dict.

    Expected format (from POST_PROMPT in make_call_v8.py):
      - Call outcome: Connected
      - Spoke with: John Smith
      - Role: IT Director
      - Organization: Lincoln Public Schools
      - Current vendor: Palo Alto
      - Current setup: FortiGate 200F cluster
      - Pain points: EOL firewalls, compliance gaps
      - Interest level: 4
      - Follow-up: Send case study on K-12 security
      - Meeting booked: yes — Tuesday 3pm
      - Contact email: john@lps.org
      - Contact direct phone: 402-555-1234
      - Notes: Very engaged, mentioned budget cycle in July
    """
    if not summary:
        return {"outcome": "No Answer", "raw_summary": ""}

    result: Dict[str, Any] = {"raw_summary": summary}
    sl = summary.lower()

    # Field extraction with regex
    field_patterns = {
        "outcome": r"call outcome[:\s]+([^\n]+)",
        "spoke_with": r"spoke with[:\s]+([^\n]+)",
        "role": r"role[:\s]+([^\n]+)",
        "organization": r"organization[:\s]+([^\n]+)",
        "current_vendor": r"current vendor[:\s]+([^\n]+)",
        "current_setup": r"current setup[:\s]+([^\n]+)",
        "pain_points": r"pain points?[:\s]+([^\n]+)",
        "interest_level": r"interest level[:\s]+(\d+)",
        "follow_up": r"follow[- ]?up[:\s]+([^\n]+)",
        "meeting_booked": r"meeting booked[:\s]+([^\n]+)",
        "contact_email": r"contact email[:\s]+([^\n]+)",
        "contact_phone": r"contact (?:direct )?phone[:\s]+([^\n]+)",
        "notes": r"notes[:\s]+([^\n]+)",
    }

    for field, pattern in field_patterns.items():
        match = re.search(pattern, sl if field != "notes" else summary, re.IGNORECASE)
        if match:
            val = match.group(1).strip().rstrip(".,;")
            if field == "interest_level":
                try:
                    result[field] = int(val)
                except ValueError:
                    result[field] = 0
            elif field == "outcome":
                # Normalize outcome
                normalized = OUTCOME_MAP.get(val.lower(), val.title())
                result[field] = normalized
            elif val.lower() in ("unknown", "none", "n/a", "na", ""):
                result[field] = None
            else:
                result[field] = val
        elif field == "outcome":
            result[field] = "No Answer"  # default

    return result


# ── Detection Engines ──────────────────────────────────────────────────────────

def detect_referral(parsed: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Detect if the call resulted in a referral to another person."""
    summary = parsed.get("raw_summary", "")
    notes = parsed.get("notes", "") or ""
    follow_up = parsed.get("follow_up", "") or ""
    combined = f"{summary}\n{notes}\n{follow_up}"

    referral_patterns = [
        re.compile(
            r"(?:talk to|reach out to|contact|ask for|speak with|referred (?:me |us )?to)\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
            r"(?:\s+(?:at|from|in)\s+(.+?))?(?:\.|,|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:the (?:right|better) person (?:is|would be))\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            re.IGNORECASE,
        ),
    ]

    for pattern in referral_patterns:
        match = pattern.search(combined)
        if match:
            name = match.group(1).strip()
            org = match.group(2).strip() if match.lastindex >= 2 and match.group(2) else None
            # Filter out common false positives
            if name.lower() in ("our", "the", "my", "your", "a", "an", "someone", "anybody"):
                continue
            return {"name": name, "organization": org}

    return None


def detect_meeting(parsed: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Detect if a meeting was booked during the call."""
    meeting_raw = parsed.get("meeting_booked")
    if not meeting_raw:
        return None

    if isinstance(meeting_raw, str) and meeting_raw.lower().startswith("yes"):
        # Extract date/time info
        detail = meeting_raw.replace("yes", "").replace("Yes", "").strip(" —-–:")
        return {
            "booked": True,
            "detail": detail if detail else "Time TBD",
            "contact": parsed.get("spoke_with"),
            "organization": parsed.get("organization"),
            "email": parsed.get("contact_email"),
        }

    return None


def detect_email_promise(parsed: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Detect if the AI promised to send follow-up information."""
    follow_up = parsed.get("follow_up", "") or ""
    notes = parsed.get("notes", "") or ""
    combined = f"{follow_up} {notes}".lower()

    email_signals = [
        "send", "email", "case study", "brochure", "information",
        "white paper", "documentation", "spec sheet", "quote",
        "pricing", "proposal",
    ]

    if any(signal in combined for signal in email_signals):
        return {
            "type": "follow_up_email",
            "detail": follow_up or notes,
            "to_email": parsed.get("contact_email"),
            "contact": parsed.get("spoke_with"),
            "organization": parsed.get("organization"),
        }

    return None


def calculate_lead_score(parsed: Dict[str, Any]) -> int:
    """
    Calculate a lead score (0-100) based on call outcome signals.

    Scoring:
      - Meeting booked: +40
      - Connected (spoke to someone): +15
      - High interest (4-5): +20
      - Medium interest (3): +10
      - Has pain points: +10
      - Knows current vendor (competitive intel): +5
      - Email collected: +5
      - Phone collected: +5
    """
    score = 0
    outcome = parsed.get("outcome", "")

    if outcome == "Meeting Booked":
        score += 40
    elif outcome == "Connected":
        score += 15

    interest = parsed.get("interest_level")
    if interest and interest >= 4:
        score += 20
    elif interest and interest >= 3:
        score += 10

    if parsed.get("pain_points"):
        score += 10
    if parsed.get("current_vendor"):
        score += 5
    if parsed.get("contact_email"):
        score += 5
    if parsed.get("contact_phone"):
        score += 5

    return min(score, 100)


# ── Action Handlers ────────────────────────────────────────────────────────────

def queue_follow_up(call_entry: Dict, parsed: Dict, referral: Optional[Dict],
                    meeting: Optional[Dict], email_promise: Optional[Dict],
                    lead_score: int, dry_run: bool = False) -> List[str]:
    """Queue all follow-up actions from a processed call. Returns list of actions taken."""
    actions = []

    if referral:
        entry = {
            "type": "referral",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_id": call_entry.get("call_id"),
            "from_account": call_entry.get("account_name", ""),
            "to_number": call_entry.get("to", ""),
            "referral_name": referral["name"],
            "referral_org": referral.get("organization"),
            "status": "pending",
        }
        if not dry_run:
            with open(FOLLOW_UP_QUEUE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        actions.append(f"Referral queued: {referral['name']} at {referral.get('organization', 'unknown')}")

    if meeting:
        entry = {
            "type": "meeting_booked",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_id": call_entry.get("call_id"),
            "account_name": call_entry.get("account_name", ""),
            "to_number": call_entry.get("to", ""),
            "contact": meeting.get("contact"),
            "organization": meeting.get("organization"),
            "detail": meeting.get("detail"),
            "email": meeting.get("email"),
            "status": "pending_confirmation",
        }
        if not dry_run:
            with open(MEETING_QUEUE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        actions.append(f"Meeting detected: {meeting.get('detail', 'TBD')} with {meeting.get('contact', 'unknown')}")

    if email_promise:
        entry = {
            "type": "email_follow_up",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_id": call_entry.get("call_id"),
            "account_name": call_entry.get("account_name", ""),
            "to_number": call_entry.get("to", ""),
            "to_email": email_promise.get("to_email"),
            "contact": email_promise.get("contact"),
            "organization": email_promise.get("organization"),
            "detail": email_promise.get("detail"),
            "status": "pending",
        }
        if not dry_run:
            with open(EMAIL_QUEUE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        actions.append(f"Email queued: {email_promise.get('detail', '')[:60]}")

    # High-value alert (score >= 50 or meeting booked)
    if lead_score >= 50 or meeting:
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_id": call_entry.get("call_id"),
            "account_name": call_entry.get("account_name", ""),
            "to_number": call_entry.get("to", ""),
            "outcome": parsed.get("outcome"),
            "lead_score": lead_score,
            "interest": parsed.get("interest_level"),
            "contact": parsed.get("spoke_with"),
            "meeting": meeting,
            "summary": parsed.get("raw_summary", "")[:200],
        }
        if not dry_run:
            with open(ALERTS_LOG, "a") as f:
                f.write(json.dumps(alert) + "\n")
            _post_slack_alert(alert)
        actions.append(f"🔥 High-value alert (score={lead_score})")

    return actions


def _post_slack_alert(alert: Dict) -> None:
    """Post a high-value call alert to Slack DM."""
    if not SLACK_TOKEN:
        return

    try:
        import requests
        emoji = "🔥" if alert.get("meeting") else "⭐"
        score = alert.get("lead_score", 0)
        text = (
            f"{emoji} *High-Value Call Alert* (Score: {score}/100)\n"
            f"📞 {alert.get('to_number', 'unknown')} — {alert.get('account_name', 'unknown')}\n"
            f"👤 {alert.get('contact', 'unknown')} | Outcome: {alert.get('outcome', '?')}\n"
        )
        if alert.get("meeting"):
            text += f"📅 Meeting: {alert['meeting'].get('detail', 'TBD')}\n"
        text += f"📝 {alert.get('summary', '')[:150]}"

        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_TOKEN}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": SLACK_DM, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[slack] Alert post failed: {e}")


# ── Processing State ───────────────────────────────────────────────────────────

def load_state() -> Dict:
    """Load processing state — tracks which call_ids have been processed."""
    if PROCESSING_STATE.exists():
        with open(PROCESSING_STATE) as f:
            return json.load(f)
    return {"processed": {}, "stats": {"total": 0, "connected": 0, "meetings": 0, "referrals": 0, "emails_queued": 0}}


def save_state(state: Dict) -> None:
    """Save processing state."""
    with open(PROCESSING_STATE, "w") as f:
        json.dump(state, f, indent=2)


# ── Core Processing ───────────────────────────────────────────────────────────

def process_single_call(call_entry: Dict, state: Dict, dry_run: bool = False, verbose: bool = True) -> Dict:
    """
    Process a single call entry through the full pipeline.

    Returns a result dict with parsed data and actions taken.
    """
    call_id = call_entry.get("call_id", "unknown")

    # Skip if already processed
    if call_id in state.get("processed", {}):
        if verbose:
            print(f"  ⏭  {call_id} — already processed")
        return {"skipped": True, "call_id": call_id}

    summary = call_entry.get("summary", "")
    parsed = parse_structured_summary(summary)

    # Detect signals
    referral = detect_referral(parsed)
    meeting = detect_meeting(parsed)
    email_promise = detect_email_promise(parsed)
    lead_score = calculate_lead_score(parsed)

    # Queue actions
    actions = queue_follow_up(
        call_entry, parsed, referral, meeting, email_promise, lead_score,
        dry_run=dry_run,
    )

    # Print result
    outcome = parsed.get("outcome", "?")
    interest = parsed.get("interest_level", "?")
    contact = parsed.get("spoke_with") or "unknown"
    to_num = call_entry.get("to", "?")

    if verbose:
        score_bar = "█" * (lead_score // 10) + "░" * (10 - lead_score // 10)
        prefix = "[DRY]" if dry_run else " ✅ "
        print(f"  {prefix} {call_id[:8]}.. | {to_num:>15s} | {outcome:<18s} | "
              f"Interest: {interest} | Score: [{score_bar}] {lead_score} | "
              f"Contact: {contact}")
        for action in actions:
            print(f"        → {action}")

    # Update state
    if not dry_run:
        state.setdefault("processed", {})[call_id] = {
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "outcome": outcome,
            "lead_score": lead_score,
            "actions": len(actions),
        }
        stats = state.setdefault("stats", {})
        stats["total"] = stats.get("total", 0) + 1
        if outcome == "Connected":
            stats["connected"] = stats.get("connected", 0) + 1
        if meeting:
            stats["meetings"] = stats.get("meetings", 0) + 1
        if referral:
            stats["referrals"] = stats.get("referrals", 0) + 1
        if email_promise:
            stats["emails_queued"] = stats.get("emails_queued", 0) + 1

    return {
        "skipped": False,
        "call_id": call_id,
        "parsed": parsed,
        "referral": referral,
        "meeting": meeting,
        "email_promise": email_promise,
        "lead_score": lead_score,
        "actions": actions,
    }


def scan_and_process(dry_run: bool = False, since_hours: Optional[float] = None) -> Dict:
    """
    Scan call_summaries.jsonl and process all unprocessed entries.

    Args:
        dry_run: If True, don't write any state or queue files
        since_hours: If set, only process entries from the last N hours

    Returns:
        Summary dict with counts
    """
    state = load_state()
    results = {"processed": 0, "skipped": 0, "errors": 0, "high_value": 0}

    # Find all JSONL files with call data
    files_to_scan = []
    if SUMMARIES_FILE.exists() and SUMMARIES_FILE.stat().st_size > 0:
        files_to_scan.append(SUMMARIES_FILE)
    if ARCHIVE_FILE.exists():
        files_to_scan.append(ARCHIVE_FILE)

    if not files_to_scan:
        print("No call summary files found.")
        return results

    cutoff = None
    if since_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    for filepath in files_to_scan:
        print(f"\n📂 Scanning: {filepath.name}")
        with open(filepath) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    results["errors"] += 1
                    continue

                # Time filter
                if cutoff:
                    ts = entry.get("timestamp", "")
                    try:
                        entry_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if entry_time < cutoff:
                            continue
                    except Exception:
                        pass

                result = process_single_call(entry, state, dry_run=dry_run)
                if result.get("skipped"):
                    results["skipped"] += 1
                else:
                    results["processed"] += 1
                    if result.get("lead_score", 0) >= 50:
                        results["high_value"] += 1

    if not dry_run:
        save_state(state)

    return results


def show_stats() -> None:
    """Display processing statistics."""
    state = load_state()
    stats = state.get("stats", {})
    processed = state.get("processed", {})

    print("\n📊 Post-Call Processing Statistics")
    print("=" * 50)
    print(f"  Total processed:    {stats.get('total', 0)}")
    print(f"  Connected calls:    {stats.get('connected', 0)}")
    print(f"  Meetings booked:    {stats.get('meetings', 0)}")
    print(f"  Referrals found:    {stats.get('referrals', 0)}")
    print(f"  Emails queued:      {stats.get('emails_queued', 0)}")
    print(f"  Unique call IDs:    {len(processed)}")

    # Recent processing
    if processed:
        recent = sorted(processed.items(), key=lambda x: x[1].get("processed_at", ""), reverse=True)[:5]
        print(f"\n  Last 5 processed:")
        for cid, info in recent:
            print(f"    {cid[:12]}.. | {info.get('outcome', '?'):15s} | Score: {info.get('lead_score', 0)}")

    # Queue depths
    for name, path in [
        ("Follow-up queue", FOLLOW_UP_QUEUE),
        ("Meeting queue", MEETING_QUEUE),
        ("Email queue", EMAIL_QUEUE),
        ("High-value alerts", ALERTS_LOG),
    ]:
        count = 0
        if path.exists():
            with open(path) as f:
                count = sum(1 for line in f if line.strip())
        print(f"  {name:20s}: {count} entries")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Post-call processing pipeline")
    parser.add_argument("--scan", action="store_true", help="Scan and process all unprocessed calls")
    parser.add_argument("--call-id", type=str, help="Process a single call by ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing state")
    parser.add_argument("--stats", action="store_true", help="Show processing statistics")
    parser.add_argument("--reprocess", action="store_true", help="Reprocess (ignore processed state)")
    parser.add_argument("--since", type=str, help="Only process calls from last Nh (e.g., 24h, 72h)")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.reprocess:
        # Clear state for reprocessing
        if PROCESSING_STATE.exists():
            PROCESSING_STATE.unlink()
            print("🔄 Processing state cleared — will reprocess all entries")

    since_hours = None
    if args.since:
        match = re.match(r"(\d+)h?", args.since)
        if match:
            since_hours = float(match.group(1))

    if args.call_id:
        # Process single call
        state = load_state()
        # Find the call in log files
        found = False
        for filepath in [SUMMARIES_FILE, ARCHIVE_FILE]:
            if not filepath.exists():
                continue
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("call_id") == args.call_id:
                        process_single_call(entry, state, dry_run=args.dry_run)
                        if not args.dry_run:
                            save_state(state)
                        found = True
                        break
                if found:
                    break
        if not found:
            print(f"❌ Call ID {args.call_id} not found in log files")
            sys.exit(1)
    elif args.scan or not any([args.stats, args.call_id]):
        # Default: scan all
        print("🔍 Scanning call summaries for unprocessed entries...")
        results = scan_and_process(dry_run=args.dry_run, since_hours=since_hours)
        print(f"\n📋 Results: {results['processed']} processed, "
              f"{results['skipped']} skipped, {results['high_value']} high-value, "
              f"{results['errors']} errors")


if __name__ == "__main__":
    main()
