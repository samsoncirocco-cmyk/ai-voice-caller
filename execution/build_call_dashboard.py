#!/usr/bin/env python3
"""
build_call_dashboard.py — Generate a beautiful call analytics dashboard.

Reads call_summaries.jsonl and generates an interactive HTML dashboard
showing agent performance, call outcomes, trends, and highlights.

Deployed to: brain.6eyes.dev/calls (Second Brain static page)

Usage:
  python3 execution/build_call_dashboard.py                    # Generate dashboard
  python3 execution/build_call_dashboard.py --output /tmp/     # Custom output
  python3 execution/build_call_dashboard.py --deploy            # Generate + deploy to Second Brain
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
SUMMARIES_FILE = LOGS_DIR / "call_summaries.jsonl"
ARCHIVE_FILE = LOGS_DIR / "call_summaries_test_archive_mar13.jsonl"

SECOND_BRAIN = Path("/home/samson/.openclaw/workspace/projects/second-brain")
OUTPUT_DIR = SECOND_BRAIN / "public" / "calls"

# Agent profiles (mirror webhook_server.py)
AGENT_PROFILES = {
    "6028985026": {"id": "602", "name": "Paul", "label": "Municipal / Govt", "color": "#8b5cf6", "emoji": "🟣"},
    "4806024668": {"id": "480-02", "name": "Alex", "label": "Cold List", "color": "#f97316", "emoji": "🟠"},
    "4808227861": {"id": "480-22", "name": "Jackson", "label": "Cold List (B)", "color": "#10b981", "emoji": "🟢"},
    "4806025848": {"id": "480-58", "name": "Mary", "label": "Municipal (B)", "color": "#f43f5e", "emoji": "🔴"},
    "6053035984": {"id": "605", "name": "SD Local", "label": "South Dakota", "color": "#3b82f6", "emoji": "🔵"},
    "4022755273": {"id": "402", "name": "NE Local", "label": "Nebraska", "color": "#eab308", "emoji": "🟡"},
    "5152987809": {"id": "515", "name": "IA Local", "label": "Iowa", "color": "#06b6d4", "emoji": "🩵"},
}

OUTCOME_COLORS = {
    "Connected": "#10b981",
    "Meeting Booked": "#8b5cf6",
    "Voicemail": "#f97316",
    "No Answer": "#6b7280",
    "Not Interested": "#ef4444",
    "Wrong Number": "#9ca3af",
}


def load_all_calls() -> List[Dict]:
    """Load all call entries from all log files."""
    calls = []
    for filepath in [ARCHIVE_FILE, SUMMARIES_FILE]:
        if not filepath.exists():
            continue
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Strip raw data to save memory
                    entry.pop("raw", None)
                    calls.append(entry)
                except json.JSONDecodeError:
                    continue
    return calls


def classify_outcome(summary: str) -> str:
    """Classify call outcome from summary text."""
    if not summary:
        return "No Answer"
    sl = summary.lower()

    # Direct field extraction
    m = re.search(r"call outcome[:\s]+([^\n]+)", sl)
    if m:
        raw = m.group(1).strip().rstrip(".,;")
        if any(x in raw for x in ["meeting booked", "demo booked", "meeting scheduled"]):
            return "Meeting Booked"
        elif any(x in raw for x in ["left voicemail", "voicemail"]):
            return "Voicemail"
        elif any(x in raw for x in ["no answer", "not available", "rang out"]):
            return "No Answer"
        elif any(x in raw for x in ["not interested", "do not call"]):
            return "Not Interested"
        elif "wrong number" in raw:
            return "Wrong Number"
        elif "connected" in raw:
            return "Connected"

    # Fallback keyword matching
    if any(x in sl for x in ["meeting booked", "demo booked"]):
        return "Meeting Booked"
    elif any(x in sl for x in ["voicemail", "left a message"]):
        return "Voicemail"
    elif any(x in sl for x in ["not interested", "do not call"]):
        return "Not Interested"
    elif any(x in sl for x in ["wrong number"]):
        return "Wrong Number"
    elif any(x in sl for x in ["spoke with", "connected"]):
        return "Connected"
    elif any(x in sl for x in ["no answer"]):
        return "No Answer"

    return "No Answer"


def get_agent_profile(from_number: str) -> Dict:
    """Get agent profile from FROM number."""
    digits = re.sub(r"\D", "", str(from_number))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return AGENT_PROFILES.get(digits, {
        "id": digits[:3] if digits else "?",
        "name": f"Unknown ({digits[:3]})" if digits else "Unknown",
        "label": "Unknown",
        "color": "#6b7280",
        "emoji": "⚪",
    })


def extract_interest(summary: str) -> Optional[int]:
    """Extract interest level from summary."""
    m = re.search(r"interest[^\d]*(\d+)", summary.lower())
    if m:
        return int(m.group(1))
    return None


def extract_contact(summary: str) -> Optional[str]:
    """Extract contact name from summary."""
    m = re.search(r"spoke with[:\s]+([^\n\-,\.]+)", summary, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if name.lower() not in ("unknown", "none", "n/a"):
            return name.title()
    return None


def generate_dashboard(calls: List[Dict]) -> str:
    """Generate the HTML dashboard."""
    total = len(calls)
    if total == 0:
        return "<html><body><h1>No call data available</h1></body></html>"

    # Compute metrics
    outcomes = Counter()
    agents = defaultdict(lambda: {"total": 0, "connected": 0, "meetings": 0, "interest_sum": 0, "interest_n": 0})
    by_date = defaultdict(lambda: {"total": 0, "connected": 0, "meetings": 0})
    by_hour = Counter()
    high_interest = []
    meetings_list = []

    for call in calls:
        summary = call.get("summary", "")
        outcome = classify_outcome(summary)
        outcomes[outcome] += 1

        from_num = call.get("from", "")
        agent = get_agent_profile(from_num)
        aid = agent["id"]
        agents[aid]["total"] += 1
        agents[aid]["profile"] = agent
        if outcome == "Connected":
            agents[aid]["connected"] += 1
        if outcome == "Meeting Booked":
            agents[aid]["meetings"] += 1

        interest = extract_interest(summary)
        if interest is not None:
            agents[aid]["interest_sum"] += interest
            agents[aid]["interest_n"] += 1

        # Date tracking
        ts = call.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
                hour_key = dt.hour
                by_date[date_key]["total"] += 1
                if outcome in ("Connected", "Meeting Booked"):
                    by_date[date_key]["connected"] += 1
                if outcome == "Meeting Booked":
                    by_date[date_key]["meetings"] += 1
                by_hour[hour_key] += 1
            except Exception:
                pass

        # High interest
        if interest and interest >= 4:
            contact = extract_contact(summary)
            high_interest.append({
                "to": call.get("to", ""),
                "account": call.get("account_name", ""),
                "contact": contact,
                "interest": interest,
                "outcome": outcome,
                "timestamp": ts,
                "agent": agent["name"],
            })

        # Meetings
        if outcome == "Meeting Booked":
            contact = extract_contact(summary)
            meetings_list.append({
                "to": call.get("to", ""),
                "account": call.get("account_name", ""),
                "contact": contact,
                "timestamp": ts,
                "agent": agent["name"],
                "summary": summary[:200],
            })

    # Derived stats
    connected = outcomes.get("Connected", 0) + outcomes.get("Meeting Booked", 0)
    connect_rate = round((connected / total) * 100) if total else 0
    meeting_count = outcomes.get("Meeting Booked", 0)
    meeting_rate = round((meeting_count / total) * 100, 1) if total else 0
    voicemail_count = outcomes.get("Voicemail", 0)

    # Date range
    dates_sorted = sorted(by_date.keys())
    date_labels = json.dumps(dates_sorted[-14:])  # Last 14 days
    date_totals = json.dumps([by_date[d]["total"] for d in dates_sorted[-14:]])
    date_connected = json.dumps([by_date[d]["connected"] for d in dates_sorted[-14:]])

    # Outcome chart data
    outcome_labels = json.dumps(list(outcomes.keys()))
    outcome_values = json.dumps(list(outcomes.values()))
    outcome_colors_list = json.dumps([OUTCOME_COLORS.get(k, "#6b7280") for k in outcomes.keys()])

    # Hour distribution
    hour_labels = json.dumps([f"{h}:00" for h in range(8, 19)])
    hour_values = json.dumps([by_hour.get(h, 0) for h in range(8, 19)])

    # Agent cards HTML
    agent_cards_html = ""
    for aid, data in sorted(agents.items(), key=lambda x: x[1]["total"], reverse=True):
        prof = data.get("profile", {})
        t = data["total"] or 1
        cr = round(((data["connected"] + data["meetings"]) / t) * 100)
        mr = round((data["meetings"] / t) * 100)
        avg_interest = round(data["interest_sum"] / data["interest_n"], 1) if data["interest_n"] else "—"
        color = prof.get("color", "#6b7280")
        agent_cards_html += f"""
        <div class="agent-card" style="border-left: 4px solid {color}">
          <div class="agent-header">
            <span class="agent-emoji">{prof.get('emoji', '⚪')}</span>
            <div>
              <div class="agent-name">{prof.get('name', aid)}</div>
              <div class="agent-label">{prof.get('label', '')}</div>
            </div>
          </div>
          <div class="agent-stats">
            <div class="stat"><span class="stat-value">{data['total']}</span><span class="stat-label">Calls</span></div>
            <div class="stat"><span class="stat-value">{cr}%</span><span class="stat-label">Connect</span></div>
            <div class="stat"><span class="stat-value">{data['meetings']}</span><span class="stat-label">Meetings</span></div>
            <div class="stat"><span class="stat-value">{avg_interest}</span><span class="stat-label">Avg Interest</span></div>
          </div>
        </div>"""

    # High interest table rows
    hi_rows = ""
    for h in sorted(high_interest, key=lambda x: x.get("interest", 0), reverse=True)[:15]:
        ts_short = h.get("timestamp", "")[:10]
        hi_rows += f"""
        <tr>
          <td>{h.get('account') or h.get('to', '—')}</td>
          <td>{h.get('contact', '—')}</td>
          <td><span class="interest-badge interest-{h.get('interest', 0)}">{h.get('interest', '?')}/5</span></td>
          <td>{h.get('outcome', '—')}</td>
          <td>{h.get('agent', '—')}</td>
          <td>{ts_short}</td>
        </tr>"""

    # Meetings table rows
    meeting_rows = ""
    for m in meetings_list:
        ts_short = m.get("timestamp", "")[:10]
        meeting_rows += f"""
        <tr>
          <td>{m.get('account') or m.get('to', '—')}</td>
          <td>{m.get('contact', '—')}</td>
          <td>{m.get('agent', '—')}</td>
          <td>{ts_short}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Call Analytics — Fortinet SLED</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0f0f23;
      color: #e2e8f0;
      min-height: 100vh;
    }}
    .header {{
      background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #4c1d95 100%);
      padding: 2rem 2rem 1.5rem;
      border-bottom: 1px solid rgba(139, 92, 246, 0.3);
    }}
    .header h1 {{
      font-size: 1.8rem;
      font-weight: 700;
      background: linear-gradient(90deg, #c084fc, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .header .subtitle {{ color: #a5b4fc; margin-top: 0.3rem; font-size: 0.9rem; }}
    .container {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem; }}

    /* KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .kpi-card {{
      background: linear-gradient(145deg, #1e1b4b, #1a1744);
      border: 1px solid rgba(139, 92, 246, 0.2);
      border-radius: 12px;
      padding: 1.2rem;
      text-align: center;
      transition: transform 0.2s, border-color 0.2s;
    }}
    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(139, 92, 246, 0.5);
    }}
    .kpi-value {{
      font-size: 2.2rem;
      font-weight: 800;
      background: linear-gradient(90deg, #c084fc, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .kpi-label {{ color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.3rem; }}
    .kpi-detail {{ color: #64748b; font-size: 0.75rem; margin-top: 0.2rem; }}

    /* Charts */
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }}
    .chart-card {{
      background: #1e1b4b;
      border: 1px solid rgba(139, 92, 246, 0.15);
      border-radius: 12px;
      padding: 1.5rem;
    }}
    .chart-card h3 {{
      font-size: 1rem;
      margin-bottom: 1rem;
      color: #c084fc;
    }}
    canvas {{ max-height: 280px; }}

    /* Agent Cards */
    .section-title {{
      font-size: 1.2rem;
      font-weight: 700;
      color: #c084fc;
      margin: 1.5rem 0 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid rgba(139, 92, 246, 0.2);
    }}
    .agents-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .agent-card {{
      background: #1e1b4b;
      border: 1px solid rgba(139, 92, 246, 0.15);
      border-radius: 10px;
      padding: 1rem;
      transition: transform 0.2s;
    }}
    .agent-card:hover {{ transform: translateY(-2px); }}
    .agent-header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.8rem;
    }}
    .agent-emoji {{ font-size: 1.5rem; }}
    .agent-name {{ font-weight: 700; color: #e2e8f0; }}
    .agent-label {{ color: #94a3b8; font-size: 0.8rem; }}
    .agent-stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0.5rem;
    }}
    .stat {{ text-align: center; }}
    .stat-value {{ display: block; font-size: 1.2rem; font-weight: 700; color: #c084fc; }}
    .stat-label {{ display: block; font-size: 0.65rem; color: #64748b; text-transform: uppercase; }}

    /* Tables */
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    th {{
      text-align: left;
      padding: 0.6rem 0.8rem;
      color: #c084fc;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid rgba(139, 92, 246, 0.2);
    }}
    td {{
      padding: 0.6rem 0.8rem;
      border-bottom: 1px solid rgba(139, 92, 246, 0.1);
      color: #cbd5e1;
    }}
    tr:hover td {{ background: rgba(139, 92, 246, 0.05); }}

    .interest-badge {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .interest-4 {{ background: #065f46; color: #34d399; }}
    .interest-5 {{ background: #5b21b6; color: #c084fc; }}

    .meeting-badge {{
      display: inline-block;
      background: #5b21b6;
      color: #c084fc;
      padding: 0.15rem 0.5rem;
      border-radius: 9999px;
      font-size: 0.7rem;
      font-weight: 600;
    }}

    .footer {{
      text-align: center;
      color: #475569;
      font-size: 0.75rem;
      padding: 2rem 0;
      border-top: 1px solid rgba(139, 92, 246, 0.1);
      margin-top: 2rem;
    }}

    @media (max-width: 768px) {{
      .charts-grid {{ grid-template-columns: 1fr; }}
      .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .agents-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📞 AI Call Analytics</h1>
    <p class="subtitle">Fortinet SLED Territory — AI Voice Caller Performance Dashboard</p>
  </div>

  <div class="container">
    <!-- KPI Cards -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value">{total}</div>
        <div class="kpi-label">Total Calls</div>
        <div class="kpi-detail">All-time outbound</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{connect_rate}%</div>
        <div class="kpi-label">Connect Rate</div>
        <div class="kpi-detail">{connected} connected</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{meeting_count}</div>
        <div class="kpi-label">Meetings Booked</div>
        <div class="kpi-detail">{meeting_rate}% booking rate</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{voicemail_count}</div>
        <div class="kpi-label">Voicemails Left</div>
        <div class="kpi-detail">{round((voicemail_count / total) * 100) if total else 0}% of calls</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{len(high_interest)}</div>
        <div class="kpi-label">High Interest</div>
        <div class="kpi-detail">Interest ≥ 4/5</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{len(agents)}</div>
        <div class="kpi-label">Active Agents</div>
        <div class="kpi-detail">AI caller lanes</div>
      </div>
    </div>

    <!-- Charts -->
    <div class="charts-grid">
      <div class="chart-card">
        <h3>📊 Call Outcomes</h3>
        <canvas id="outcomeChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>📈 Daily Call Volume (Last 14 Days)</h3>
        <canvas id="volumeChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>⏰ Calls by Hour</h3>
        <canvas id="hourChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>🎯 Connect Rate Trend</h3>
        <canvas id="connectChart"></canvas>
      </div>
    </div>

    <!-- Agent Performance -->
    <h2 class="section-title">🤖 Agent Performance</h2>
    <div class="agents-grid">
      {agent_cards_html}
    </div>

    <!-- High Interest Leads -->
    {'<h2 class="section-title">🔥 High-Interest Leads (Interest ≥ 4)</h2>' if high_interest else ''}
    {'<div class="chart-card"><table><thead><tr><th>Account</th><th>Contact</th><th>Interest</th><th>Outcome</th><th>Agent</th><th>Date</th></tr></thead><tbody>' + hi_rows + '</tbody></table></div>' if high_interest else ''}

    <!-- Meetings -->
    {'<h2 class="section-title">📅 Meetings Booked</h2>' if meetings_list else ''}
    {'<div class="chart-card"><table><thead><tr><th>Account</th><th>Contact</th><th>Agent</th><th>Date</th></tr></thead><tbody>' + meeting_rows + '</tbody></table></div>' if meetings_list else ''}

    <div class="footer">
      Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} by Paul (AI) &bull;
      <a href="/pipeline" style="color: #818cf8;">Pipeline</a> &bull;
      <a href="/velocity" style="color: #818cf8;">Velocity</a> &bull;
      <a href="/battlecards" style="color: #818cf8;">Battlecards</a> &bull;
      <a href="/monday-prep" style="color: #818cf8;">Monday Prep</a>
    </div>
  </div>

  <script>
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = 'rgba(139, 92, 246, 0.1)';

    // Outcome Doughnut
    new Chart(document.getElementById('outcomeChart'), {{
      type: 'doughnut',
      data: {{
        labels: {outcome_labels},
        datasets: [{{
          data: {outcome_values},
          backgroundColor: {outcome_colors_list},
          borderWidth: 0,
          hoverOffset: 8,
        }}]
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, padding: 12 }} }}
        }}
      }}
    }});

    // Volume Bar Chart
    new Chart(document.getElementById('volumeChart'), {{
      type: 'bar',
      data: {{
        labels: {date_labels},
        datasets: [
          {{
            label: 'Total Calls',
            data: {date_totals},
            backgroundColor: 'rgba(139, 92, 246, 0.5)',
            borderRadius: 4,
          }},
          {{
            label: 'Connected',
            data: {date_connected},
            backgroundColor: 'rgba(16, 185, 129, 0.6)',
            borderRadius: 4,
          }}
        ]
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45 }} }},
          y: {{ beginAtZero: true, grid: {{ color: 'rgba(139, 92, 246, 0.05)' }} }}
        }},
        plugins: {{ legend: {{ labels: {{ font: {{ size: 11 }} }} }} }}
      }}
    }});

    // Hour Distribution
    new Chart(document.getElementById('hourChart'), {{
      type: 'bar',
      data: {{
        labels: {hour_labels},
        datasets: [{{
          label: 'Calls',
          data: {hour_values},
          backgroundColor: 'rgba(168, 85, 247, 0.5)',
          borderRadius: 4,
        }}]
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ grid: {{ display: false }} }},
          y: {{ beginAtZero: true, grid: {{ color: 'rgba(139, 92, 246, 0.05)' }} }}
        }},
        plugins: {{ legend: {{ display: false }} }}
      }}
    }});

    // Connect Rate Trend
    const dateTotals = {date_totals};
    const dateConnected = {date_connected};
    const connectRates = dateTotals.map((t, i) => t > 0 ? Math.round((dateConnected[i] / t) * 100) : 0);
    new Chart(document.getElementById('connectChart'), {{
      type: 'line',
      data: {{
        labels: {date_labels},
        datasets: [{{
          label: 'Connect Rate %',
          data: connectRates,
          borderColor: '#8b5cf6',
          backgroundColor: 'rgba(139, 92, 246, 0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointBackgroundColor: '#c084fc',
        }}]
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45 }} }},
          y: {{ beginAtZero: true, max: 100, grid: {{ color: 'rgba(139, 92, 246, 0.05)' }},
            ticks: {{ callback: v => v + '%' }} }}
        }},
        plugins: {{ legend: {{ display: false }} }}
      }}
    }});
  </script>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(description="Build call analytics dashboard")
    parser.add_argument("--output", type=str, help="Output directory")
    parser.add_argument("--deploy", action="store_true", help="Deploy to Second Brain")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    print("📊 Loading call data...")
    calls = load_all_calls()
    print(f"   {len(calls)} calls loaded")

    print("🎨 Generating dashboard...")
    html = generate_dashboard(calls)

    os.makedirs(output_dir, exist_ok=True)
    output_file = output_dir / "index.html"
    with open(output_file, "w") as f:
        f.write(html)
    print(f"   ✅ Written to {output_file}")

    if args.deploy:
        print("🚀 Deploying to Second Brain...")
        import subprocess
        os.chdir(SECOND_BRAIN)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-m", "Add call analytics dashboard"], check=False)
        subprocess.run(["git", "push"], check=True)
        print("   ✅ Deployed — available at brain.6eyes.dev/calls")


if __name__ == "__main__":
    main()
