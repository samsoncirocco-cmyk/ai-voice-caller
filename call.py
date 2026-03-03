#!/usr/bin/env python3
"""
Make an outbound AI call via SignalWire Compatibility API.

Usage:
  python3 call.py +16025551234                  # Cold call (default)
  python3 call.py +16025551234 --discovery      # Discovery call
  python3 call.py +16025551234 --from +14806024668  # Use alternate caller ID
"""
import argparse
import json
import os
import sys
from urllib import request, parse, error

# ── SignalWire Credentials (load from config) ──────────────────────────
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "signalwire.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

PROJECT_ID = _cfg["project_id"]
API_TOKEN = _cfg["auth_token"]
SPACE = _cfg["space_url"]

# ── Defaults ───────────────────────────────────────────────────────────
DEFAULT_FROM = _cfg["phone_number"]  # +14806024668
BASE_URL = "https://signalwire:fortinet2026@caller.6eyes.dev"
API_URL = f"https://{SPACE}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"


def make_call(to_number: str, agent: str = "cold-caller", from_number: str = DEFAULT_FROM):
    """Place an outbound call via SignalWire Compatibility API."""
    agent_url = f"{BASE_URL}/{agent}"

    print(f"📞 Placing call...")
    print(f"   To:    {to_number}")
    print(f"   From:  {from_number}")
    print(f"   Agent: {agent}")
    print(f"   URL:   {agent_url}")
    print()

    # Build request
    data = parse.urlencode({
        "Url": agent_url,
        "To": to_number,
        "From": from_number,
    }).encode()

    # Basic auth: project_id:api_token
    import base64
    credentials = base64.b64encode(f"{PROJECT_ID}:{API_TOKEN}".encode()).decode()

    req = request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            print(f"✅ Call initiated!")
            print(f"   SID:    {result.get('sid', 'N/A')}")
            print(f"   Status: {result.get('status', 'N/A')}")
            return result
    except error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ API Error ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make an outbound AI call")
    parser.add_argument("to", help="Phone number to call (E.164 format, e.g. +16025551234)")
    parser.add_argument("--discovery", action="store_true", help="Use discovery agent instead of cold-caller")
    parser.add_argument("--from", dest="from_number", default=DEFAULT_FROM, help=f"Caller ID (default: {DEFAULT_FROM})")

    args = parser.parse_args()
    agent = "discovery" if args.discovery else "cold-caller"

    make_call(args.to, agent=agent, from_number=args.from_number)
