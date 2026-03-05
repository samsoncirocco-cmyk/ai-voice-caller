#!/usr/bin/env python3
"""
webhook_server.py — Central webhook server for hooks.6eyes.dev

Runs on port 18790 (cloudflared tunnel → hooks.6eyes.dev)

Routes:
  POST /voice-caller/post-call   ← SignalWire post_prompt_url callback
  GET  /health                   ← Health check
  GET  /                         ← Status

Usage:
  python3 webhook_server.py
  # or via PM2: pm2 start webhook_server.py --name hooks-server --interpreter python3
"""

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)

LOG_DIR  = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "call_summaries.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "server": "hooks.6eyes.dev", "port": 18790}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "routes": [
            "POST /voice-caller/post-call",
            "GET  /health",
        ]
    }), 200


@app.route("/voice-caller/post-call", methods=["POST"])
def post_call_summary():
    """
    Receives SignalWire post_prompt_url callback after each AI call.
    Logs to logs/call_summaries.jsonl (flat file, easy to query).
    """
    data = request.json or {}

    call_id = data.get("call_id", "unknown")
    # SignalWire sends post_prompt_data.raw (not post_prompt_result)
    post_prompt_data = data.get("post_prompt_data", {})
    summary = (
        post_prompt_data.get("substituted")
        or post_prompt_data.get("raw")
        or data.get("post_prompt_result", data.get("result", ""))
    )

    swml_call = data.get("SWMLCall", {})
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_id": call_id,
        "to": swml_call.get("to_number", data.get("to", "")),
        "from": swml_call.get("from_number", data.get("from", "")),
        "summary": summary,
        "raw": data
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"[{log_entry['timestamp']}] Call {call_id} logged — {str(summary)[:100]}")

    # Auto-push to Salesforce in background (non-blocking)
    def push_to_sf(call_id):
        try:
            script = os.path.join(os.path.dirname(__file__), "sfdc_push.py")
            result = subprocess.run(
                ["python3", script, "--call-id", call_id],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "SF_DISABLE_AUTOUPDATE": "true"}
            )
            print(f"[SF push] call_id={call_id} → {result.stdout.strip() or result.stderr.strip()}")
        except Exception as e:
            print(f"[SF push] Error for call_id={call_id}: {e}")

    threading.Thread(target=push_to_sf, args=(call_id,), daemon=True).start()

    return jsonify({"status": "logged", "call_id": call_id}), 200


AGENT_PROFILES = {
    "6028985026": {
        "id": "602",
        "name": "Lane A — 602",
        "label": "Municipal / Govt",
        "voice": "openai.onyx",
        "target": "City/County/Municipal",
        "phone": "+16028985026",
        "color": "violet",
    },
    "4806024668": {
        "id": "480",
        "name": "Lane B — 480",
        "label": "Cold List",
        "voice": "gcloud.en-US-Casual-K",
        "target": "SLED Cold List",
        "phone": "+14806024668",
        "color": "orange",
    },
}

def _get_agent_profile(from_number: str) -> dict:
    """Look up agent profile by FROM number."""
    import re as _re
    digits = _re.sub(r"\D", "", str(from_number))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return AGENT_PROFILES.get(digits, {
        "id": digits[:3] if digits else "unknown",
        "name": f"Lane — {digits[:3] or '?'}",
        "label": "Unknown",
        "voice": "unknown",
        "target": "unknown",
        "phone": from_number,
        "color": "zinc",
    })


def _parse_summary(summary: str, from_number: str) -> dict:
    """Extract structured fields from Paul's post-call summary text."""
    s = summary or ""
    sl = s.lower()

    # Outcome detection
    if any(x in sl for x in ["meeting booked", "demo booked", "scheduled a meeting", "agreed to meet"]):
        outcome = "Meeting Booked"
    elif any(x in sl for x in ["voicemail", "left a message", "left message"]):
        outcome = "Voicemail"
    elif any(x in sl for x in ["no answer", "didn't answer", "did not answer", "rang out", "not available"]):
        outcome = "No Answer"
    elif any(x in sl for x in ["not interested", "do not call", "remove from", "hang up", "hung up"]):
        outcome = "Not Interested"
    elif any(x in sl for x in ["spoke with", "interest level", "connected"]):
        outcome = "Connected"
    elif s.strip():
        outcome = "Connected"
    else:
        outcome = "No Answer"

    # Interest level (0-5 or 0-10)
    interest = None
    import re as _re
    m = _re.search(r"interest[^\d]*(\d+)", sl)
    if m:
        interest = int(m.group(1))

    # Who was spoken with
    contact_name = None
    contact_title = None
    m = _re.search(r"spoke with[:\s]+([^\n\-,\.]+)", sl)
    if m:
        contact_name = m.group(1).strip().title()
    m = _re.search(r"role[:\s]+([^\n\-,\.]+)", sl)
    if not m:
        m = _re.search(r"(it director|technology director|superintendent|principal|cio|network admin|it coordinator|director of technology)[^\n]*", sl)
    if m:
        contact_title = m.group(1).strip().title()

    # Agent/lane from FROM number
    agent = _get_agent_profile(from_number)

    return {
        "outcome": outcome,
        "interest": interest,
        "contact_name": contact_name,
        "contact_title": contact_title,
        "lane": agent["name"],
        "agent_id": agent["id"],
    }


