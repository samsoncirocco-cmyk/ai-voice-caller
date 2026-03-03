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


if __name__ == "__main__":
    print("hooks.6eyes.dev webhook server starting on :18790")
    app.run(host="0.0.0.0", port=18790, debug=False)
