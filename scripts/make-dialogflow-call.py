#!/usr/bin/env python3
"""
Make an outbound call that uses the Dialogflow CX webhook

This connects SignalWire → Webhook → Dialogflow CX for natural AI conversations
"""
import os
import sys
import json
from signalwire.rest import Client as SignalWireClient

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    """Load SignalWire configuration"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def make_dialogflow_call(to_number):
    """Make a call using Dialogflow CX webhook"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    from_number = config['phone_number']
    webhook_url = config['webhook_url']
    
    print(f"📞 Making Dialogflow CX call...")
    print(f"   From: {from_number}")
    print(f"   To: {to_number}")
    print(f"   Webhook: {webhook_url}")
    print(f"   Space: {space_url}")
    
    # Initialize SignalWire client
    client = SignalWireClient(
        project_id,
        auth_token,
        signalwire_space_url=space_url
    )
    
    # Create TwiML that forwards to webhook
    # The webhook will handle the Dialogflow integration
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect>{webhook_url}</Redirect>
</Response>"""
    
    try:
        # Make the call
        call = client.calls.create(
            from_=from_number,
            to=to_number,
            twiml=twiml,
            status_callback=webhook_url,
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST'
        )
        
        print(f"\n✅ Call initiated!")
        print(f"   Call SID: {call.sid}")
        print(f"   Status: {call.status}")
        print(f"\n🤖 Dialogflow CX will handle the conversation:")
        print(f"   1. Answer the call")
        print(f"   2. Say 'Hi' or speak naturally")
        print(f"   3. The AI will respond using Discovery Mode flow")
        print(f"   4. It will ask for IT contact information")
        print(f"   5. Answer naturally - it's a real conversation!")
        print(f"\n📊 Monitor the call:")
        print(f"   - Firestore: active_calls/{call.sid}")
        print(f"   - Logs: gcloud functions logs read dialogflowWebhook --region=us-central1")
        
        return call
        
    except Exception as e:
        print(f"\n❌ Call failed: {e}")
        print(f"\nDebug info:")
        print(f"  Project ID: {project_id}")
        print(f"  Space URL: {space_url}")
        print(f"  From: {from_number}")
        print(f"  To: {to_number}")
        print(f"  Webhook: {webhook_url}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make-dialogflow-call.py <phone-number>")
        print("Example: python3 make-dialogflow-call.py 6022950104")
        print("")
        print("This makes a call using the Dialogflow CX webhook.")
        print("Make sure the webhook is deployed first:")
        print("  cd webhook && bash deploy.sh")
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
    print(f"🤖 MAKING DIALOGFLOW CX CALL")
    print(f"{'='*70}")
    print("")
    
    call = make_dialogflow_call(phone)
    
    print(f"\n{'='*70}")
    print(f"✅ CALL IN PROGRESS")
    print(f"{'='*70}")
    print(f"\nThis uses Dialogflow CX for natural conversation.")
    print(f"The AI will guide you through the Discovery Mode flow.")
    print(f"\nCall SID: {call.sid}")
    print(f"\nTo check status:")
    print(f"  python3 scripts/check-call-status.py {call.sid}")
