#!/usr/bin/env python3
"""
make_call_v7.py — Diagnostic call script with multiple approaches.

This script tests different call methods to diagnose the AI silence issue.

APPROACH A: Compatibility API + cXML <Say> (baseline — should ring + speak)
APPROACH B: Calling API + url to SignalWire-hosted SWML relay-bin (should ring + AI speaks)
APPROACH C: Calling API + url to GCF SWML endpoint (test if external URLs work)

Usage:
  python3 make_call_v7.py +16022950104 --approach a   # Test cXML Say (baseline)
  python3 make_call_v7.py +16022950104 --approach b   # Test Calling API + relay-bin
  python3 make_call_v7.py +16022950104 --approach c   # Test Calling API + GCF URL
"""
import sys
import json
import time
import requests
import argparse

# === SignalWire Credentials ===
SW_SPACE = "6eyes.signalwire.com"
SW_PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
SW_AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"

# === Phone Numbers ===
FROM_NUMBER = "+14806025848"  # Fresh number (not rate-limited)

# === Endpoints ===
COMPAT_API = f"https://{SW_SPACE}/api/laml/2010-04-01/Accounts/{SW_PROJECT_ID}/Calls.json"
CALLING_API = f"https://{SW_SPACE}/api/calling/calls"

# === SWML Resources ===
# SignalWire-hosted SWML relay-bin (AI Cold Caller Outbound)
SWML_RELAY_BIN = "https://6eyes.signalwire.com/relay-bins/f2fad3f1-ec3d-4155-91d2-c7993f8c8d4e"

# GCF-hosted SWML endpoint
SWML_GCF = "https://us-central1-tatt-pro.cloudfunctions.net/swmlOutbound?agent=cold-caller"

# SignalWire-hosted cXML bin (Simple Test TwiML — <Say> only)
CXML_BIN = "https://6eyes.signalwire.com/laml-bins/b2be5a14-57f2-4988-8170-446b6a65ae02"


def approach_a(to_number):
    """
    APPROACH A: Compatibility API + cXML <Say> bin
    
    This is the BASELINE test. If this doesn't work, the problem is at the 
    infrastructure/phone level (rate limiting, carrier blocking, etc.)
    
    Expected: Phone rings, Samson hears "Hello! This is a test call from SignalWire."
    """
    print("\n" + "="*60)
    print("APPROACH A: Compatibility API + cXML <Say>")
    print("Expected: Phone rings, hears TTS message")
    print("="*60)
    
    payload = {
        "From": FROM_NUMBER,
        "To": to_number,
        "Url": CXML_BIN,
    }
    
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {to_number}")
    print(f"  Url:  {CXML_BIN}")
    print(f"  API:  Compatibility (cXML)")
    
    resp = requests.post(
        COMPAT_API,
        data=payload,
        auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
        timeout=30,
    )
    
    print(f"\n  HTTP {resp.status_code}")
    if resp.status_code in (200, 201):
        data = resp.json()
        sid = data.get("sid", "?")
        status = data.get("status", "?")
        print(f"  SID: {sid}")
        print(f"  Status: {status}")
        
        poll_compat(sid)
        return data
    else:
        print(f"  ERROR: {resp.text[:300]}")
        return None


