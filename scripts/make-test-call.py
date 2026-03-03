#!/usr/bin/env python3
"""
Make a simple test call via SignalWire
Uses basic TwiML first, then we'll integrate Dialogflow CX
"""
import os
import sys
import json
from signalwire.rest import Client as SignalWireClient

# Load SignalWire config
CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    """Load SignalWire configuration"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def make_call(to_number):
    """Make a test call using SignalWire"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    
    print(f"📞 Making call...")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    print(f"   Space: {space_url}")
    
    # Initialize SignalWire client
    client = SignalWireClient(
        project_id,
        auth_token,
        signalwire_space_url=space_url
    )
    
    # Simple TwiML for first test
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">
        Hi, this is Paul calling for Samson from Fortinet.
        This is a test of the AI voice calling system.
        Can you hear me okay?
    </Say>
    <Pause length="3"/>
    <Say voice="Polly.Matthew">
        Great! Test call successful.
        Talk soon.
    </Say>
</Response>"""
    
    try:
        # Make the call
        call = client.calls.create(
            from_=from_number,
            to=to_number,
            twiml=twiml
        )
        
        print(f"\n✅ Call initiated!")
        print(f"   Call SID: {call.sid}")
        print(f"   Status: {call.status}")
        print(f"\n🎤 The call should be ringing now...")
        print(f"   It will say: 'Hi, this is Paul calling for Samson from Fortinet...'")
        
        return call
        
    except Exception as e:
        print(f"\n❌ Call failed: {e}")
        print(f"\nDebug info:")
        print(f"  Project ID: {project_id}")
        print(f"  Space URL: {space_url}")
        print(f"  From: {from_number}")
        print(f"  To: {to_number}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make-test-call.py <phone-number>")
        print("Example: python3 make-test-call.py 6022950104")
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
    print(f"🔊 MAKING TEST CALL")
    print(f"{'='*70}")
    
    call = make_call(phone)
    
    print(f"\n{'='*70}")
    print(f"✅ CALL IN PROGRESS")
    print(f"{'='*70}")
    print(f"\nCheck your phone! You should receive a call from {call.from_}")
    print(f"Call SID: {call.sid}")
