#!/usr/bin/env python3
"""
Fortinet SLED Voice Operations Dashboard
Live ops dashboard pulling from Firestore (tatt-pro)
Run: .venv/bin/python execution/dashboard.py
"""
import json
import os
import logging
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from google.cloud import firestore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
db = firestore.Client(project="tatt-pro")

# SignalWire config for number health
SW_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "signalwire.json")
try:
    with open(SW_CONFIG_PATH) as f:
        SW_CFG = json.load(f)
except Exception:
    SW_CFG = {}


def _ts_to_str(ts):
    """Convert Firestore timestamp or ISO string to readable string."""
    if ts is None:
        return ""
    if hasattr(ts, "isoformat"):
        return ts.strftime("%Y-%m-%d %H:%M")
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ts
    return str(ts)


def _ts_to_epoch(ts):
    """Convert to epoch seconds for sorting."""
    if ts is None:
        return 0
    if hasattr(ts, "timestamp"):
        return ts.timestamp()
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0
    return 0


def fetch_collection(name, limit=200):
    """Fetch docs from a Firestore collection."""
    try:
        docs = db.collection(name).limit(limit).stream()
        return [dict(doc.to_dict(), _id=doc.id) for doc in docs]
    except Exception as e:
        logger.warning(f"Failed to fetch {name}: {e}")
        return []


