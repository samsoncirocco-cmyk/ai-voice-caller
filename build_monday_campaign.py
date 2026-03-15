#!/usr/bin/env python3
"""
Build Monday Mar 17 2026 calling campaign for Samson Cirocco.
E-Rate accounts (SD/NE/IA with open opps) + inactive follow-ups.
"""
import csv
import json
import subprocess
import re
import sys
import os
import requests
from pathlib import Path
from datetime import datetime, date

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = BASE_DIR / "campaigns" / "monday-mar17-2026.csv"

GATEWAY_URL = "http://192.168.0.109:4000/v1/chat/completions"
GATEWAY_TOKEN = "sk-9MPo9UCKsAIU3Ykn9JmcYA"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
OWNER_ID = "005Hr00000INgbqIAD"

INACTIVE_CUTOFF = "2026-02-12"   # 30 days before Mar 14


def sf_query(q):
    cmd = ["sf", "data", "query", "--query", q, "--json", "--target-org", "production"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.split('\n')
    json_start = next((i for i, l in enumerate(lines) if l.strip().startswith('{')), 0)
    data = json.loads('\n'.join(lines[json_start:]))
    if data["status"] != 0:
        raise Exception(f"SFDC error: {data}")
    return data["result"]["records"]


def normalize_phone(raw):
    """Strip to digits and format as +1XXXXXXXXXX."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    return raw  # fallback: return as-is


ERATE_TRACKS = {
    "Solution - Front Runner": (
        "Hi, this is Samson with Fortinet — we're in a strong position on your 2026 E-Rate project "
        "and I wanted to touch base before the submission deadline to confirm we have everything lined up on your end."
    ),
    "Pending Initial Meeting": (
        "Hi, this is Samson with Fortinet — I'm reaching out to schedule a quick meeting on your 2026 E-Rate opportunity; "
        "the window is closing fast and I want to make sure we get your proposal submitted in time."
    ),
    "Qualification (10%)": (
        "Hi, this is Samson with Fortinet — following up on your 2026 E-Rate qualification to see if you've "
        "identified your top priorities so I can get you a proposal before the filing deadline."
    ),
    "Prospecting": (
        "Hi, this is Samson from Fortinet — I wanted to reach out because your organization may qualify for "
        "E-Rate Category 2 funding this year, and Fortinet's firewall and switch solutions can often be fully covered."
    ),
}

def gen_talk_track(account_name, state, call_type, stage=None):
    """Generate a talk track — try gateway LLM first, fall back to curated templates."""
    if call_type == "erate":
        prompt = (
            f"Write a 1-2 sentence phone call opener for a Fortinet sales rep calling "
            f"{account_name} in {state} about their open E-Rate opportunity "
            f"(stage: {stage}). Be concise, friendly, and specific to E-Rate funding deadlines. "
            f"Do not use placeholders. Output only the talk track text, nothing else."
        )
    else:
        prompt = (
            f"Write a 1-2 sentence phone call opener for a Fortinet sales rep "
            f"doing a follow-up check-in with {account_name} in {state}. "
            f"They haven't been contacted in over 30 days. Be warm and brief. "
            f"Do not use placeholders. Output only the talk track text, nothing else."
        )

    # Try gateway first (fast)
    try:
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120,
            "temperature": 0.7,
        }
        resp = requests.post(
            GATEWAY_URL,
            headers={"Authorization": f"Bearer {GATEWAY_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass  # gateway down, use templates

    # Curated templates (instant, no LLM needed)
    if call_type == "erate":
        track = ERATE_TRACKS.get(stage, ERATE_TRACKS["Prospecting"])
        return track.replace("your 2026 E-Rate project", f"your 2026 E-Rate project at {account_name}")
    else:
        return (
            f"Hi, this is Samson from Fortinet — just checking in with {account_name} "
            f"to see how things are going and whether there's anything on the network or security side we can help with this spring."
        )


def main():
    print("🚀 Building Monday Mar 17 2026 calling campaign...\n")

    # ── 1. Pull E-Rate opportunities ──────────────────────────────────────────
    print("📡 Querying open E-Rate opportunities...")
    erate_opps = sf_query(
        f"SELECT Id, Name, StageName, Account.Id, Account.Name, Account.Phone, "
        f"Account.BillingState, Account.BillingCity, CloseDate "
        f"FROM Opportunity "
        f"WHERE OwnerId='{OWNER_ID}' AND IsClosed=false "
        f"AND (Name LIKE '%E-Rate%' OR Name LIKE '%Erate%' OR Name LIKE '%eRate%')"
    )
    print(f"  → {len(erate_opps)} open E-Rate opps")

    # Deduplicate by AccountId, keep highest stage
    STAGE_RANK = {
        "Solution - Front Runner": 5,
        "Pending Initial Meeting": 4,
        "Qualification (10%)": 3,
        "Prospecting": 2,
    }
    erate_accounts = {}
    for opp in erate_opps:
        acct = opp.get("Account", {})
        acct_id = acct.get("Id")
        if not acct_id or not acct.get("Phone"):
            continue
        rank = STAGE_RANK.get(opp["StageName"], 1)
        if acct_id not in erate_accounts or rank > erate_accounts[acct_id]["rank"]:
            erate_accounts[acct_id] = {
                "account_name": acct.get("Name", "").replace(",", " ").strip(),
                "phone": normalize_phone(acct.get("Phone", "")),
                "state": acct.get("BillingState", ""),
                "call_type": "erate",
                "stage": opp["StageName"],
                "rank": rank,
            }

    erate_list = list(erate_accounts.values())
    print(f"  → {len(erate_list)} unique E-Rate accounts with phones\n")

    # ── 2. Pull inactive follow-up accounts ───────────────────────────────────
    print("📡 Querying 30+ day inactive accounts...")
    inactive_recs = sf_query(
        f"SELECT Id, Name, Phone, BillingState, BillingCity, LastActivityDate "
        f"FROM Account "
        f"WHERE OwnerId='{OWNER_ID}' AND Phone != null "
        f"AND BillingState IN ('Iowa','Nebraska','South Dakota') "
        f"AND (LastActivityDate < {INACTIVE_CUTOFF} OR LastActivityDate = null) "
        f"ORDER BY LastActivityDate ASC NULLS FIRST "
        f"LIMIT 100"
    )
    print(f"  → {len(inactive_recs)} inactive accounts found")

    # Exclude accounts already in E-Rate list, pick best 20
    erate_acct_ids = set(erate_accounts.keys())
    followup_list = []
    # Prefer accounts with an actual LastActivityDate (had some history) over null
    has_activity = [r for r in inactive_recs if r.get("LastActivityDate") and r["Id"] not in erate_acct_ids]
    no_activity   = [r for r in inactive_recs if not r.get("LastActivityDate") and r["Id"] not in erate_acct_ids]

    # Take up to 20 follow-ups: prefer those with some history first
    candidates = has_activity + no_activity
    target_followup = 25 - len(erate_list)   # aim for total ~25

    for rec in candidates[:target_followup]:
        followup_list.append({
            "account_name": rec["Name"].replace(",", " ").strip(),
            "phone": normalize_phone(rec["Phone"]),
            "state": rec.get("BillingState", ""),
            "call_type": "followup",
            "stage": None,
            "last_activity": rec.get("LastActivityDate", "never"),
        })

    print(f"  → {len(followup_list)} follow-up accounts selected\n")

    # ── 3. Generate talk tracks ───────────────────────────────────────────────
    all_accounts = erate_list + followup_list
    print(f"📝 Generating talk tracks for {len(all_accounts)} accounts...")

    rows = []
    for i, acc in enumerate(all_accounts, 1):
        print(f"  [{i}/{len(all_accounts)}] {acc['account_name']} ({acc['call_type']})")
        track = gen_talk_track(
            acc["account_name"],
            acc["state"],
            acc["call_type"],
            acc.get("stage"),
        )
        rows.append({
            "account_name": acc["account_name"],
            "phone": acc["phone"],
            "state": acc["state"],
            "call_type": acc["call_type"],
            "talk_track": track,
        })

    # ── 4. Write CSV ──────────────────────────────────────────────────────────
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["account_name", "phone", "state", "call_type", "talk_track"])
        writer.writeheader()
        writer.writerows(rows)

    erate_count = sum(1 for r in rows if r["call_type"] == "erate")
    followup_count = sum(1 for r in rows if r["call_type"] == "followup")
    print(f"\n✅ Campaign CSV written: {OUTPUT_CSV}")
    print(f"   Total: {len(rows)} | E-Rate: {erate_count} | Follow-up: {followup_count}")

    return len(rows), erate_count, followup_count


if __name__ == "__main__":
    main()
