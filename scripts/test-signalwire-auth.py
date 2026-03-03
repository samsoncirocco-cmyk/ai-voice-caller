#!/usr/bin/env python3
"""
Test SignalWire authentication and list available phone numbers
"""
import os
import sys
import json
from signalwire.rest import Client as SignalWireClient

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def test_auth():
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    
    print(f"Testing SignalWire authentication...")
    print(f"  Project ID: {project_id}")
    print(f"  Space: {space_url}")
    
    try:
        # Initialize client
        client = SignalWireClient(
            project_id,
            auth_token,
            signalwire_space_url=space_url
        )
        
        print(f"\n✅ Client initialized")
        
        # Try to list phone numbers
        print(f"\nFetching phone numbers...")
        numbers = client.incoming_phone_numbers.list()
        
        print(f"\n✅ API call successful!")
        print(f"\nPhone numbers in account:")
        for number in numbers:
            print(f"  • {number.phone_number} (SID: {number.sid})")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_auth()
