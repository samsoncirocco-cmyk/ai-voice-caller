#!/usr/bin/env python3
"""
Make an outbound call using SignalWire that connects to Discovery Mode agent
"""
import os
import sys
import json
from signalwire.rest import Client as SignalWireClient

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def make_agent_call(to_number):
    """Make a call with inline SWML that acts like Discovery Mode agent"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    
    print(f"📞 Initiating AI agent call...")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    
    client = SignalWireClient(
        project_id,
        auth_token,
        signalwire_space_url=space_url
    )
    
    # Create TwiML with short delay for audio connection
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Pause length="2"/>
    <Say voice="Polly.Matthew">
        Hi, this is Paul calling for Samson from Fortinet. 
        This is a test of the voice calling system.
        Can you hear me okay?
    </Say>
    <Pause length="3"/>
    <Say voice="Polly.Matthew">
        Great! The system is working. Talk soon.
    </Say>
</Response>"""
    
    try:
        # Make the call with TwiML
        call = client.calls.create(
            from_=from_number,
            to=to_number,
            twiml=twiml
        )
        
        print(f"\n✅ AI agent call initiated!")
        print(f"   Call SID: {call.sid}")
        print(f"   Status: {call.status}")
        print(f"\n🤖 The AI agent will introduce itself and ask for IT contact info")
        
        return call
        
    except Exception as e:
        print(f"\n❌ Call failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make-agent-call.py <phone-number>")
        sys.exit(1)
    
    phone = sys.argv[1]
    phone = phone.replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
    
    if not phone.startswith('+'):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith('1') and len(phone) == 11:
            phone = f"+{phone}"
    
    print(f"\n{'='*70}")
    print(f"🤖 MAKING AI AGENT CALL")
    print(f"{'='*70}")
    
    call = make_agent_call(phone)
    
    print(f"\n{'='*70}")
    print(f"✅ AI AGENT IS CALLING")
    print(f"{'='*70}")
    print(f"\nAnswer your phone! The AI will:")
    print(f"  1. Introduce itself as Paul from Fortinet")
    print(f"  2. Ask who handles IT")
    print(f"  3. Ask for their direct phone number")
    print(f"  4. Confirm what it heard")
    print(f"  5. Thank you and end the call")
