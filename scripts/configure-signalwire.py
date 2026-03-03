#!/usr/bin/env python3
"""
Configure SignalWire phone number to use Dialogflow webhook

This script automatically configures your SignalWire phone number
to forward calls to the Dialogflow CX webhook.
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

def configure_phone_number():
    """Configure phone number to use webhook"""
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    phone_number = config['phone_number']
    phone_number_id = config['phone_number_id']
    webhook_url = config['webhook_url']
    
    print(f"📞 Configuring SignalWire phone number...")
    print(f"   Phone: {phone_number}")
    print(f"   Webhook: {webhook_url}")
    print(f"   Space: {space_url}")
    
    # Initialize SignalWire client
    client = SignalWireClient(
        project_id,
        auth_token,
        signalwire_space_url=space_url
    )
    
    try:
        # Update phone number configuration
        # SignalWire uses TwiML for call handling
        phone_number_resource = client.incoming_phone_numbers(phone_number_id).update(
            voice_url=webhook_url,
            voice_method='POST'
        )
        
        print(f"\n✅ Phone number configured!")
        print(f"   SID: {phone_number_resource.sid}")
        print(f"   Voice URL: {phone_number_resource.voice_url}")
        print(f"   Voice Method: {phone_number_resource.voice_method}")
        print(f"\n📝 Configuration:")
        print(f"   - Incoming calls will be forwarded to webhook")
        print(f"   - Webhook will connect to Dialogflow CX")
        print(f"   - AI will handle the conversation")
        print(f"\n🧪 Test it:")
        print(f"   python3 scripts/make-dialogflow-call.py 6022950104")
        
        return phone_number_resource
        
    except Exception as e:
        print(f"\n❌ Configuration failed: {e}")
        print(f"\nDebug info:")
        print(f"  Project ID: {project_id}")
        print(f"  Space URL: {space_url}")
        print(f"  Phone Number: {phone_number}")
        print(f"  Phone Number ID: {phone_number_id}")
        print(f"  Webhook URL: {webhook_url}")
        
        print(f"\n💡 Manual configuration:")
        print(f"  1. Go to https://{space_url}/phone_numbers")
        print(f"  2. Click on {phone_number}")
        print(f"  3. Under 'Voice & Fax' → 'A Call Comes In'")
        print(f"  4. Select: Webhook")
        print(f"  5. URL: {webhook_url}")
        print(f"  6. Method: POST")
        print(f"  7. Save")
        
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"🔧 CONFIGURING SIGNALWIRE")
    print(f"{'='*70}")
    print("")
    
    resource = configure_phone_number()
    
    print(f"\n{'='*70}")
    print(f"✅ CONFIGURATION COMPLETE")
    print(f"{'='*70}")
    print(f"\nYour phone number is now connected to Dialogflow CX.")
    print(f"Make a test call to verify everything works!")
