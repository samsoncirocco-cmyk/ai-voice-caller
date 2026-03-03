#!/usr/bin/env python3
"""
Make an outbound call using SignalWire REST API that connects to our running agent

This script:
1. Uses SignalWire REST API to initiate outbound call
2. Points SignalWire to our agent URL for SWML
3. Agent handles the conversation
"""
import os
import sys
import json
import requests
import base64

# SignalWire config
CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

# Public agent URL with Basic Auth credentials embedded
# Format: https://username:password@domain/
AGENT_URL = "https://signalwire:fortinet2026@310295e3d6a69b.lhr.life/"

def load_config():
    """Load SignalWire configuration"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def make_outbound_call(to_number):
    """
    Make an outbound call that connects to our Discovery Agent
    """
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    
    print(f"📞 Initiating outbound call...")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    print(f"   Agent URL: {AGENT_URL}")
    
    # Use SignalWire Compatibility API (similar to Twilio)
    url = f"https://{space_url}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json"
    
    # Create Basic Auth header
    auth_string = f"{project_id}:{auth_token}"
    auth_bytes = auth_string.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_string = base64_bytes.decode('ascii')
    
    headers = {
        "Authorization": f"Basic {base64_string}"
    }
    
    # Request payload - tell SignalWire to fetch SWML from our agent
    payload = {
        "From": from_number,
        "To": to_number,
        "Url": AGENT_URL,  # SignalWire will request SWML from this URL
        "Method": "POST"
    }
    
    try:
        print(f"\n📡 Making API request to SignalWire...")
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        
        # Check response
        if response.status_code in [200, 201]:
            call_data = response.json()
            call_sid = call_data.get('sid', 'unknown')
            
            print(f"\n✅ Outbound call initiated!")
            print(f"   Call SID: {call_sid}")
            print(f"   Status: {call_data.get('status', 'unknown')}")
            print(f"\n🎤 The Discovery Agent will:")
            print(f"   1. Introduce itself as Paul from Fortinet")
            print(f"   2. Ask for IT contact name")
            print(f"   3. Ask for direct phone number")
            print(f"   4. Confirm the information")
            print(f"   5. Save to Firestore")
            print(f"\n📱 Your phone should be ringing now!")
            
            return call_data
        else:
            print(f"\n❌ Call failed!")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
            sys.exit(1)
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ API request failed: {e}")
        print(f"\nDebug info:")
        print(f"  Project ID: {project_id}")
        print(f"  Space URL: {space_url}")
        print(f"  API URL: {url}")
        print(f"  From: {from_number}")
        print(f"  To: {to_number}")
        print(f"  Agent URL: {AGENT_URL}")
        
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make-outbound-call.py <phone-number>")
        print("Example: python3 make-outbound-call.py 6022950104")
        sys.exit(1)
    
    # Get phone number from command line
    phone = sys.argv[1]
    
    # Clean up phone number
    phone = phone.replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
    
    # Add +1 if not present (assume US)
    if not phone.startswith('+'):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith('1') and len(phone) == 11:
            phone = f"+{phone}"
        else:
            phone = f"+1{phone}"
    
    print(f"\n{'='*70}")
    print(f"🤖 MAKING AI-POWERED OUTBOUND CALL")
    print(f"{'='*70}")
    print(f"\nThis call will use the Discovery Agent (agents/discovery_agent.py)")
    print(f"Agent is running at: {AGENT_URL}")
    
    call = make_outbound_call(phone)
    
    print(f"\n{'='*70}")
    print(f"✅ CALL IN PROGRESS")
    print(f"{'='*70}")
    print(f"\nAnswer your phone and talk to Paul (the AI agent)!")
    print(f"\nCall SID: {call.get('sid', 'unknown')}")
    print(f"\nTo check status:")
    print(f"  python3 scripts/check-call-status.py {call.get('sid', 'unknown')}")