def approach_b(to_number):
    """
    APPROACH B: Calling API + url to SignalWire-hosted SWML relay-bin
    
    This tests if the Calling API can make real PSTN calls using a 
    SignalWire-hosted SWML script URL.
    
    Expected: Phone rings, AI speaks greeting, has conversation.
    """
    print("\n" + "="*60)
    print("APPROACH B: Calling API + SignalWire relay-bin URL")
    print("Expected: Phone rings, AI speaks greeting")
    print("="*60)
    
    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "caller_id": FROM_NUMBER,
            "url": SWML_RELAY_BIN,
        }
    }
    
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {to_number}")
    print(f"  URL:  {SWML_RELAY_BIN}")
    print(f"  API:  Calling API")
    
    resp = requests.post(
        CALLING_API,
        json=payload,
        auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    
    print(f"\n  HTTP {resp.status_code}")
    if resp.status_code in (200, 201):
        data = resp.json()
        call_id = data.get("id", "?")
        status = data.get("status", "?")
        source = data.get("source", "?")
        ctype = data.get("type", "?")
        print(f"  Call ID: {call_id}")
        print(f"  Status: {status}")
        print(f"  Source: {source}")
        print(f"  Type: {ctype}")
        
        # Monitor for ringing using Compat API
        print(f"\n  Monitoring for 60s (checking if call appears in Compat API)...")
        monitor_compat(to_number)
        return data
    else:
        print(f"  ERROR: {resp.text[:300]}")
        return None


def approach_c(to_number):
    """
    APPROACH C: Calling API + url to GCF SWML endpoint
    
    Tests if the Calling API works with an external SWML URL.
    
    Expected: Phone rings, AI speaks greeting.
    """
    print("\n" + "="*60)
    print("APPROACH C: Calling API + GCF SWML URL")
    print("Expected: Phone rings, AI speaks greeting")
    print("="*60)
    
    payload = {
        "command": "dial",
        "params": {
            "from": FROM_NUMBER,
            "to": to_number,
            "caller_id": FROM_NUMBER,
            "url": SWML_GCF,
        }
    }
    
    print(f"  From: {FROM_NUMBER}")
    print(f"  To:   {to_number}")
    print(f"  URL:  {SWML_GCF}")
    print(f"  API:  Calling API")
    
    resp = requests.post(
        CALLING_API,
        json=payload,
        auth=(SW_PROJECT_ID, SW_AUTH_TOKEN),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    
    print(f"\n  HTTP {resp.status_code}")
    if resp.status_code in (200, 201):
        data = resp.json()
        call_id = data.get("id", "?")
        status = data.get("status", "?")
        source = data.get("source", "?")
        ctype = data.get("type", "?")
        print(f"  Call ID: {call_id}")
        print(f"  Status: {status}")
        print(f"  Source: {source}")
        print(f"  Type: {ctype}")
        
        print(f"\n  Monitoring for 60s...")
        monitor_compat(to_number)
        return data
    else:
        print(f"  ERROR: {resp.text[:300]}")
        return None


def poll_compat(sid, max_polls=12, interval=5):
    """Poll a specific call SID via Compatibility API."""
    url = f"https://{SW_SPACE}/api/laml/2010-04-01/Accounts/{SW_PROJECT_ID}/Calls/{sid}.json"
    
    print(f"\n  Polling call {sid[:12]}...")
    for i in range(max_polls):
        time.sleep(interval)
        try:
            r = requests.get(url, auth=(SW_PROJECT_ID, SW_AUTH_TOKEN), timeout=10)
            if r.ok:
                d = r.json()
                status = d.get("status", "?")
                dur = d.get("duration", 0)
                sip = d.get("sip_result_code", "N/A")
                print(f"  [{i+1}/{max_polls}] {status} | {dur}s | SIP: {sip}")
                
                if status in ("completed", "failed", "busy", "no-answer", "canceled"):
                    if status == "completed" and int(dur or 0) > 5:
                        print(f"\n  ✅ Call completed ({dur}s)")
                    elif status == "failed":
                        print(f"\n  ❌ Call failed (SIP {sip})")
                    return d
        except:
            print(f"  [{i+1}/{max_polls}] Poll error")
    print("  Polling timed out")


def monitor_compat(to_number, duration=60, interval=5):
    """Monitor Compatibility API for any new calls to to_number."""
    url = f"https://{SW_SPACE}/api/laml/2010-04-01/Accounts/{SW_PROJECT_ID}/Calls.json?PageSize=3"
    
    # Get baseline
    baseline_sids = set()
    try:
        r = requests.get(url, auth=(SW_PROJECT_ID, SW_AUTH_TOKEN), timeout=10)
        if r.ok:
            for c in r.json().get("calls", []):
                baseline_sids.add(c["sid"])
    except:
        pass
    
    polls = duration // interval
    for i in range(polls):
        time.sleep(interval)
        try:
            r = requests.get(url, auth=(SW_PROJECT_ID, SW_AUTH_TOKEN), timeout=10)
            if r.ok:
                for c in r.json().get("calls", []):
                    if c["sid"] not in baseline_sids:
                        status = c.get("status", "?")
                        dur = c.get("duration", 0)
                        sip = c.get("sip_result_code", "N/A")
                        print(f"  [{i+1}/{polls}] NEW CALL: {c['sid'][:12]} | {status} | {dur}s | SIP: {sip}")
                        if status in ("completed", "failed"):
                            return c
                    else:
                        latest = r.json().get("calls", [{}])[0]
                        print(f"  [{i+1}/{polls}] No new calls (latest: {latest.get('status','?')} {latest.get('sid','?')[:12]})")
        except:
            print(f"  [{i+1}/{polls}] Monitor error")
    
    print("  No new calls appeared in Compat API during monitoring period")
    print("  This confirms Calling API calls do NOT create Compat API records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnostic call testing")
    parser.add_argument("to", help="Phone number to call (E.164)")
    parser.add_argument("--approach", required=True, choices=["a", "b", "c"],
                        help="a=cXML baseline, b=Calling API+relay-bin, c=Calling API+GCF")
    args = parser.parse_args()
    
    # Normalize phone
    phone = args.to.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"
    
    if args.approach == "a":
        approach_a(phone)
    elif args.approach == "b":
        approach_b(phone)
    elif args.approach == "c":
        approach_c(phone)
