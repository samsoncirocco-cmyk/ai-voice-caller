#!/usr/bin/env python3
"""
Test Call Script - Trigger AI Voice Call via SignalWire
Takes phone number as argument and initiates a test call
Logs results to Firestore
"""

import os
import sys
import json
import argparse
from datetime import datetime
from google.cloud import firestore

# Configuration
PROJECT_ID = "tatt-pro"
FIRESTORE_COLLECTION = "voice-calls"
AGENT_NAME_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/agent-name.txt"
SIGNALWIRE_CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"


def load_agent_name():
    """Load Dialogflow CX agent resource name"""
    if not os.path.exists(AGENT_NAME_FILE):
        print(f"✗ Agent name file not found: {AGENT_NAME_FILE}")
        print("  Run create-agent.py first!")
        sys.exit(1)
    
    with open(AGENT_NAME_FILE, 'r') as f:
        return f.read().strip()


def load_signalwire_config():
    """Load SignalWire configuration"""
    if not os.path.exists(SIGNALWIRE_CONFIG_FILE):
        print(f"✗ SignalWire config not found: {SIGNALWIRE_CONFIG_FILE}")
        print("  SignalWire integration not configured yet!")
        print("  See config/signalwire-needed.md for setup instructions")
        return None
    
    with open(SIGNALWIRE_CONFIG_FILE, 'r') as f:
        return json.load(f)


def validate_phone_number(phone):
    """Basic phone number validation (E.164 format preferred)"""
    # Remove common formatting
    cleaned = phone.replace('-', '').replace('(', '').replace(')', '').replace(' ', '').replace('+', '')
    
    # Check if it's all digits and reasonable length (10-15 digits)
    if not cleaned.isdigit():
        return False, "Phone number must contain only digits"
    
    if len(cleaned) < 10 or len(cleaned) > 15:
        return False, "Phone number must be 10-15 digits"
    
    # Convert to E.164 format (add +1 for US numbers if not present)
    if len(cleaned) == 10:
        e164 = f"+1{cleaned}"
    elif cleaned.startswith('1') and len(cleaned) == 11:
        e164 = f"+{cleaned}"
    else:
        e164 = f"+{cleaned}"
    
    return True, e164


def log_call_to_firestore(call_data):
    """Log call attempt to Firestore"""
    try:
        db = firestore.Client(project=PROJECT_ID)
        collection = db.collection(FIRESTORE_COLLECTION)
        
        # Add timestamp
        call_data['timestamp'] = firestore.SERVER_TIMESTAMP
        call_data['created_at'] = datetime.utcnow().isoformat()
        
        # Add document
        doc_ref = collection.add(call_data)
        
        print(f"✓ Call logged to Firestore: {doc_ref[1].id}")
        return doc_ref[1].id
        
    except Exception as e:
        print(f"⚠ Warning: Could not log to Firestore: {e}")
        return None


def trigger_call(phone_number, agent_name, signalwire_config=None):
    """
    Trigger a test call via SignalWire
    
    NOTE: This is a placeholder implementation.
    Once SignalWire is configured, this will use their API to initiate calls.
    """
    
    print(f"\n📞 Initiating test call to {phone_number}...")
    
    if not signalwire_config:
        print("\n⚠ SignalWire not configured - SIMULATION MODE")
        print("  This is what would happen when SignalWire is connected:")
        print(f"  1. POST to SignalWire API: /api/calls")
        print(f"  2. Payload: {{")
        print(f"       'to': '{phone_number}',")
        print(f"       'from': '<SignalWire-Phone-Number>',")
        print(f"       'dialogflow_cx_agent': '{agent_name}',")
        print(f"       'flow': 'test-call'")
        print(f"     }}")
        print(f"  3. SignalWire initiates call")
        print(f"  4. Call connects to Dialogflow CX")
        print(f"  5. Conversation flow executes")
        print(f"  6. Result logged to Firestore")
        
        # Log simulated call
        call_data = {
            'to': phone_number,
            'agent': agent_name,
            'flow': 'test-call',
            'status': 'simulated',
            'mode': 'test',
            'note': 'SignalWire not configured - simulation only'
        }
        
        log_call_to_firestore(call_data)
        
        return {
            'success': False,
            'simulated': True,
            'message': 'SignalWire not configured'
        }
    
    # REAL IMPLEMENTATION (when SignalWire is configured)
    try:
        import requests
        
        # SignalWire API endpoint
        space_url = signalwire_config.get('space_url')
        project_id = signalwire_config.get('project_id')
        api_token = signalwire_config.get('api_token')
        from_number = signalwire_config.get('from_number')
        
        # Construct API endpoint
        api_url = f"https://{space_url}/api/relay/rest/calls"
        
        # Request payload
        payload = {
            'to': phone_number,
            'from': from_number,
            'url': signalwire_config.get('webhook_url'),  # Dialogflow CX webhook
            'method': 'POST'
        }
        
        # Make API call
        response = requests.post(
            api_url,
            auth=(project_id, api_token),
            json=payload,
            timeout=30
        )
        
        response.raise_for_status()
        
        result = response.json()
        call_sid = result.get('sid')
        
        print(f"✓ Call initiated successfully!")
        print(f"  Call SID: {call_sid}")
        print(f"  Status: {result.get('status')}")
        
        # Log successful call
        call_data = {
            'to': phone_number,
            'from': from_number,
            'agent': agent_name,
            'flow': 'test-call',
            'call_sid': call_sid,
            'status': result.get('status'),
            'mode': 'production'
        }
        
        log_call_to_firestore(call_data)
        
        return {
            'success': True,
            'call_sid': call_sid,
            'status': result.get('status')
        }
        
    except Exception as e:
        print(f"\n✗ Error initiating call: {e}")
        
        # Log failed call
        call_data = {
            'to': phone_number,
            'agent': agent_name,
            'flow': 'test-call',
            'status': 'failed',
            'error': str(e),
            'mode': 'production'
        }
        
        log_call_to_firestore(call_data)
        
        return {
            'success': False,
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Trigger AI voice test call')
    parser.add_argument('phone', help='Phone number to call (e.g., 602-295-0104)')
    parser.add_argument('--simulate', action='store_true', 
                       help='Simulate call without SignalWire (default if not configured)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("AI Voice Caller - Test Call Script")
    print("=" * 60)
    
    # Validate phone number
    valid, result = validate_phone_number(args.phone)
    if not valid:
        print(f"✗ Invalid phone number: {result}")
        sys.exit(1)
    
    phone_e164 = result
    print(f"📱 Target phone: {args.phone} ({phone_e164})")
    
    # Load agent
    agent_name = load_agent_name()
    print(f"🤖 Agent: {agent_name}")
    
    # Load SignalWire config (if exists)
    signalwire_config = load_signalwire_config()
    
    # Trigger call
    result = trigger_call(phone_e164, agent_name, signalwire_config)
    
    print("\n" + "=" * 60)
    if result.get('success'):
        print("✓ SUCCESS: Call initiated")
        print(f"  Call SID: {result.get('call_sid')}")
    elif result.get('simulated'):
        print("⚠ SIMULATED: Call not actually placed (SignalWire needed)")
    else:
        print("✗ FAILED: Could not initiate call")
        if result.get('error'):
            print(f"  Error: {result.get('error')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
