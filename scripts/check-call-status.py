#!/usr/bin/env python3
"""
Check the status of a call by SID
"""
import os
import sys
import json
from signalwire.rest import Client as SignalWireClient

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def check_call(call_sid):
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    
    print(f"Checking call status for SID: {call_sid}")
    
    client = SignalWireClient(
        project_id,
        auth_token,
        signalwire_space_url=space_url
    )
    
    try:
        call = client.calls(call_sid).fetch()
        
        print(f"\n📞 Call Details:")
        print(f"  From: {call.from_}")
        print(f"  To: {call.to}")
        print(f"  Status: {call.status}")
        print(f"  Direction: {call.direction}")
        print(f"  Duration: {call.duration} seconds")
        print(f"  Price: ${call.price} {call.price_unit}")
        
        if hasattr(call, 'error_code') and call.error_code:
            print(f"\n❌ Error Code: {call.error_code}")
            print(f"  Error Message: {call.error_message}")
        
        return call
        
    except Exception as e:
        print(f"\n❌ Failed to fetch call: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check-call-status.py <call-sid>")
        sys.exit(1)
    
    call_sid = sys.argv[1]
    check_call(call_sid)
