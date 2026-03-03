#!/usr/bin/env python3
"""
Make an outbound test call using SignalWire Calling API (not LaML)
"""
import requests
import json
import base64

# Configuration
PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"
SPACE_URL = "6eyes.signalwire.com"
FROM_NUMBER = "+16028985026"
TO_NUMBER = "+16022950104"
AI_AGENT_ID = "f2c41814-4a36-436b-b723-71d5cdffec60"

# Create auth header
auth_string = f"{PROJECT_ID}:{AUTH_TOKEN}"
auth_b64 = base64.b64encode(auth_string.encode()).decode()

# Create SWML script that uses the AI agent
swml_script = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {
                "ai": {
                    "ai_agent_id": AI_AGENT_ID
                }
            }
        ]
    }
}

# Make the call using new Calling API
url = f"https://{SPACE_URL}/api/calling/calls"

payload = {
    "command": "dial",
    "params": {
        "from": FROM_NUMBER,
        "to": TO_NUMBER,
        "swml": swml_script
    }
}

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Basic {auth_b64}"
}

print(f"Making call from {FROM_NUMBER} to {TO_NUMBER}...")
print(f"Using AI Agent ID: {AI_AGENT_ID}")
print(f"\nPayload:")
print(json.dumps(payload, indent=2))

response = requests.post(url, json=payload, headers=headers)

print(f"\nResponse Status: {response.status_code}")
print(f"Response Body: {response.text}")

if response.status_code in [200, 201]:
    try:
        call_data = response.json()
        print(f"\n✅ Call initiated successfully!")
        print(f"Call ID: {call_data.get('id')}")
        print(json.dumps(call_data, indent=2))
    except:
        print("\n✅ Call initiated (no JSON response)")
else:
    print(f"\n❌ Call failed!")
    print(f"Error: {response.text}")
