#!/usr/bin/env python3
"""
Make an outbound test call using SignalWire AI Agent
"""
import requests
from requests.auth import HTTPBasicAuth
import json

# Configuration
PROJECT_ID = "6b9a5a5f-7d10-436c-abf0-c623208d76cd"
AUTH_TOKEN = "PT4f6bab11e0ba7fcde64b54a8385064e8fae086e359b04be8"
SPACE_URL = "6eyes.signalwire.com"
FROM_NUMBER = "+16028985026"
TO_NUMBER = "+16022950104"
AI_AGENT_ID = "f2c41814-4a36-436b-b723-71d5cdffec60"

# Create SWML script that uses the AI agent
swml_script = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {
                "ai": {
                    "ai_agent_id": AI_AGENT_ID,
                    "params": {
                        "direction": "outbound",
                        "wait_for_user": False
                    }
                }
            }
        ]
    }
}

# Convert SWML to JSON string
swml_json = json.dumps(swml_script)

# Base64 encode the SWML
import base64
swml_base64 = base64.b64encode(swml_json.encode()).decode()
swml_url = f"data:application/json;base64,{swml_base64}"

# Make the call using LaML API
url = f"https://{SPACE_URL}/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls.json"

data = {
    "From": FROM_NUMBER,
    "To": TO_NUMBER,
    "Url": swml_url
}

print(f"Making call from {FROM_NUMBER} to {TO_NUMBER}...")
print(f"Using AI Agent ID: {AI_AGENT_ID}")
print(f"SWML URL: {swml_url[:100]}...")

response = requests.post(
    url,
    auth=HTTPBasicAuth(PROJECT_ID, AUTH_TOKEN),
    data=data
)

print(f"\nResponse Status: {response.status_code}")
print(f"Response Body: {response.text}")

if response.status_code == 201:
    call_data = response.json()
    print(f"\n✅ Call initiated successfully!")
    print(f"Call SID: {call_data.get('sid')}")
    print(f"Status: {call_data.get('status')}")
else:
    print(f"\n❌ Call failed!")
    print(f"Error: {response.text}")
