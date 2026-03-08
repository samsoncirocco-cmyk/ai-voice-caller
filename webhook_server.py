#!/usr/bin/env python3
"""
webhook_server.py — Central webhook server for hooks.6eyes.dev

Runs on port 18790 (cloudflared tunnel → hooks.6eyes.dev)

Routes:
  POST /voice-caller/post-call          ← SignalWire post_prompt_url callback
  POST /voice-caller/sfdc-sync          ← V2: SFDC live-sync (call_outcome | referral | new_lead)
  GET  /voice-caller/sfdc-sync/status   ← V2: Live-sync log tail + stats
  POST /outlook-sync                    ← Outlook inbox/calendar push from work machine
  GET  /outlook-sync                    ← Latest Outlook snapshot
  GET  /voice-caller/agents             ← Per-agent performance stats
  GET  /voice-caller/activity           ← Recent call log entries
  GET  /health                          ← Health check
  GET  /                                ← Status + route listing

Usage:
  python3 webhook_server.py
  # or via PM2: pm2 start webhook_server.py --name hooks-server --interpreter python3
"""

import json
import os
import re as _re
import subprocess
import threading
import time
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
            "POST /voice-caller/sfdc-sync          ← V2 live-sync (call_outcome|referral|new_lead)",
            "GET  /voice-caller/sfdc-sync/status   ← sync log tail + stats",
            "POST /outlook-sync",
            "GET  /outlook-sync",
            "GET  /voice-caller/agents",
            "GET  /voice-caller/activity",
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


OUTLOOK_SYNC_FILE = os.path.join(os.path.dirname(__file__), "logs", "outlook-sync-latest.json")
OUTLOOK_BRIDGE_TOKEN = "outlook-bridge-2026"


