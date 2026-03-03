#!/usr/bin/env python3
"""
Test SignalWire Native AI Agent (Option A)
Uses the agent created via SignalWire's AI Agent API
"""
import os
import sys
import json
import requests

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def make_ai_agent_call(to_number):
    """Make a call using the native SignalWire AI agent"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    agent_id = config['ai_agent']['agent_id']
    
    print(f"📞 Testing SignalWire Native AI Agent...")
    print(f"   Agent ID: {agent_id}")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    
    # SignalWire Compatibility API (Twilio-compatible)
    base_url = f"https://{space_url}"
    api_url = f"{base_url}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json"
    
    # Create call using AI agent
    # Reference: https://developer.signalwire.com/compatibility-api/rest/create-a-call
    
    payload = {
        "From": from_number,
        "To": to_number,
        "Url": f"{base_url}/api/ai/agent/{agent_id}",  # AI agent webhook URL
        "Method": "POST"
    }
    
    try:
        response = requests.post(
            api_url,
            auth=(project_id, auth_token),
            json=payload
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            call_id = data.get('id') or data.get('sid') or data.get('call_id')
            
            print(f"\n✅ Call initiated via AI Agent!")
            print(f"   Call ID: {call_id}")
            print(f"   Agent: {config['ai_agent']['name']}")
            print(f"   Voice: {config['ai_agent']['voice']}")
            print(f"   Model: {config['ai_agent']['model']}")
            print(f"\n🤖 AI will:")
            print(f"   - Introduce as Paul from Fortinet")
            print(f"   - Ask for IT contact name")
            print(f"   - Ask for direct phone number")
            print(f"   - Confirm and save to Firestore")
            
            return data
        else:
            print(f"\n❌ Call failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test-native-ai-agent.py <phone-number>")
        sys.exit(1)
    
    phone = sys.argv[1]
    phone = phone.replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
    
    if not phone.startswith('+'):
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif phone.startswith('1') and len(phone) == 11:
            phone = f"+{phone}"
    
    print(f"\n{'='*70}")
    print(f"🧪 TESTING OPTION A: SIGNALWIRE NATIVE AI AGENT")
    print(f"{'='*70}\n")
    
    result = make_ai_agent_call(phone)
    
    if result:
        print(f"\n{'='*70}")
        print(f"✅ TEST CALL PLACED - ANSWER YOUR PHONE!")
        print(f"{'='*70}")
    else:
        print(f"\n{'='*70}")
        print(f"❌ TEST FAILED - SEE ERRORS ABOVE")
        print(f"{'='*70}")
