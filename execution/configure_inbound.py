#!/usr/bin/env python3
"""
configure_inbound.py — Configure SignalWire phone numbers for inbound call handling.

Sets the voice_url on each local-presence number to point to our inbound
handler at hooks.6eyes.dev/voice-caller/inbound.

Usage:
  python3 execution/configure_inbound.py --dry-run    # Preview changes
  python3 execution/configure_inbound.py --apply       # Apply changes
  python3 execution/configure_inbound.py --status      # Show current config

Note: Requires SignalWire REST API access.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "signalwire.json"

with open(CONFIG_FILE) as f:
    CFG = json.load(f)

SPACE_URL = CFG["space_url"]
PROJECT_ID = CFG["project_id"]
AUTH_TOKEN = CFG["auth_token"]

AUTH_B64 = base64.b64encode(f"{PROJECT_ID}:{AUTH_TOKEN}".encode()).decode()
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": f"Basic {AUTH_B64}",
}

INBOUND_URL = "https://hooks.6eyes.dev/voice-caller/inbound"
STATUS_CALLBACK = "https://hooks.6eyes.dev/voice-caller/inbound-callback"

# All our numbers (local presence + originals)
NUMBERS = {
    "+16053035984": {"label": "SD Local (605)", "state": "SD"},
    "+14022755273": {"label": "NE Local (402)", "state": "NE"},
    "+15152987809": {"label": "IA Local (515)", "state": "IA"},
    "+16028985026": {"label": "Original (602)", "state": "AZ"},
    "+14806024668": {"label": "Alex Lane (480-02)", "state": "AZ"},
    "+14808227861": {"label": "Jackson Lane (480-22)", "state": "AZ"},
    "+14806025848": {"label": "Mary Lane (480-58)", "state": "AZ"},
}


def list_numbers():
    """List all phone numbers in the SignalWire project."""
    url = f"https://{SPACE_URL}/api/relay/rest/phone_numbers"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        print(f"❌ Failed to list numbers: {resp.status_code} — {resp.text[:200]}")
        return []
    data = resp.json()
    return data.get("data", data.get("phone_numbers", []))


def get_number_config(phone_sid: str):
    """Get configuration for a specific phone number."""
    url = f"https://{SPACE_URL}/api/relay/rest/phone_numbers/{phone_sid}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return None
    return resp.json()


def update_number(phone_sid: str, voice_url: str, dry_run: bool = False):
    """Update a phone number's voice URL for inbound handling."""
    url = f"https://{SPACE_URL}/api/relay/rest/phone_numbers/{phone_sid}"
    payload = {
        "call_handler": "laml_webhooks",
        "call_receive_mode": "voice",
        "call_request_url": voice_url,
        "call_request_method": "POST",
    }

    if dry_run:
        print(f"  [DRY RUN] Would update {phone_sid}")
        print(f"    voice_url → {voice_url}")
        return True

    resp = requests.put(url, headers=HEADERS, data=payload, timeout=15)
    if resp.status_code in (200, 201):
        print(f"  ✅ Updated successfully")
        return True
    else:
        print(f"  ❌ Failed: {resp.status_code} — {resp.text[:200]}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Configure SignalWire inbound handling")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--status", action="store_true", help="Show current config")
    args = parser.parse_args()

    print("📱 Fetching SignalWire phone numbers...")
    numbers = list_numbers()

    if not numbers:
        print("No numbers found or API error.")
        return

    # Map our known numbers to their SIDs
    number_map = {}
    for num in numbers:
        phone = num.get("phone_number", num.get("number", ""))
        sid = num.get("id", num.get("sid", ""))
        number_map[phone] = {
            "sid": sid,
            "current_url": num.get("call_request_url", "none"),
            "handler": num.get("call_handler", "unknown"),
            **num,
        }

    if args.status or not args.apply:
        print(f"\n{'Number':<18s} {'Label':<25s} {'Handler':<15s} {'Current Voice URL'}")
        print("─" * 100)
        for phone, info in sorted(NUMBERS.items()):
            if phone in number_map:
                nm = number_map[phone]
                cur_url = nm.get("current_url", "not set")
                handler = nm.get("handler", "?")
                marker = "✅" if INBOUND_URL in str(cur_url) else "⚠️"
                print(f"{phone:<18s} {info['label']:<25s} {handler:<15s} {marker} {cur_url}")
            else:
                print(f"{phone:<18s} {info['label']:<25s} {'NOT FOUND':<15s}")

    if args.apply or args.dry_run:
        print(f"\n{'Applying' if args.apply else 'Previewing'} inbound handler configuration...")
        for phone, info in NUMBERS.items():
            if phone not in number_map:
                print(f"\n⚠️  {phone} ({info['label']}) — not found in SignalWire project")
                continue

            nm = number_map[phone]
            sid = nm["sid"]
            cur_url = nm.get("current_url", "")

            if INBOUND_URL in str(cur_url):
                print(f"\n✅ {phone} ({info['label']}) — already configured")
                continue

            print(f"\n📞 {phone} ({info['label']})")
            update_number(sid, INBOUND_URL, dry_run=args.dry_run)

    if not args.apply and not args.dry_run and not args.status:
        print("\nUse --status to check, --dry-run to preview, or --apply to configure.")


if __name__ == "__main__":
    main()