@app.route("/voice-caller/agents", methods=["GET"])
def agent_stats():
    """
    Returns per-agent performance stats aggregated from call_summaries.jsonl.
    Each entry = one configured SignalWire phone number / agent profile.
    """
    # Seed with known profiles so agents with zero calls still appear
    stats = {}
    for digits, profile in AGENT_PROFILES.items():
        stats[profile["id"]] = {
            "agent_id":    profile["id"],
            "name":        profile["name"],
            "label":       profile["label"],
            "voice":       profile["voice"],
            "target":      profile["target"],
            "phone":       profile["phone"],
            "color":       profile["color"],
            "total":       0,
            "meetings":    0,
            "connected":   0,
            "voicemail":   0,
            "no_answer":   0,
            "not_interested": 0,
            "interest_sum": 0,
            "interest_count": 0,
        }

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                from_num = rec.get("from", "")
                parsed = _parse_summary(rec.get("summary", ""), from_num)
                aid = parsed["agent_id"]

                if aid not in stats:
                    agent = _get_agent_profile(from_num)
                    stats[aid] = {
                        "agent_id": aid,
                        "name": agent["name"],
                        "label": agent["label"],
                        "voice": agent["voice"],
                        "target": agent["target"],
                        "phone": agent["phone"],
                        "color": agent["color"],
                        "total": 0, "meetings": 0, "connected": 0,
                        "voicemail": 0, "no_answer": 0, "not_interested": 0,
                        "interest_sum": 0, "interest_count": 0,
                    }

                s = stats[aid]
                s["total"] += 1
                outcome = parsed["outcome"]
                if outcome == "Meeting Booked":      s["meetings"] += 1
                elif outcome == "Connected":         s["connected"] += 1
                elif outcome == "Voicemail":         s["voicemail"] += 1
                elif outcome == "No Answer":         s["no_answer"] += 1
                elif outcome == "Not Interested":    s["not_interested"] += 1

                if parsed["interest"] is not None:
                    s["interest_sum"] += parsed["interest"]
                    s["interest_count"] += 1

    # Compute derived metrics
    result = []
    for s in stats.values():
        t = s["total"] or 1
        s["connect_rate"]  = round(((s["meetings"] + s["connected"]) / t) * 100)
        s["meeting_rate"]  = round((s["meetings"] / t) * 100)
        s["avg_interest"]  = round(s["interest_sum"] / s["interest_count"], 1) if s["interest_count"] else None
        result.append(s)

    result.sort(key=lambda x: x["meeting_rate"], reverse=True)
    return jsonify({"agents": result}), 200


@app.route("/voice-caller/activity", methods=["GET"])
def call_activity():
    """
    Returns the last N entries from call_summaries.jsonl as structured JSON.
    Query params:
      ?n=50    — number of entries (default 50, max 200)
      ?outcome=Connected — filter by outcome
    """
    try:
        n = min(int(request.args.get("n", 50)), 200)
    except ValueError:
        n = 50
    outcome_filter = request.args.get("outcome", "").strip().lower()

    entries = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            from_num = rec.get("from", "")
            parsed = _parse_summary(rec.get("summary", ""), from_num)
            agent = _get_agent_profile(from_num)
            entry = {
                "call_id":       rec.get("call_id", ""),
                "timestamp":     rec.get("timestamp", ""),
                "to":            rec.get("to", ""),
                "from_number":   from_num,
                "summary":       rec.get("summary", ""),
                "outcome":       parsed["outcome"],
                "interest":      parsed["interest"],
                "contact_name":  parsed["contact_name"],
                "contact_title": parsed["contact_title"],
                "lane":          parsed["lane"],
                "agent_id":      parsed["agent_id"],
                "agent_label":   agent["label"],
                "agent_voice":   agent["voice"],
                "agent_target":  agent["target"],
            }

            if outcome_filter and entry["outcome"].lower() != outcome_filter:
                continue

            entries.append(entry)
            if len(entries) >= n:
                break

    return jsonify({
        "count": len(entries),
        "entries": entries,
    }), 200


if __name__ == "__main__":
    print("hooks.6eyes.dev webhook server starting on :18790")
    app.run(host="0.0.0.0", port=18790, debug=False)
