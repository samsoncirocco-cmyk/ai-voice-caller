#!/usr/bin/env python3
"""
run_k12_campaign.py — Dedicated K-12 campaign runner.

Filters the account DB for Education: Lower Education accounts (K-12 school
districts across IA/NE/SD), exports a fresh CSV, then drives them through
campaign_runner_v2.py with the k12.txt prompt.

After the run, posts a Slack summary to #call-blitz.

Usage
─────
  python3 run_k12_campaign.py                # live run (business hours only)
  python3 run_k12_campaign.py --dry-run      # research-only, no calls
  python3 run_k12_campaign.py --limit 20     # cap at 20 calls
  python3 run_k12_campaign.py --interval 180 # 3-min spacing
  python3 run_k12_campaign.py --force-hours  # skip time-of-day gate (testing)
  python3 run_k12_campaign.py --status       # show K-12 account stats and exit

Background
──────────
The K-12 vertical is identified in accounts.db as vertical='Education: Lower Education'.
The smart_router already classifies these correctly and routes them to prompts/k12.txt.
This script adds an explicit filter + dedicated CSV so K-12 campaigns can be tracked
independently.

Calling windows (enforced by campaign_runner_v2.py --business-hours):
  8:00–10:00 AM MST  (morning window)
  1:00–3:00 PM MST   (afternoon window)
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "campaigns" / "accounts.db"
K12_CSV = ROOT / "campaigns" / "k12-accounts.csv"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Slack ─────────────────────────────────────────────────────────────────────
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = "C0AFQ0FPYGM"  # #call-blitz

# ── K-12 vertical tag in DB ───────────────────────────────────────────────────
K12_VERTICAL = "Education: Lower Education"

VERTICAL_TAGS = [
    "Education: Lower Education",
    "K-12",
    "K12",
]


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_k12_accounts(status_filter=None):
    """Return list of dicts for all K-12 accounts in the DB."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join(["?" for _ in VERTICAL_TAGS])
    sql = f"SELECT * FROM accounts WHERE vertical IN ({placeholders})"
    params = list(VERTICAL_TAGS)
    if status_filter:
        sql += " AND call_status = ?"
        params.append(status_filter)
    sql += " ORDER BY created_at ASC"

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_k12_stats():
    """Return status breakdown for K-12 accounts."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    placeholders = ",".join(["?" for _ in VERTICAL_TAGS])
    cur.execute(
        f"SELECT call_status, COUNT(*) FROM accounts WHERE vertical IN ({placeholders}) "
        f"GROUP BY call_status",
        VERTICAL_TAGS,
    )
    stats = dict(cur.fetchall())
    cur.execute(
        f"SELECT COUNT(*) FROM accounts WHERE vertical IN ({placeholders})",
        VERTICAL_TAGS,
    )
    stats["_total"] = cur.fetchone()[0]
    conn.close()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────

def export_k12_csv(accounts) -> Path:
    """Write K-12 accounts to a CSV compatible with campaign_runner_v2.py."""
    K12_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(K12_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["phone", "name", "account", "notes"])
        for acct in accounts:
            phone = acct.get("phone", "").strip()
            name = acct.get("account_name", "").strip()
            state = acct.get("state", "")
            vertical = acct.get("vertical", "")
            sfdc_id = acct.get("sfdc_id", "")
            notes_parts = [
                f"State: {state}",
                f"Vertical: {vertical}",
                f"SFDC: {sfdc_id}" if sfdc_id else "",
                f"CallCount: {acct.get('call_count', 0)}",
            ]
            notes = " | ".join(p for p in notes_parts if p)
            writer.writerow([phone, name, name, notes])
    print(f"[k12] Exported {len(accounts)} accounts → {K12_CSV}")
    return K12_CSV


# ─────────────────────────────────────────────────────────────────────────────
# Slack
# ─────────────────────────────────────────────────────────────────────────────

def post_slack(text: str):
    if not SLACK_TOKEN:
        print(f"[slack] (no token) {text}")
        return
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
        if not resp.json().get("ok"):
            print(f"[slack] Error: {resp.json()}")
    except Exception as e:
        print(f"[slack] Failed: {e}")


def build_slack_summary(stats_before: dict, stats_after: dict, elapsed: float) -> str:
    total = stats_after.get("_total", 0)
    new_before = stats_before.get("new", 0)
    new_after = stats_after.get("new", 0)
    processed = new_before - new_after  # accounts that moved out of 'new'

    interested = stats_after.get("interested", 0)
    voicemail = stats_after.get("voicemail", 0)
    no_answer = stats_after.get("no_answer", 0)
    not_interested = stats_after.get("not_interested", 0)
    dnc = stats_after.get("dnc", 0)
    converted = stats_after.get("converted", 0)
    referral = stats_after.get("referral_given", 0)

    failures = dnc  # DNC is the closest to "failure" in this context

    lines = [
        f":school: *K-12 Campaign Run — {datetime.now().strftime('%Y-%m-%d %H:%M MST')}*",
        f">*Total K-12 accounts:* {total}",
        f">*Processed this run:* {processed}",
        f">*Remaining (new):* {new_after}",
        "",
        "*Outcome breakdown:*",
        f">  :handshake: Interested: {interested}",
        f">  :telephone_receiver: Voicemail: {voicemail}",
        f">  :no_bell: No answer: {no_answer}",
        f">  :x: Not interested: {not_interested}",
        f">  :recycle: Referral given: {referral}",
        f">  :warning: DNC/Failures: {failures}",
        "",
        f":stopwatch: Elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s",
    ]
    if converted:
        lines.append(f":star: *Converted to opportunity: {converted}*")
    if interested:
        lines.append(":bell: Hot leads moved to Samson for follow-up!")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="K-12 campaign runner")
    parser.add_argument("--dry-run", action="store_true", help="Research only, no calls")
    parser.add_argument("--limit", type=int, default=0, help="Max calls to place (0=all)")
    parser.add_argument("--interval", type=int, default=240, help="Seconds between calls")
    parser.add_argument("--force-hours", action="store_true", help="Skip business hours gate")
    parser.add_argument("--status", action="store_true", help="Print K-12 stats and exit")
    parser.add_argument("--status-only", action="store_true", help="Alias for --status")
    args = parser.parse_args()

    # ── load .env ────────────────────────────────────────────────────────────
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # Also try workspace .env
    workspace_env = ROOT.parent.parent / ".env"
    if workspace_env.exists():
        for line in workspace_env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # ── status mode ──────────────────────────────────────────────────────────
    if args.status or args.status_only:
        stats = get_k12_stats()
        print(f"\n{'─'*50}")
        print(f"  K-12 Account Stats (vertical: {K12_VERTICAL!r})")
        print(f"{'─'*50}")
        for k, v in sorted(stats.items()):
            label = "_total" if k == "_total" else k
            print(f"  {label:<20} {v}")
        print()
        return

    print(f"\n[k12] Starting K-12 campaign — {datetime.now().isoformat()}")
    print(f"[k12] Prompt: prompts/k12.txt")
    print(f"[k12] DB: {DB_PATH}")

    # ── fetch K-12 accounts ───────────────────────────────────────────────────
    accounts = get_k12_accounts(status_filter="new")
    if not accounts:
        msg = ":school: K-12 Campaign: No new accounts to call. All 174 accounts already processed!"
        print(f"[k12] {msg}")
        post_slack(msg)
        return

    print(f"[k12] Found {len(accounts)} new K-12 accounts to call.")
    stats_before = get_k12_stats()

    # ── export CSV ───────────────────────────────────────────────────────────
    csv_path = export_k12_csv(accounts)

    # ── build command ─────────────────────────────────────────────────────────
    cmd = [
        sys.executable,
        str(ROOT / "campaign_runner_v2.py"),
        str(csv_path),
        "--prompt", "prompts/k12.txt",
        "--voice", "openai.onyx",
        "--interval", str(args.interval),
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if not args.force_hours:
        cmd.append("--business-hours")

    print(f"[k12] Running: {' '.join(cmd)}")
    post_slack(
        f":school: *K-12 Campaign Starting* — {len(accounts)} accounts queued\n"
        f">Prompt: `k12.txt` | Interval: {args.interval}s | Limit: {args.limit or 'all'}\n"
        f">{'DRY RUN — no calls placed' if args.dry_run else 'LIVE — calls will be placed during business hours'}"
    )

    start = time.time()
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), timeout=3600)  # SAFETY 2026-03-09: 1-hour max (was 4 hours)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
        print("[k12] Campaign timed out after 4 hours.")
    except KeyboardInterrupt:
        exit_code = -2
        print("[k12] Campaign interrupted.")
    elapsed = time.time() - start

    # ── post Slack summary ────────────────────────────────────────────────────
    stats_after = get_k12_stats()
    summary = build_slack_summary(stats_before, stats_after, elapsed)
    if exit_code != 0:
        summary += f"\n\n:warning: *Exit code: {exit_code}* — check `logs/` for details."
    post_slack(summary)
    print(f"\n[k12] Done. Posted summary to Slack.")
    print(summary)

    sys.exit(0 if exit_code == 0 else 1)


if __name__ == "__main__":
    main()