@app.route("/outlook-sync", methods=["POST"])
def outlook_sync():
    """
    Receives Outlook inbox + calendar data from the work machine bridge.
    Stores latest snapshot to logs/outlook-sync-latest.json.
    """
    token = request.headers.get("X-Bridge-Token", "")
    if token != OUTLOOK_BRIDGE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    data["source"] = data.get("source", "work-machine")

    email_count = len(data.get("inbox", data.get("emails", [])))
    cal_count = len(data.get("calendar", []))

    with open(OUTLOOK_SYNC_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[outlook-sync] {data['received_at']} — {email_count} emails, {cal_count} calendar events")
    return jsonify({"status": "ok", "emails": email_count, "calendar": cal_count}), 200


@app.route("/outlook-sync", methods=["GET"])
def outlook_sync_read():
    """Returns the latest Outlook sync snapshot."""
    token = request.headers.get("X-Bridge-Token", "")
    if token != OUTLOOK_BRIDGE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    if not os.path.exists(OUTLOOK_SYNC_FILE):
        return jsonify({"status": "no_data", "message": "No sync received yet"}), 404

    with open(OUTLOOK_SYNC_FILE) as f:
        data = json.load(f)
    return jsonify(data), 200


AGENT_PROFILES = {
    "6028985026": {
        "id": "602",
        "name": "Lane A — Paul",
        "label": "Municipal / Govt",
        "voice": "openai.onyx",
        "prompt": "prompts/paul.txt",
        "target": "City/County/Municipal",
        "phone": "+16028985026",
        "color": "violet",
    },
    "4806024668": {
        "id": "480-02",
        "name": "Lane B — Alex",
        "label": "Cold List",
        "voice": "gcloud.en-US-Casual-K",
        "prompt": "prompts/cold_outreach.txt",
        "target": "SLED Cold List",
        "phone": "+14806024668",
        "color": "orange",
    },
    "4808227861": {
        "id": "480-22",
        "name": "Lane C — Jackson",
        "label": "Cold List (B)",
        "voice": "openai.echo",
        "prompt": "prompts/jackson.txt",
        "target": "SLED Cold List",
        "phone": "+14808227861",
        "color": "emerald",
    },
    "4806025848": {
        "id": "480-58",
        "name": "Lane D — Mary",
        "label": "Municipal / Govt (B)",
        "voice": "openai.nova",
        "prompt": "prompts/mary.txt",
        "target": "City/County/Municipal",
        "phone": "+14806025848",
        "color": "rose",
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


# ══════════════════════════════════════════════════════════════════════════════
# V2 SFDC LIVE SYNC
# Receives structured outbound-event objects and immediately upserts them into
# Salesforce via sfdc_push.py (call outcomes) or direct sf-CLI Task creation
# (referrals and new leads).  All attempts are durably logged and retried with
# exponential back-off so no event is silently dropped.
# ══════════════════════════════════════════════════════════════════════════════

_SFDC_SYNC_LOG  = os.path.join(LOG_DIR, "sfdc-live-sync.jsonl")
_SFDC_MAX_TRIES = 3          # total attempts (1 initial + 2 retries)
_SFDC_BASE_WAIT = 5          # seconds; doubles each retry → 5 / 10 / 20
_SFDC_SF_ALIAS  = "fortinet"
_SFDC_SCRIPT    = os.path.join(os.path.dirname(__file__), "sfdc_push.py")


# ── structured logger ─────────────────────────────────────────────────────────

def _sync_log(event: dict, status: str, message: str, attempt: int = 0) -> None:
    """Append one JSON line to sfdc-live-sync.jsonl and echo to stdout."""
    entry = {
        "logged_at":  datetime.now(timezone.utc).isoformat(),
        "event_type": event.get("event_type", "unknown"),
        "call_id":    event.get("call_id"),
        "status":     status,      # pending | retrying | success | failed | skipped
        "attempt":    attempt,
        "message":    message[:500],
    }
    with open(_SFDC_SYNC_LOG, "a") as _f:
        _f.write(json.dumps(entry) + "\n")
    print(
        f"[sfdc-sync] {status:8s} | {entry['event_type']:12s} | "
        f"call={entry['call_id'] or '—'} | attempt={attempt} | {message[:100]}"
    )


# ── sf CLI helpers ────────────────────────────────────────────────────────────

def _run_sf_cmd(args: list, timeout: int = 30) -> tuple:
    """Run a `sf` CLI command. Returns (success: bool, stdout: str)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=os.path.dirname(__file__),
        )
    except subprocess.TimeoutExpired:
        return False, f"sf CLI timed out after {timeout}s"
    except FileNotFoundError:
        return False, "sf CLI not found — check PATH"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, proc.stdout


def _sfdc_lookup_account(phone: str) -> dict | None:
    """
    Look up a Salesforce Account by phone number (last 10 digits).
    Returns {"Id": "...", "Name": "..."} or None.
    """
    if not phone:
        return None
    digits = _re.sub(r"\D+", "", phone)
    last10 = digits[-10:] if len(digits) >= 10 else digits
    if not last10:
        return None

    soql = f"SELECT Id, Name FROM Account WHERE Phone LIKE '%{last10}%' LIMIT 1"
    ok, out = _run_sf_cmd([
        "sf", "data", "query",
        "--query", soql,
        "--json",
        "--target-org", _SFDC_SF_ALIAS,
    ])
    if not ok:
        return None
    try:
        records = json.loads(out).get("result", {}).get("records", [])
        if not records:
            return None
        return {"Id": records[0]["Id"], "Name": records[0].get("Name", "")}
    except Exception:
        return None


def _sfdc_create_task(
    account_id: str,
    subject: str,
    date_str: str,
    description: str,
    call_type: str = "Outbound",
) -> tuple:
    """
    Create a Completed Task in Salesforce linked to an Account.
    Returns (success: bool, message: str).
    """
    # Escape single-quotes in field values so the CLI doesn't choke
    def _esc(s: str) -> str:
        return str(s).replace("'", "\\'").replace("\n", " | ")[:1000]

    values = (
        f"Subject='{_esc(subject)}' "
        f"Status='Completed' "
        f"ActivityDate='{date_str}' "
        f"WhatId='{account_id}' "
        f"Type='Call' "
        f"CallType='{call_type}' "
        f"Description='{_esc(description)}'"
    )
    ok, out = _run_sf_cmd([
        "sf", "data", "create", "record",
        "--sobject", "Task",
        "--values", values,
        "--json",
        "--target-org", _SFDC_SF_ALIAS,
    ])
    if not ok:
        return False, out

    try:
        task_id = json.loads(out).get("result", {}).get("id", "")
        return True, f"Task {task_id} created on {account_id}"
    except Exception as exc:
        return False, f"Task parse error: {exc}"


def _event_date(event: dict) -> str:
    """Extract YYYY-MM-DD from event timestamp (defaults to today UTC)."""
    ts = event.get("timestamp")
    if ts:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.date().isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_in_call_log(event: dict) -> None:
    """
    If a call_outcome event isn't already in call_summaries.jsonl, append it
    so that sfdc_push.py can find it by call_id.
    """
    call_id = event.get("call_id")
    if not call_id:
        return

    # Check existing log
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as _f:
            for _line in _f:
                try:
                    if json.loads(_line.strip()).get("call_id") == call_id:
                        return  # already present
                except Exception:
                    pass

    entry = {
        "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "call_id":   call_id,
        "to":        event.get("to", ""),
        "from":      event.get("from", ""),
        "summary":   event.get("summary", ""),
        "raw":       event,
        "_source":   "sfdc-sync-webhook",
    }
    with open(LOG_FILE, "a") as _f:
        _f.write(json.dumps(entry) + "\n")


# ── per-event-type push handlers ──────────────────────────────────────────────

def _push_call_outcome(event: dict) -> tuple:
    """
    Push a call_outcome event to SFDC via sfdc_push.py.
    sfdc_push.py looks up the Account by phone then creates a Task.
    """
    call_id = event.get("call_id", "").strip()
    if not call_id:
        return False, "call_id is required for call_outcome events"

    # Make sure the record exists in call_summaries.jsonl for sfdc_push.py
    _ensure_in_call_log(event)

    ok, out = _run_sf_cmd(
        ["python3", _SFDC_SCRIPT, "--call-id", call_id],
        timeout=60,
    )
    output = out.strip() or ("ok" if ok else "unknown error")
    return ok, output


def _push_referral(event: dict) -> tuple:
    """
    Push a referral event — creates a SFDC Task on the caller's Account.
    Fields: referral_name, referral_org, referral_phone (all optional but useful).
    """
    phone = event.get("to") or event.get("phone", "")
    account = _sfdc_lookup_account(phone)
    if not account:
        return False, f"No SFDC Account found for phone '{phone}'"

    referral_name  = event.get("referral_name", "").strip()
    referral_org   = event.get("referral_org", "").strip()
    referral_phone = event.get("referral_phone", "").strip()
    date_str       = _event_date(event)
    call_id        = event.get("call_id", "n/a")
    summary        = event.get("summary", "")

    subject = f"AI Caller — Referral: {referral_name or referral_org or 'unknown'}"
    description = (
        f"Referral captured during AI outbound call ({date_str}).\n"
        f"Referred Name : {referral_name}\n"
        f"Referred Org  : {referral_org}\n"
        f"Referred Phone: {referral_phone}\n"
        f"Call ID       : {call_id}\n"
        f"Summary       : {summary}"
    )
    return _sfdc_create_task(account["Id"], subject, date_str, description)


def _push_new_lead(event: dict) -> tuple:
    """
    Push a new_lead event — creates a SFDC Task capturing the lead details.
    Fields: lead_name, lead_org, lead_phone, lead_email (all optional but useful).
    Falls back to the caller's account when the lead's phone isn't in SFDC.
    """
    lead_phone = event.get("lead_phone", "").strip()
    caller_phone = event.get("to") or event.get("phone", "")

    # Try lead's org first, then caller's org
    account = _sfdc_lookup_account(lead_phone) or _sfdc_lookup_account(caller_phone)
    if not account:
        return False, (
            f"No SFDC Account found for lead_phone='{lead_phone}' "
            f"or caller='{caller_phone}'"
        )

    lead_name  = event.get("lead_name", "").strip()
    lead_org   = event.get("lead_org", "").strip()
    lead_email = event.get("lead_email", "").strip()
    date_str   = _event_date(event)
    call_id    = event.get("call_id", "n/a")
    summary    = event.get("summary", "")

    subject = f"AI Caller — New Lead: {lead_name or lead_org or 'unknown'}"
    description = (
        f"New lead captured during AI outbound call ({date_str}).\n"
        f"Lead Name  : {lead_name}\n"
        f"Lead Org   : {lead_org}\n"
        f"Lead Phone : {lead_phone}\n"
        f"Lead Email : {lead_email}\n"
        f"Call ID    : {call_id}\n"
        f"Summary    : {summary}"
    )
    return _sfdc_create_task(account["Id"], subject, date_str, description)


# Registry — add new event types here
_SFDC_HANDLERS: dict = {
    "call_outcome": _push_call_outcome,
    "referral":     _push_referral,
    "new_lead":     _push_new_lead,
}


# ── retry engine ──────────────────────────────────────────────────────────────

def _sync_with_retry(event: dict) -> tuple:
    """
    Attempt to push *event* to SFDC.  On failure, retry up to _SFDC_MAX_TRIES
    total attempts using exponential back-off (_SFDC_BASE_WAIT × 2^n seconds).
    Returns (success: bool, final_message: str).
    """
    event_type = event.get("event_type", "")
    handler = _SFDC_HANDLERS.get(event_type)
    if handler is None:
        msg = f"Unknown event_type '{event_type}'. Valid: {list(_SFDC_HANDLERS)}"
        _sync_log(event, "failed", msg)
        return False, msg

    delay = _SFDC_BASE_WAIT
    last_message = ""

    for attempt in range(1, _SFDC_MAX_TRIES + 1):
        status = "pending" if attempt == 1 else "retrying"
        _sync_log(event, status, f"attempt {attempt}/{_SFDC_MAX_TRIES}", attempt)

        try:
            ok, message = handler(event)
        except Exception as exc:
            ok, message = False, f"Unhandled exception: {exc}"

        last_message = message

        if ok:
            _sync_log(event, "success", message, attempt)
            return True, message

        final_status = "failed" if attempt == _SFDC_MAX_TRIES else "retrying"
        _sync_log(event, final_status, message, attempt)

        if attempt < _SFDC_MAX_TRIES:
            time.sleep(delay)
            delay *= 2  # exponential back-off: 5 → 10 → 20s

    return False, last_message


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/voice-caller/sfdc-sync", methods=["POST"])
def sfdc_live_sync_route():
    """
    V2 SFDC Live Sync — receive an outbound event and immediately upsert to SF.

    Request body (JSON):
      {
        "event_type": "call_outcome" | "referral" | "new_lead",  ← REQUIRED
        "call_id":    "<uuid>",          ← required for call_outcome
        "timestamp":  "<ISO8601>",       ← optional, defaults to now UTC
        "to":         "+16055551234",    ← target phone (used for Account lookup)
        "from":       "+16028985026",    ← caller phone
        "summary":    "<call summary>",

        # call_outcome fields (summary is the primary payload):
        "outcome":    "Connected|Meeting Booked|...",

        # referral fields:
        "referral_name":  "Jane Doe",
        "referral_org":   "Aberdeen USD",
        "referral_phone": "+16055559999",

        # new_lead fields:
        "lead_name":  "John Smith",
        "lead_org":   "Watertown School District",
        "lead_phone": "+16055550000",
        "lead_email": "john@watertown.k12.sd.us"
      }

    Response:
      200  {"status": "synced",   "event_type": "...", "message": "..."}
      202  {"status": "pending",  ...}   ← first attempt still running (rare)
      400  {"error": "...",       "valid_types": [...]}
      502  {"status": "failed",   "event_type": "...", "message": "...", "retries": N}
    """
    data = request.json or {}
    event_type = data.get("event_type", "").strip()

    if not event_type:
        return jsonify({
            "error": "event_type is required",
            "valid_types": list(_SFDC_HANDLERS),
        }), 400

    if event_type not in _SFDC_HANDLERS:
        return jsonify({
            "error": f"Unknown event_type '{event_type}'",
            "valid_types": list(_SFDC_HANDLERS),
        }), 400

    # Stamp timestamp if caller omitted it
    if not data.get("timestamp"):
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

    event = dict(data)  # snapshot before threading
    result: dict = {"ok": False, "message": ""}

    def _run() -> None:
        ok, msg = _sync_with_retry(event)
        result["ok"]      = ok
        result["message"] = msg

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # Block up to 90 s: covers 3 attempts × (5+10+20 s back-off) comfortably.
    # If SF is just slow the caller waits but gets a definitive answer.
    t.join(timeout=90)

    if t.is_alive():
        # Still running — background thread will finish; return 202
        return jsonify({
            "status":     "pending",
            "event_type": event_type,
            "message":    "Sync in progress (90 s timeout exceeded, continuing in background)",
        }), 202

    if result["ok"]:
        return jsonify({
            "status":     "synced",
            "event_type": event_type,
            "message":    result["message"],
        }), 200

    return jsonify({
        "status":     "failed",
        "event_type": event_type,
        "message":    result["message"],
        "retries":    _SFDC_MAX_TRIES,
    }), 502


@app.route("/voice-caller/sfdc-sync/status", methods=["GET"])
def sfdc_live_sync_status():
    """
    Return a tail of sfdc-live-sync.jsonl + aggregate stats.
    Query params:
      ?n=50   — number of log entries to return (default 50, max 500)
    """
    try:
        n = min(int(request.args.get("n", 50)), 500)
    except ValueError:
        n = 50

    entries = []
    stats: dict = {
        "total":   0,
        "success": 0,
        "failed":  0,
        "retrying": 0,
        "pending": 0,
    }
    by_event_type: dict = {}

    if os.path.exists(_SFDC_SYNC_LOG):
        with open(_SFDC_SYNC_LOG) as _f:
            lines = [l.strip() for l in _f if l.strip()]

        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Aggregate totals (across entire file, not just the tail)
            s = rec.get("status", "")
            if s in stats:
                stats[s] += 1
            stats["total"] += 1

            et = rec.get("event_type", "unknown")
            by_event_type.setdefault(et, {"total": 0, "success": 0, "failed": 0})
            by_event_type[et]["total"] += 1
            if s == "success":
                by_event_type[et]["success"] += 1
            elif s == "failed":
                by_event_type[et]["failed"] += 1

        # Return last N entries in reverse-chronological order
        for line in reversed(lines[-n:]):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return jsonify({
        "log_file":      _SFDC_SYNC_LOG,
        "stats":         stats,
        "by_event_type": by_event_type,
        "entries":       entries,
        "count":         len(entries),
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
# END V2 SFDC LIVE SYNC
# ══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    print("hooks.6eyes.dev webhook server starting on :18790")
    app.run(host="0.0.0.0", port=18790, debug=False)
