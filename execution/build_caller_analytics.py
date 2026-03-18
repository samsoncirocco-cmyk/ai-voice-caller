#!/usr/bin/env python3
"""
build_caller_analytics.py — AI Voice Caller Performance Analytics Dashboard

Reads from:
  - logs/campaign_log.jsonl       (all outbound calls)
  - logs/call_summaries.jsonl     (post-call AI summaries)
  - campaigns/performance_stats.json  (prompt variant stats)
  - campaigns/monday-mar17-2026.csv   (today's targets)

Outputs:
  - ../../projects/second-brain/public/caller-analytics.html

Usage:
  python3 execution/build_caller_analytics.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    MST = ZoneInfo("America/Phoenix")
except Exception:
    MST = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKSPACE = ROOT.parent.parent  # .openclaw/workspace
SECOND_BRAIN = WORKSPACE / "projects" / "second-brain" / "public"
SECOND_BRAIN.mkdir(parents=True, exist_ok=True)

CAMPAIGN_LOG = ROOT / "logs" / "campaign_log.jsonl"
CALL_SUMMARIES = ROOT / "logs" / "call_summaries.jsonl"
HIGH_VALUE_ALERTS = ROOT / "logs" / "high-value-alerts.jsonl"
PERF_STATS = ROOT / "campaigns" / "performance_stats.json"

# ── Data Loaders ─────────────────────────────────────────────────────────────

def load_campaign_log():
    records = []
    if not CAMPAIGN_LOG.exists():
        return records
    with open(CAMPAIGN_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def load_call_summaries():
    records = []
    if not CALL_SUMMARIES.exists():
        return records
    with open(CALL_SUMMARIES) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                # Skip ping record
                if d.get("raw", {}).get("ping"):
                    continue
                records.append(d)
            except Exception:
                pass
    return records


def parse_summary_field(summary: str, field: str) -> str:
    """Extract a field value from the structured summary text."""
    for line in summary.split("\n"):
        if f"- {field}:" in line:
            return line.split(":", 1)[1].strip()
    return ""


def load_high_value_alerts():
    records = []
    if not HIGH_VALUE_ALERTS.exists():
        return records
    with open(HIGH_VALUE_ALERTS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def load_perf_stats():
    if not PERF_STATS.exists():
        return {}
    try:
        with open(PERF_STATS) as f:
            return json.load(f)
    except Exception:
        return {}


def load_all_campaign_csvs():
    """Load all CSV campaign files and aggregate targets."""
    campaigns_dir = ROOT / "campaigns"
    targets = []
    for csv_file in sorted(campaigns_dir.glob("*.csv")):
        if csv_file.name in ("k12-accounts.csv", "sled-territory-832.csv"):
            continue
        try:
            import csv
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_campaign_file"] = csv_file.name
                    targets.append(row)
        except Exception:
            pass
    return targets


# ── Analytics Engine ─────────────────────────────────────────────────────────

def build_analytics():
    campaign_log = load_campaign_log()
    summaries = load_call_summaries()
    alerts = load_high_value_alerts()
    perf_raw = load_perf_stats()
    targets = load_all_campaign_csvs()

    # Campaign log stats
    total_calls = len(campaign_log)
    successful_calls = sum(1 for c in campaign_log if c.get("result") == "success")
    failed_calls = total_calls - successful_calls

    # Calls by date
    calls_by_date = defaultdict(int)
    for c in campaign_log:
        ts = c.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                if MST:
                    dt = dt.astimezone(MST)
                calls_by_date[dt.strftime("%Y-%m-%d")] += 1
            except Exception:
                pass

    # Calls by account name
    calls_by_account = defaultdict(list)
    for c in campaign_log:
        calls_by_account[c.get("account", "Unknown")].append(c)

    # Call summaries analysis
    outcomes = defaultdict(int)
    interest_scores = []
    vendors_mentioned = defaultdict(int)
    meetings_booked = 0
    warm_leads = []  # interest >= 3
    
    for s in summaries:
        summary_text = s.get("summary", "")
        
        outcome = parse_summary_field(summary_text, "Call outcome")
        if outcome:
            outcomes[outcome.lower()] += 1
        
        interest_str = parse_summary_field(summary_text, "Interest level")
        try:
            score = int(interest_str)
            interest_scores.append(score)
        except Exception:
            pass
        
        meeting = parse_summary_field(summary_text, "Meeting booked")
        if "yes" in meeting.lower():
            meetings_booked += 1
        
        # Vendor intel
        vendor_re = re.compile(r"\b(cisco|meraki|palo alto|sonicwall|aruba|sophos|checkpoint|juniper|watchguard|crowdstrike)\b", re.I)
        for match in vendor_re.findall(summary_text):
            vendors_mentioned[match.lower()] += 1
        
        # Warm leads
        try:
            score = int(interest_str)
            if score >= 3:
                account = s.get("account_name", "") or parse_summary_field(summary_text, "Organization")
                spoke_with = parse_summary_field(summary_text, "Spoke with")
                role = parse_summary_field(summary_text, "Role")
                email = parse_summary_field(summary_text, "Contact email")
                phone = parse_summary_field(summary_text, "Contact direct phone")
                notes = parse_summary_field(summary_text, "Notes")
                ts = s.get("timestamp", "")[:10]
                warm_leads.append({
                    "account": account or "Unknown",
                    "score": score,
                    "spoke_with": spoke_with,
                    "role": role,
                    "email": email,
                    "phone": phone,
                    "notes": notes[:200],
                    "date": ts,
                })
        except Exception:
            pass

    # Performance stats by vertical / prompt
    vertical_stats = {}
    for prompt_path, verticals in perf_raw.get("prompt_variant", {}).items():
        prompt_name = Path(prompt_path).stem
        for vertical, stats in verticals.items():
            key = f"{vertical}"
            if key not in vertical_stats:
                vertical_stats[key] = {"answered": 0, "voicemail": 0, "no_answer": 0,
                                        "interested": 0, "not_interested": 0}
            for k in vertical_stats[key]:
                vertical_stats[key][k] += stats.get(k, 0)

    # Campaign targets breakdown
    target_by_type = defaultdict(int)
    target_by_state = defaultdict(int)
    for t in targets:
        call_type = t.get("call_type", t.get("type", "unknown"))
        state = t.get("state", t.get("State", "unknown"))
        target_by_type[call_type] += 1
        target_by_state[state] += 1

    # Incorporate high-value alerts as warm leads
    for alert in alerts:
        outcome = alert.get("outcome", "")
        interest = alert.get("interest", 0)
        lead_score = alert.get("lead_score", 0)
        account = alert.get("account_name") or ""
        contact = alert.get("contact") or "unknown"
        summary_text = alert.get("summary", "")
        ts = alert.get("timestamp", "")[:10]
        
        if "meeting" in outcome.lower():
            meetings_booked += 1
        
        if interest >= 3 or lead_score >= 50:
            # Check if already in warm leads
            existing = [w for w in warm_leads if w["account"] == account]
            if not existing:
                notes_snippet = summary_text[:200] if summary_text else ""
                warm_leads.append({
                    "account": account or "Unknown",
                    "score": interest,
                    "spoke_with": contact,
                    "role": parse_summary_field(summary_text, "Role"),
                    "email": parse_summary_field(summary_text, "Contact email"),
                    "phone": parse_summary_field(summary_text, "Contact direct phone"),
                    "notes": f"[Lead Score: {lead_score}/100] {notes_snippet}",
                    "date": ts,
                    "outcome": outcome,
                })

    # Latest campaign date  
    latest_campaign_date = max(calls_by_date.keys()) if calls_by_date else "N/A"
    
    avg_interest = sum(interest_scores) / len(interest_scores) if interest_scores else 0

    return {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "meetings_booked": meetings_booked,
        "warm_leads": warm_leads,
        "outcomes": dict(outcomes),
        "interest_scores": interest_scores,
        "avg_interest": round(avg_interest, 1),
        "vendors_mentioned": dict(vendors_mentioned),
        "vertical_stats": vertical_stats,
        "calls_by_date": dict(calls_by_date),
        "target_by_type": dict(target_by_type),
        "target_by_state": dict(target_by_state),
        "latest_campaign_date": latest_campaign_date,
        "total_targets": len(targets),
        "summaries_count": len(summaries),
        "alerts_count": len(alerts),
    }


# ── HTML Builder ─────────────────────────────────────────────────────────────

def build_html(data: dict) -> str:
    now_str = datetime.now().strftime("%B %d, %Y %I:%M %p MST")

    warm_leads_html = ""
    if data["warm_leads"]:
        for lead in sorted(data["warm_leads"], key=lambda x: -x["score"]):
            score = lead["score"]
            score_color = "#ff4444" if score >= 4 else "#ffaa00"
            email_link = f'<a href="mailto:{lead["email"]}" style="color:#7c3aed">{lead["email"]}</a>' if lead["email"] not in ("none", "", "unknown") else "—"
            phone_link = f'<a href="tel:{lead["phone"]}" style="color:#7c3aed">{lead["phone"]}</a>' if lead["phone"] not in ("none", "", "unknown") else "—"
            warm_leads_html += f"""
            <div class="lead-card">
              <div class="lead-header">
                <span class="lead-name">{lead['account']}</span>
                <span class="interest-badge" style="background:{score_color}">★ {score}/5</span>
              </div>
              <div class="lead-meta">
                {f'<span>👤 {lead["spoke_with"]} — {lead["role"]}</span>' if lead["spoke_with"] not in ("unknown","") else ""}
                {f'<span>📧 {email_link}</span>' if email_link != "—" else ""}
                {f'<span>📞 {phone_link}</span>' if phone_link != "—" else ""}
                <span>📅 {lead["date"]}</span>
              </div>
              {f'<div class="lead-notes">{lead["notes"]}</div>' if lead["notes"] else ""}
            </div>"""
    else:
        warm_leads_html = '<p style="color:#666;text-align:center;padding:24px">No warm leads yet — keep calling! 🎯</p>'

    # Vertical table rows
    vertical_rows = ""
    for vertical, stats in data["vertical_stats"].items():
        total = stats["answered"] + stats["voicemail"] + stats["no_answer"]
        answer_rate = f"{stats['answered']/total*100:.0f}%" if total > 0 else "—"
        interest_pct = f"{stats['interested']/stats['answered']*100:.0f}%" if stats["answered"] > 0 else "—"
        vertical_rows += f"""
        <tr>
          <td><span class="vertical-badge vertical-{vertical.lower().replace(' ','_')}">{vertical.title()}</span></td>
          <td>{total}</td>
          <td>{stats['answered']}</td>
          <td>{stats['voicemail']}</td>
          <td>{answer_rate}</td>
          <td>{stats['interested']}</td>
          <td>{interest_pct}</td>
        </tr>"""

    # Outcomes chart data
    outcome_labels = json.dumps(list(data["outcomes"].keys()))
    outcome_values = json.dumps(list(data["outcomes"].values()))
    
    # Timeline data
    date_labels = json.dumps(sorted(data["calls_by_date"].keys()))
    date_values = json.dumps([data["calls_by_date"][d] for d in sorted(data["calls_by_date"].keys())])

    # Vendor intel
    vendor_html = ""
    if data["vendors_mentioned"]:
        for vendor, count in sorted(data["vendors_mentioned"].items(), key=lambda x: -x[1]):
            vendor_html += f'<div class="vendor-chip">{vendor.title()} <span class="vendor-count">{count}×</span></div>'
    else:
        vendor_html = '<span style="color:#666">None detected yet</span>'

    # Interest distribution
    scores = data["interest_scores"]
    score_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for s in scores:
        if s in score_dist:
            score_dist[s] += 1
    score_labels = json.dumps([f"★{i}" for i in range(1, 6)])
    score_values = json.dumps([score_dist[i] for i in range(1, 6)])

    success_rate = f"{data['successful_calls']/data['total_calls']*100:.0f}%" if data["total_calls"] > 0 else "0%"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Caller Analytics | Fortinet SLED</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f0f13;
    --surface: #1a1a24;
    --surface2: #22222e;
    --border: #2a2a3a;
    --accent: #7c3aed;
    --accent2: #10b981;
    --accent3: #f59e0b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --danger: #ef4444;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Inter', -apple-system, sans-serif; min-height: 100vh; }}

  .header {{
    background: linear-gradient(135deg, #1a0a2e 0%, #0f0f13 50%, #0a1a20 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .header-left h1 {{ font-size: 1.5rem; font-weight: 700; }}
  .header-left h1 span {{ color: var(--accent); }}
  .header-left p {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
  .header-right {{ display: flex; gap: 12px; align-items: center; }}
  .live-badge {{
    background: var(--accent2); color: white; font-size: 0.7rem; font-weight: 700;
    padding: 4px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.05em;
    display: flex; align-items: center; gap: 6px;
  }}
  .live-dot {{ width: 6px; height: 6px; background: white; border-radius: 50%; animation: pulse 1.5s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.4 }} }}

  .nav {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 32px; display: flex; gap: 0; }}
  .nav a {{
    color: var(--muted); text-decoration: none; font-size: 0.85rem; font-weight: 500;
    padding: 14px 18px; border-bottom: 2px solid transparent; transition: all .2s; display: block;
  }}
  .nav a:hover, .nav a.active {{ color: var(--text); border-color: var(--accent); }}

  .main {{ padding: 24px 32px; max-width: 1400px; margin: 0 auto; }}

  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; position: relative; overflow: hidden;
  }}
  .kpi::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
  }}
  .kpi-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
  .kpi-value {{ font-size: 2rem; font-weight: 800; }}
  .kpi-sub {{ font-size: 0.75rem; color: var(--muted); margin-top: 4px; }}
  .kpi.green .kpi-value {{ color: var(--accent2); }}
  .kpi.amber .kpi-value {{ color: var(--accent3); }}
  .kpi.purple .kpi-value {{ color: var(--accent); }}
  .kpi.red .kpi-value {{ color: var(--danger); }}

  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }}

  .card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px;
  }}
  .card h2 {{ font-size: 0.9rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
  .card h2 .icon {{ font-size: 1.1rem; }}

  .chart-container {{ position: relative; height: 200px; }}

  /* Vertical performance table */
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 12px; border-bottom: 1px solid rgba(42,42,58,0.5); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(124,58,237,0.05); }}

  .vertical-badge {{
    display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600;
  }}
  .vertical-k12 {{ background: rgba(124,58,237,.2); color: #a78bfa; }}
  .vertical-government {{ background: rgba(16,185,129,.2); color: #34d399; }}
  .vertical-higher_ed {{ background: rgba(245,158,11,.2); color: #fbbf24; }}
  .vertical-other {{ background: rgba(148,163,184,.2); color: #94a3b8; }}

  /* Warm leads */
  .lead-card {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-bottom: 12px;
  }}
  .lead-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .lead-name {{ font-weight: 700; font-size: 0.95rem; }}
  .interest-badge {{ padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; color: white; }}
  .lead-meta {{ display: flex; flex-wrap: wrap; gap: 12px; font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }}
  .lead-meta span {{ display: flex; align-items: center; gap: 4px; }}
  .lead-notes {{ font-size: 0.8rem; color: var(--muted); line-height: 1.5; background: rgba(0,0,0,.3); padding: 10px; border-radius: 8px; }}

  /* Vendor chips */
  .vendor-chip {{
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.2);
    color: #fc8181; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; margin: 4px;
  }}
  .vendor-count {{ background: rgba(239,68,68,.2); border-radius: 10px; padding: 1px 6px; font-size: 0.7rem; font-weight: 700; }}

  .full-width {{ grid-column: 1 / -1; }}
  .text-green {{ color: var(--accent2); }}
  .text-amber {{ color: var(--accent3); }}
  .text-purple {{ color: var(--accent); }}
  .text-muted {{ color: var(--muted); }}

  .footer {{ text-align: center; padding: 24px; color: var(--muted); font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 24px; }}

  @media (max-width: 768px) {{
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
    .main {{ padding: 16px; }}
    .header {{ flex-direction: column; gap: 12px; align-items: flex-start; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>📞 AI Caller <span>Analytics</span></h1>
    <p>Voice Caller Performance · Fortinet SLED Territory · Updated {now_str}</p>
  </div>
  <div class="header-right">
    <div class="live-badge"><div class="live-dot"></div> Live Data</div>
  </div>
</div>

<div class="nav">
  <a href="/gm">🌅 Good Morning</a>
  <a href="/pipeline">📊 Pipeline</a>
  <a href="/callsheet">📞 Call Sheet</a>
  <a href="/caller-analytics" class="active">🤖 AI Caller</a>
  <a href="/mobile">📱 Mobile</a>
  <a href="/next-action">⚡ Next Action</a>
  <a href="/intelligence">🧠 Intelligence</a>
  <a href="/">🏠 Home</a>
</div>

<div class="main">

  <!-- KPI Row -->
  <div class="kpi-grid">
    <div class="kpi purple">
      <div class="kpi-label">Total Calls Placed</div>
      <div class="kpi-value">{data['total_calls']}</div>
      <div class="kpi-sub">Across all campaigns</div>
    </div>
    <div class="kpi green">
      <div class="kpi-label">Connected</div>
      <div class="kpi-value">{data['successful_calls']}</div>
      <div class="kpi-sub">{success_rate} delivery rate</div>
    </div>
    <div class="kpi amber">
      <div class="kpi-label">Avg Interest Score</div>
      <div class="kpi-value">{data['avg_interest']}/5</div>
      <div class="kpi-sub">On answered calls</div>
    </div>
    <div class="kpi green">
      <div class="kpi-label">Meetings Booked</div>
      <div class="kpi-value">{data['meetings_booked']}</div>
      <div class="kpi-sub">From AI conversations</div>
    </div>
    <div class="kpi purple">
      <div class="kpi-label">Warm Leads (★3+)</div>
      <div class="kpi-value">{len(data['warm_leads'])}</div>
      <div class="kpi-sub">Need follow-up</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Call Summaries</div>
      <div class="kpi-value">{data['summaries_count']}</div>
      <div class="kpi-sub">Full AI transcripts</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Campaign Targets</div>
      <div class="kpi-value">{data['total_targets']}</div>
      <div class="kpi-sub">In active lists</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Last Campaign</div>
      <div class="kpi-value" style="font-size:1.1rem">{data['latest_campaign_date']}</div>
      <div class="kpi-sub">Most recent run</div>
    </div>
  </div>

  <!-- Row 1: Charts -->
  <div class="grid-3">
    <div class="card">
      <h2><span class="icon">📊</span> Call Outcomes</h2>
      <div class="chart-container">
        <canvas id="outcomesChart"></canvas>
      </div>
    </div>
    <div class="card">
      <h2><span class="icon">⭐</span> Interest Score Distribution</h2>
      <div class="chart-container">
        <canvas id="interestChart"></canvas>
      </div>
    </div>
    <div class="card">
      <h2><span class="icon">📅</span> Calls Over Time</h2>
      <div class="chart-container">
        <canvas id="timelineChart"></canvas>
      </div>
    </div>
  </div>

  <!-- Row 2: Vertical performance + Vendor intel -->
  <div class="grid-2">
    <div class="card">
      <h2><span class="icon">🏢</span> Performance by Vertical</h2>
      <table>
        <thead>
          <tr>
            <th>Vertical</th>
            <th>Total</th>
            <th>Answered</th>
            <th>Voicemail</th>
            <th>Answer %</th>
            <th>Interested</th>
            <th>Interest %</th>
          </tr>
        </thead>
        <tbody>
          {vertical_rows if vertical_rows else '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">No vertical data yet</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2><span class="icon">⚔️</span> Competitor Intel (Mentions)</h2>
      <div style="padding: 8px 0;">
        {vendor_html}
      </div>
      <div style="margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border);">
        <h2><span class="icon">🗺️</span> Targets by State</h2>
        <div style="display: flex; gap: 16px; margin-top: 8px; flex-wrap: wrap;">
          {''.join(f'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px 16px;text-align:center"><div style="font-size:1.5rem;font-weight:800">{count}</div><div style="font-size:0.75rem;color:var(--muted)">{state}</div></div>' for state, count in sorted(data["target_by_state"].items(), key=lambda x: -x[1]))}
        </div>
      </div>
    </div>
  </div>

  <!-- Row 3: Warm Leads (full width) -->
  <div class="card full-width">
    <h2><span class="icon">🔥</span> Warm Leads — Interest ★3+ (Needs Follow-Up)</h2>
    {warm_leads_html}
  </div>

  <!-- Row 4: Campaign breakdown -->
  <div class="card full-width">
    <h2><span class="icon">📋</span> Campaign Target Breakdown</h2>
    <div style="display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px;">
      {''.join(f'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px 20px;text-align:center"><div style="font-size:1.5rem;font-weight:800;color:var(--accent)">{count}</div><div style="font-size:0.8rem;color:var(--muted);margin-top:4px">{call_type.title()}</div></div>' for call_type, count in sorted(data["target_by_type"].items(), key=lambda x: -x[1]))}
    </div>
  </div>

</div>

<div class="footer">
  AI Voice Caller Analytics · Paul (AI SDR) · Fortinet SLED Territory (IA/NE/SD) · 816 accounts · {now_str}
</div>

<script>
const chartDefaults = {{
  plugins: {{
    legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }},
    tooltip: {{ backgroundColor: '#1a1a24', titleColor: '#e2e8f0', bodyColor: '#94a3b8', borderColor: '#2a2a3a', borderWidth: 1 }},
  }},
  scales: {{
    x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(42,42,58,0.5)' }} }},
    y: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(42,42,58,0.5)' }}, beginAtZero: true }},
  }},
}};

// Outcomes pie chart
new Chart(document.getElementById('outcomesChart'), {{
  type: 'doughnut',
  data: {{
    labels: {outcome_labels},
    datasets: [{{
      data: {outcome_values},
      backgroundColor: ['#7c3aed','#10b981','#f59e0b','#ef4444','#3b82f6','#ec4899'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }},
    cutout: '65%',
    responsive: true, maintainAspectRatio: false,
  }}
}});

// Interest score bar chart
new Chart(document.getElementById('interestChart'), {{
  type: 'bar',
  data: {{
    labels: {score_labels},
    datasets: [{{
      label: 'Calls',
      data: {score_values},
      backgroundColor: ['#374151','#4b5563','#f59e0b','#10b981','#7c3aed'],
      borderRadius: 6,
      borderWidth: 0,
    }}]
  }},
  options: {{
    ...chartDefaults,
    plugins: {{ legend: {{ display: false }} }},
    responsive: true, maintainAspectRatio: false,
  }}
}});

// Timeline line chart
new Chart(document.getElementById('timelineChart'), {{
  type: 'line',
  data: {{
    labels: {date_labels},
    datasets: [{{
      label: 'Calls',
      data: {date_values},
      borderColor: '#7c3aed',
      backgroundColor: 'rgba(124,58,237,0.1)',
      borderWidth: 2,
      fill: true,
      tension: 0.4,
      pointBackgroundColor: '#7c3aed',
      pointRadius: 4,
    }}]
  }},
  options: {{
    ...chartDefaults,
    plugins: {{ legend: {{ display: false }} }},
    responsive: true, maintainAspectRatio: false,
  }}
}});
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("🤖 Building AI Caller Analytics Dashboard...")
    
    data = build_analytics()
    
    print(f"  📊 Total calls: {data['total_calls']}")
    print(f"  ✅ Successful: {data['successful_calls']}")
    print(f"  🔥 Warm leads: {len(data['warm_leads'])}")
    print(f"  📅 Last campaign: {data['latest_campaign_date']}")
    
    html = build_html(data)
    
    out_path = SECOND_BRAIN / "caller-analytics.html"
    out_path.write_text(html)
    print(f"  ✅ Written: {out_path}")
    print(f"  🌐 Live at: https://brain.6eyes.dev/caller-analytics")
    
    return data


if __name__ == "__main__":
    main()