def get_number_health():
    """Check SignalWire number health via recent call_logs."""
    logs = fetch_collection("call_logs", limit=20)
    if not logs:
        return "gray", "No data"
    recent = sorted(logs, key=lambda x: _ts_to_epoch(x.get("timestamp")), reverse=True)[:10]
    failed = sum(1 for c in recent if c.get("outcome") in ("failed", "no_answer", "voicemail") or c.get("duration", 1) == 0)
    if failed >= 5:
        return "red", f"{failed}/10 recent calls failed"
    if failed >= 3:
        return "yellow", f"{failed}/10 recent calls had issues"
    return "green", f"Healthy ({10-failed}/10 OK)"


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    """Return all dashboard data as JSON for frontend fetch."""
    call_logs = fetch_collection("call_logs", 500)
    contacts = fetch_collection("contacts", 500)
    lead_scores = fetch_collection("lead_scores", 500)
    cold_leads = fetch_collection("cold-call-leads", 500)
    callbacks = fetch_collection("callbacks", 200)
    emails = fetch_collection("email-queue", 200)
    campaign_runs = fetch_collection("campaign_runs", 50)
    campaign_calls = fetch_collection("campaign_calls", 200)

    # Stats
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    today_calls = [c for c in call_logs if today_str in _ts_to_str(c.get("timestamp", ""))]
    scores = [ls.get("score", 0) for ls in lead_scores if ls.get("score") is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    # Lead pipeline
    hot = [ls for ls in lead_scores if (ls.get("score") or 0) >= 70]
    warm = [ls for ls in lead_scores if 40 <= (ls.get("score") or 0) < 70]
    cold = [ls for ls in lead_scores if (ls.get("score") or 0) < 40]

    # Number health
    health_color, health_text = get_number_health()

    # Activity feed
    activities = []
    for c in call_logs:
        activities.append({
            "type": "call",
            "text": f"Call {c.get('outcome', 'unknown')} - {c.get('caller_number', 'N/A')}",
            "detail": c.get("summary", ""),
            "ts": _ts_to_str(c.get("timestamp")),
            "epoch": _ts_to_epoch(c.get("timestamp")),
        })
    for c in contacts:
        activities.append({
            "type": "contact",
            "text": f"Contact captured: {c.get('name', 'Unknown')}",
            "detail": c.get("account", ""),
            "ts": _ts_to_str(c.get("created_at")),
            "epoch": _ts_to_epoch(c.get("created_at")),
        })
    for ls in lead_scores:
        activities.append({
            "type": "lead",
            "text": f"Lead scored: {ls.get('score', 0)}/100 ({ls.get('qualification', 'N/A')})",
            "detail": ", ".join(ls.get("details", [])[:3]),
            "ts": _ts_to_str(ls.get("timestamp")),
            "epoch": _ts_to_epoch(ls.get("timestamp")),
        })
    for cb in callbacks:
        activities.append({
            "type": "callback",
            "text": f"Callback scheduled: {cb.get('contact_name', 'Unknown')}",
            "detail": cb.get("reason", ""),
            "ts": _ts_to_str(cb.get("created_at")),
            "epoch": _ts_to_epoch(cb.get("created_at")),
        })
    activities.sort(key=lambda x: x["epoch"], reverse=True)

    # Contacts table
    all_contacts = []
    for c in contacts:
        all_contacts.append({
            "name": c.get("name", "Unknown"),
            "phone": c.get("phone", ""),
            "account": c.get("account", ""),
            "source": c.get("source", ""),
            "status": c.get("status", ""),
            "created": _ts_to_str(c.get("created_at")),
            "epoch": _ts_to_epoch(c.get("created_at")),
        })
    for c in cold_leads:
        all_contacts.append({
            "name": c.get("contact_name", "Unknown"),
            "phone": c.get("phone_number", ""),
            "account": "",
            "source": c.get("source", "cold-call"),
            "status": c.get("status", ""),
            "created": _ts_to_str(c.get("created_at")),
            "epoch": _ts_to_epoch(c.get("created_at")),
        })
    all_contacts.sort(key=lambda x: x["epoch"], reverse=True)

    # Callbacks queue
    cb_list = []
    now_epoch = datetime.utcnow().timestamp()
    for cb in callbacks:
        cb_dt_str = cb.get("callback_datetime", "")
        cb_epoch = _ts_to_epoch(cb_dt_str)
        cb_list.append({
            "contact": cb.get("contact_name", "Unknown"),
            "phone": cb.get("phone_number", ""),
            "datetime": _ts_to_str(cb_dt_str),
            "reason": cb.get("reason", ""),
            "status": cb.get("status", "pending"),
            "overdue": cb_epoch < now_epoch and cb.get("status") == "pending",
            "epoch": cb_epoch,
        })
    cb_list.sort(key=lambda x: x["epoch"])

    # Campaign status
    campaigns = []
    for cr in campaign_runs:
        campaigns.append({
            "name": cr.get("campaign_name", cr.get("name", "Unknown")),
            "total": cr.get("total_contacts", 0),
            "completed": cr.get("completed", 0),
            "success_rate": cr.get("success_rate", 0),
            "status": cr.get("status", "unknown"),
        })

    # Number health detail
    health_calls = sorted(call_logs, key=lambda x: _ts_to_epoch(x.get("timestamp")), reverse=True)[:15]
    health_detail = []
    for c in health_calls:
        health_detail.append({
            "time": _ts_to_str(c.get("timestamp")),
            "outcome": c.get("outcome", "unknown"),
            "duration": c.get("duration", 0),
            "caller": c.get("caller_number", ""),
        })

    def lead_card(ls):
        return {
            "call_sid": ls.get("call_sid", ""),
            "score": ls.get("score", 0),
            "qualification": ls.get("qualification", ""),
            "details": ls.get("details", []),
            "ts": _ts_to_str(ls.get("timestamp")),
        }

    return jsonify({
        "stats": {
            "total_calls_today": len(today_calls),
            "total_calls": len(call_logs),
            "contacts_captured": len(contacts) + len(cold_leads),
            "leads_scored": len(lead_scores),
            "avg_score": avg_score,
        },
        "health": {"color": health_color, "text": health_text},
        "pipeline": {
            "hot": [lead_card(ls) for ls in sorted(hot, key=lambda x: x.get("score", 0), reverse=True)],
            "warm": [lead_card(ls) for ls in sorted(warm, key=lambda x: x.get("score", 0), reverse=True)],
            "cold": [lead_card(ls) for ls in sorted(cold, key=lambda x: x.get("score", 0), reverse=True)],
        },
        "activities": activities[:50],
        "contacts": all_contacts[:100],
        "callbacks": cb_list,
        "campaigns": campaigns,
        "number_health": health_detail,
        "phone_number": SW_CFG.get("phone_number", "N/A"),
        "refreshed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    })


DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fortinet SLED Voice Operations</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        fortinet: '#EE7623',
        fortinetDark: '#C45F1A',
        slate: {
          850: '#172033',
          950: '#0B1120',
        }
      }
    }
  }
}
</script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  body { font-family: 'Inter', sans-serif; }
  .card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(8px); border: 1px solid rgba(71, 85, 105, 0.3); }
  .glow-green { box-shadow: 0 0 8px rgba(34, 197, 94, 0.4); }
  .glow-yellow { box-shadow: 0 0 8px rgba(234, 179, 8, 0.4); }
  .glow-red { box-shadow: 0 0 8px rgba(239, 68, 68, 0.4); }
  .pipeline-card { transition: transform 0.15s, box-shadow 0.15s; }
  .pipeline-card:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }
  .scroll-feed { max-height: 420px; overflow-y: auto; }
  .scroll-feed::-webkit-scrollbar { width: 4px; }
  .scroll-feed::-webkit-scrollbar-thumb { background: #475569; border-radius: 2px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
  .pulse { animation: pulse-ring 2s ease-out infinite; }
  @keyframes pulse-ring { 0% { opacity: 1; } 100% { opacity: 0.3; } }
  .fade-in { animation: fadeIn 0.4s ease-in; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">

<!-- Header -->
<header class="bg-slate-900/80 backdrop-blur border-b border-slate-700/50 sticky top-0 z-50">
  <div class="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <div class="w-8 h-8 rounded-lg bg-fortinet flex items-center justify-center font-bold text-white text-sm">F</div>
      <div>
        <h1 class="text-lg font-semibold text-white tracking-tight">Fortinet SLED Voice Operations</h1>
        <p class="text-xs text-slate-400" id="phone-number">Loading...</p>
      </div>
    </div>
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2" id="health-indicator">
        <span class="w-3 h-3 rounded-full bg-slate-600" id="health-dot"></span>
        <span class="text-xs text-slate-400" id="health-text">Loading...</span>
      </div>
      <div class="text-xs text-slate-500" id="refresh-time">--</div>
    </div>
  </div>
</header>

<main class="max-w-[1600px] mx-auto px-6 py-6 space-y-6">

  <!-- Stats Row -->
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-4" id="stats-row">
    <div class="card rounded-xl p-5">
      <p class="text-xs text-slate-400 uppercase tracking-wider font-medium">Total Calls Today</p>
      <p class="text-3xl font-bold text-white mt-1" id="stat-calls-today">--</p>
      <p class="text-xs text-slate-500 mt-1"><span id="stat-calls-total">--</span> all time</p>
    </div>
    <div class="card rounded-xl p-5">
      <p class="text-xs text-slate-400 uppercase tracking-wider font-medium">Contacts Captured</p>
      <p class="text-3xl font-bold text-white mt-1" id="stat-contacts">--</p>
    </div>
    <div class="card rounded-xl p-5">
      <p class="text-xs text-slate-400 uppercase tracking-wider font-medium">Leads Scored</p>
      <p class="text-3xl font-bold text-white mt-1" id="stat-leads">--</p>
    </div>
    <div class="card rounded-xl p-5">
      <p class="text-xs text-slate-400 uppercase tracking-wider font-medium">Avg Lead Score</p>
      <p class="text-3xl font-bold mt-1" id="stat-avg-score">--</p>
      <p class="text-xs text-slate-500 mt-1">out of 100</p>
    </div>
  </div>

  <!-- Lead Pipeline -->
  <div>
    <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Lead Pipeline</h2>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="card rounded-xl p-4">
        <div class="flex items-center gap-2 mb-3">
          <span class="w-2.5 h-2.5 rounded-full bg-red-500"></span>
          <h3 class="text-sm font-semibold text-red-400">HOT <span class="text-slate-500 font-normal">(70+)</span></h3>
          <span class="ml-auto badge bg-red-500/20 text-red-400" id="hot-count">0</span>
        </div>
        <div class="space-y-2 scroll-feed" id="pipeline-hot"></div>
      </div>
      <div class="card rounded-xl p-4">
        <div class="flex items-center gap-2 mb-3">
          <span class="w-2.5 h-2.5 rounded-full bg-yellow-500"></span>
          <h3 class="text-sm font-semibold text-yellow-400">WARM <span class="text-slate-500 font-normal">(40-69)</span></h3>
          <span class="ml-auto badge bg-yellow-500/20 text-yellow-400" id="warm-count">0</span>
        </div>
        <div class="space-y-2 scroll-feed" id="pipeline-warm"></div>
      </div>
      <div class="card rounded-xl p-4">
        <div class="flex items-center gap-2 mb-3">
          <span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
          <h3 class="text-sm font-semibold text-blue-400">COLD <span class="text-slate-500 font-normal">(&lt;40)</span></h3>
          <span class="ml-auto badge bg-blue-500/20 text-blue-400" id="cold-count">0</span>
        </div>
        <div class="space-y-2 scroll-feed" id="pipeline-cold"></div>
      </div>
    </div>
  </div>

  <!-- Activity + Callbacks -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <div class="card rounded-xl p-4">
      <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Recent Activity</h2>
      <div class="space-y-2 scroll-feed" id="activity-feed"></div>
    </div>
    <div class="card rounded-xl p-4">
      <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Callbacks Queue</h2>
      <div class="space-y-2 scroll-feed" id="callbacks-list"></div>
      <div class="text-center text-xs text-slate-500 mt-2 hidden" id="no-callbacks">No callbacks scheduled</div>
    </div>
  </div>

  <!-- Contacts Table -->
  <div class="card rounded-xl p-4">
    <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Contacts</h2>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700/50">
            <th class="pb-2 pr-4">Name</th><th class="pb-2 pr-4">Phone</th><th class="pb-2 pr-4">Account</th>
            <th class="pb-2 pr-4">Source</th><th class="pb-2 pr-4">Status</th><th class="pb-2">Created</th>
          </tr>
        </thead>
        <tbody id="contacts-table" class="divide-y divide-slate-700/30"></tbody>
      </table>
    </div>
    <div class="text-center text-xs text-slate-500 mt-2 hidden" id="no-contacts">No contacts yet</div>
  </div>

  <!-- Campaign Status -->
  <div class="card rounded-xl p-4" id="campaigns-section">
    <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Campaign Status</h2>
    <div id="campaigns-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"></div>
    <div class="text-center text-xs text-slate-500 mt-2 hidden" id="no-campaigns">No campaigns yet</div>
  </div>

  <!-- Number Health -->
  <div class="card rounded-xl p-4">
    <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Number Health</h2>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700/50">
            <th class="pb-2 pr-4">Time</th><th class="pb-2 pr-4">Caller</th>
            <th class="pb-2 pr-4">Outcome</th><th class="pb-2">Duration</th>
          </tr>
        </thead>
        <tbody id="health-table" class="divide-y divide-slate-700/30"></tbody>
      </table>
    </div>
  </div>
</main>

<footer class="text-center text-xs text-slate-600 py-4">
  Fortinet SLED Voice Ops &middot; Powered by SignalWire + Firestore &middot; Auto-refreshes every 30s
</footer>

<script>
const TYPE_ICONS = {
  call: '<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/></svg>',
  contact: '<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>',
  lead: '<svg class="w-4 h-4 text-fortinet" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>',
  callback: '<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
};

const OUTCOME_COLORS = {
  interested: 'bg-green-500/20 text-green-400',
  meeting_booked: 'bg-green-500/20 text-green-400',
  send_info: 'bg-blue-500/20 text-blue-400',
  callback_requested: 'bg-purple-500/20 text-purple-400',
  completed: 'bg-slate-500/20 text-slate-400',
  not_interested: 'bg-red-500/20 text-red-400',
  failed: 'bg-red-500/20 text-red-400',
  no_answer: 'bg-yellow-500/20 text-yellow-400',
  voicemail: 'bg-yellow-500/20 text-yellow-400',
  unknown: 'bg-slate-500/20 text-slate-400',
};

function scoreBadge(score) {
  if (score >= 70) return '<span class="badge bg-red-500/20 text-red-400">' + score + '</span>';
  if (score >= 40) return '<span class="badge bg-yellow-500/20 text-yellow-400">' + score + '</span>';
  return '<span class="badge bg-blue-500/20 text-blue-400">' + score + '</span>';
}

function statusBadge(status) {
  const colors = {
    new: 'bg-green-500/20 text-green-400',
    pending: 'bg-yellow-500/20 text-yellow-400',
    completed: 'bg-slate-500/20 text-slate-400',
    queued: 'bg-blue-500/20 text-blue-400',
    called: 'bg-slate-500/20 text-slate-400',
  };
  return '<span class="badge ' + (colors[status] || 'bg-slate-500/20 text-slate-400') + '">' + (status || 'N/A') + '</span>';
}

function renderPipeline(containerId, leads) {
  const el = document.getElementById(containerId);
  if (!leads.length) {
    el.innerHTML = '<p class="text-xs text-slate-500 text-center py-4">No leads</p>';
    return;
  }
  el.innerHTML = leads.map(l => `
    <div class="pipeline-card bg-slate-800/60 rounded-lg p-3 border border-slate-700/30">
      <div class="flex items-center justify-between mb-1">
        <span class="text-xs font-mono text-slate-400">${l.call_sid ? l.call_sid.substring(0, 12) + '...' : 'N/A'}</span>
        ${scoreBadge(l.score)}
      </div>
      <p class="text-xs text-slate-300 mt-1">${(l.details || []).slice(0, 3).join(' | ') || 'No details'}</p>
      <p class="text-xs text-slate-500 mt-1">${l.ts || ''}</p>
    </div>
  `).join('');
}

function renderActivities(activities) {
  const el = document.getElementById('activity-feed');
  if (!activities.length) {
    el.innerHTML = '<p class="text-xs text-slate-500 text-center py-4">No activity yet</p>';
    return;
  }
  el.innerHTML = activities.map(a => `
    <div class="flex items-start gap-3 py-2 border-b border-slate-700/20 fade-in">
      <div class="mt-0.5">${TYPE_ICONS[a.type] || ''}</div>
      <div class="flex-1 min-w-0">
        <p class="text-sm text-slate-200">${a.text}</p>
        ${a.detail ? '<p class="text-xs text-slate-400 truncate">' + a.detail + '</p>' : ''}
      </div>
      <span class="text-xs text-slate-500 whitespace-nowrap">${a.ts}</span>
    </div>
  `).join('');
}

function renderCallbacks(callbacks) {
  const el = document.getElementById('callbacks-list');
  const none = document.getElementById('no-callbacks');
  if (!callbacks.length) {
    el.innerHTML = '';
    none.classList.remove('hidden');
    return;
  }
  none.classList.add('hidden');
  el.innerHTML = callbacks.map(cb => `
    <div class="flex items-start gap-3 py-2 border-b border-slate-700/20 ${cb.overdue ? 'bg-red-500/5 rounded-lg px-2 -mx-2' : ''}">
      <div class="mt-0.5">
        ${cb.overdue ? '<span class="w-2 h-2 rounded-full bg-red-500 inline-block pulse"></span>' : '<span class="w-2 h-2 rounded-full bg-yellow-500 inline-block"></span>'}
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-sm ${cb.overdue ? 'text-red-300' : 'text-slate-200'}">${cb.contact}</p>
        <p class="text-xs text-slate-400">${cb.reason}</p>
        <p class="text-xs text-slate-500">${cb.phone}</p>
      </div>
      <div class="text-right">
        <p class="text-xs ${cb.overdue ? 'text-red-400 font-semibold' : 'text-slate-400'}">${cb.datetime}</p>
        ${statusBadge(cb.status)}
      </div>
    </div>
  `).join('');
}

function renderContacts(contacts) {
  const el = document.getElementById('contacts-table');
  const none = document.getElementById('no-contacts');
  if (!contacts.length) {
    el.innerHTML = '';
    none.classList.remove('hidden');
    return;
  }
  none.classList.add('hidden');
  el.innerHTML = contacts.map(c => `
    <tr class="hover:bg-slate-800/30">
      <td class="py-2 pr-4 text-slate-200">${c.name}</td>
      <td class="py-2 pr-4 text-slate-400 font-mono text-xs">${c.phone}</td>
      <td class="py-2 pr-4 text-slate-400">${c.account}</td>
      <td class="py-2 pr-4">${statusBadge(c.source)}</td>
      <td class="py-2 pr-4">${statusBadge(c.status)}</td>
      <td class="py-2 text-xs text-slate-500">${c.created}</td>
    </tr>
  `).join('');
}

function renderCampaigns(campaigns) {
  const el = document.getElementById('campaigns-grid');
  const none = document.getElementById('no-campaigns');
  if (!campaigns.length) {
    el.innerHTML = '';
    none.classList.remove('hidden');
    return;
  }
  none.classList.add('hidden');
  el.innerHTML = campaigns.map(c => {
    const pct = c.total > 0 ? Math.round((c.completed / c.total) * 100) : 0;
    return `
    <div class="bg-slate-800/60 rounded-lg p-4 border border-slate-700/30">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-sm font-medium text-slate-200">${c.name}</h3>
        ${statusBadge(c.status)}
      </div>
      <div class="w-full bg-slate-700/50 rounded-full h-2 mb-2">
        <div class="h-2 rounded-full bg-fortinet" style="width: ${pct}%"></div>
      </div>
      <div class="flex justify-between text-xs text-slate-400">
        <span>${c.completed}/${c.total} contacts</span>
        <span>${pct}% complete</span>
      </div>
    </div>`;
  }).join('');
}

function renderHealthTable(rows) {
  const el = document.getElementById('health-table');
  if (!rows.length) {
    el.innerHTML = '<tr><td colspan="4" class="py-4 text-center text-xs text-slate-500">No call data</td></tr>';
    return;
  }
  el.innerHTML = rows.map(r => {
    const cls = OUTCOME_COLORS[r.outcome] || OUTCOME_COLORS.unknown;
    return `
    <tr class="hover:bg-slate-800/30">
      <td class="py-2 pr-4 text-xs text-slate-400">${r.time}</td>
      <td class="py-2 pr-4 text-xs text-slate-400 font-mono">${r.caller}</td>
      <td class="py-2 pr-4"><span class="badge ${cls}">${r.outcome}</span></td>
      <td class="py-2 text-xs text-slate-400">${r.duration}s</td>
    </tr>`;
  }).join('');
}

function updateHealth(health) {
  const dot = document.getElementById('health-dot');
  const txt = document.getElementById('health-text');
  dot.className = 'w-3 h-3 rounded-full';
  if (health.color === 'green') { dot.classList.add('bg-green-500', 'glow-green'); }
  else if (health.color === 'yellow') { dot.classList.add('bg-yellow-500', 'glow-yellow'); }
  else if (health.color === 'red') { dot.classList.add('bg-red-500', 'glow-red'); }
  else { dot.classList.add('bg-slate-600'); }
  txt.textContent = health.text;
}

async function refresh() {
  try {
    const res = await fetch('/api/data');
    const d = await res.json();

    document.getElementById('stat-calls-today').textContent = d.stats.total_calls_today;
    document.getElementById('stat-calls-total').textContent = d.stats.total_calls + ' calls';
    document.getElementById('stat-contacts').textContent = d.stats.contacts_captured;
    document.getElementById('stat-leads').textContent = d.stats.leads_scored;
    const avgEl = document.getElementById('stat-avg-score');
    avgEl.textContent = d.stats.avg_score;
    avgEl.className = 'text-3xl font-bold mt-1 ' + (d.stats.avg_score >= 70 ? 'text-red-400' : d.stats.avg_score >= 40 ? 'text-yellow-400' : 'text-blue-400');

    updateHealth(d.health);
    document.getElementById('phone-number').textContent = d.phone_number;
    document.getElementById('refresh-time').textContent = 'Updated: ' + d.refreshed_at;

    renderPipeline('pipeline-hot', d.pipeline.hot);
    renderPipeline('pipeline-warm', d.pipeline.warm);
    renderPipeline('pipeline-cold', d.pipeline.cold);
    document.getElementById('hot-count').textContent = d.pipeline.hot.length;
    document.getElementById('warm-count').textContent = d.pipeline.warm.length;
    document.getElementById('cold-count').textContent = d.pipeline.cold.length;

    renderActivities(d.activities);
    renderCallbacks(d.callbacks);
    renderContacts(d.contacts);
    renderCampaigns(d.campaigns);
    renderHealthTable(d.number_health);
  } catch(e) {
    console.error('Refresh failed:', e);
  }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
