#!/usr/bin/env python3
"""
Make an outbound AI call using SignalWire Agents SDK + REST API

This script:
1. Creates SWML configuration for an AI agent
2. Makes an outbound call using SignalWire native REST API with inline SWML
"""
import os
import sys
import json
import requests
import base64

# Load config
CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    """Load SignalWire configuration"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def create_ai_swml():
    """
    Create SWML for an AI agent
    
    This SWML configures a real AI agent that can listen and respond,
    not just play pre-recorded messages.
    """
    swml = {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "answer": {}  # Answer the call
                },
                {
                    "ai": {
                        "prompt": {
                            "temperature": 0.7,
                            "top_p": 0.9,
                            "text": """You are Paul, a friendly sales representative from Fortinet.

You're calling to gather IT decision-maker contact information.

INSTRUCTIONS:
1. Introduce yourself: "Hi, this is Paul calling from Fortinet"
2. Briefly state your purpose: "I'm trying to reach the person who handles IT and cybersecurity"
3. Ask who that person is
4. Ask for their direct phone number
5. Confirm the information back to them
6. Thank them and end the call

Keep responses brief and professional. If they're not interested, politely thank them and say goodbye.

Start speaking immediately after the call is answered - don't wait for the user to speak first.
"""
                        },
                        "post_prompt": {
                            "temperature": 0.5,
                            "text": "Summarize: Did we get IT contact info? If yes, provide name and phone."
                        },
                        "params": {
                            "wait_for_user": False,  # Start speaking immediately
                            "end_of_speech_timeout": 1500,
                            "ai_volume": 8,
                            "local_tz": "America/Phoenix"
                        },
                        "languages": [
                            {
                                "name": "English",
                                "code": "en-US",
                                "voice": "rime.spore"
                            }
                        ],
                        "hints": [
                            "Fortinet",
                            "cybersecurity",
                            "IT department"
                        ]
                    }
                }
            ]
        }
    }
    
    return swml

def make_ai_call(to_number):
    """Make an outbound AI call using SignalWire native REST API"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    
    print(f"📞 Initiating AI call...")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    print(f"   Space: {space_url}")
    
    # Create SWML for AI agent
    swml = create_ai_swml()
    
    print(f"\n🤖 AI Agent Configuration:")
    print(f"   Model: GPT-4 (default)")
    print(f"   Voice: Rime Spore (natural male voice)")
    print(f"   Purpose: IT contact discovery")
    print(f"   Capabilities: Listen, respond, converse naturally")
    
    # Use SignalWire native REST API
    # https://developer.signalwire.com/rest/signalwire-rest/endpoints/calling/call-commands
    url = f"https://{space_url}/api/calling/calls"
    
    # Create Basic Auth header
    auth_string = f"{project_id}:{auth_token}"
    auth_bytes = auth_string.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_string = base64_bytes.decode('ascii')
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {base64_string}"
    }
    
    # Request payload using SignalWire native format
    payload = {
        "command": "dial",
        "params": {
            "from": from_number,
            "to": to_number,
            "caller_id": from_number,
            "swml": swml  # Pass SWML as JSON object
        }
    }
    
    try:
        print(f"\n📡 Making API request to SignalWire...")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # Check response
        if response.status_code in [200, 201]:
            call_data = response.json()
            call_id = call_data.get('call_id', 'unknown')
            
            print(f"\n✅ AI call initiated!")
            print(f"   Call ID: {call_id}")
            print(f"   Response: {response.status_code}")
            print(f"\n🎤 The AI agent will:")
            print(f"   1. Start speaking immediately after answer")
            print(f"   2. Introduce itself as Paul from Fortinet")
            print(f"   3. Ask for IT decision-maker contact info")
            print(f"   4. LISTEN and RESPOND naturally (real AI!)")
            print(f"   5. Confirm information and thank the person")
            
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
        
        # Print SWML for debugging
        print(f"\nSWML sent:")
        print(json.dumps(swml, indent=2))
        
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make-ai-call.py <phone-number>")
        print("Example: python3 make-ai-call.py 6022950104")
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
    print(f"🤖 MAKING AI-POWERED CALL")
    print(f"{'='*70}")
    
    call = make_ai_call(phone)
    
    print(f"\n{'='*70}")
    print(f"✅ AI AGENT IS CALLING")
    print(f"{'='*70}")
    print(f"\nThis is a REAL AI CALL - not pre-recorded!")
    print(f"The agent will listen and respond naturally to whatever is said.")
    print(f"\nCall ID: {call.get('call_id', 'unknown')}")
