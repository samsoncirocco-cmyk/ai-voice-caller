"""
Cloud Function to serve SWML for SignalWire AI Agent.
Deploy to Firebase/GCP Cloud Functions and use the URL for outbound calls.

Usage:
  POST https://your-function-url/swml_agent
  -> Returns SWML JSON that invokes the AI agent
"""
import json
from flask import jsonify

# AI Agent configuration (from SignalWire Fabric)
AGENT_CONFIG = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {"answer": {}},
            {
                "ai": {
                    "prompt": {
                        "text": """You are Paul, a knowledgeable and professional solutions consultant calling on behalf of Fortinet. You specialize in helping IT leaders in education and local government modernize their voice and security infrastructure.

You are NOT pushy or aggressive. You are genuinely curious about their challenges and focused on finding solutions that fit their needs.

CONVERSATION FLOW:
1. GREETING: Hi, this is Paul from Fortinet. Is this the IT department?
2. CONFIRM TIME: Do you have 2 minutes for a quick question about your voice systems?
3. KILLER QUESTION: Quick question -- what happens to your phones when the internet goes down?
4. QUALIFY INTEREST based on their answer.
5. SCHEDULE OR SEND INFO: Would you be open to a 15-minute call with our partner High Point Networks?

Keep the call under 3 minutes.""",
                        "confidence": 0.6,
                        "temperature": 0.3
                    },
                    "post_prompt": {
                        "text": "Summarize the call outcome. Log the call using log_call."
                    },
                    "params": {
                        "ai_model": "gpt-4.1-nano",
                        "direction": "outbound",
                        "end_of_speech_timeout": 2000,
                        "inactivity_timeout": 30000
                    },
                    "languages": [
                        {
                            "code": "en-US",
                            "provider": "amazon",
                            "voice": "amazon.Matthew:standard:en-US"
                        }
                    ],
                    "SWAIG": {
                        "functions": [
                            {
                                "function": "log_call",
                                "web_hook_url": "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook",
                                "description": "Log call outcome",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "outcome": {"type": "string"},
                                        "summary": {"type": "string"}
                                    }
                                }
                            },
                            {
                                "function": "save_contact",
                                "web_hook_url": "https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook",
                                "description": "Save IT contact information",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "phone": {"type": "string"},
                                        "account": {"type": "string"}
                                    },
                                    "required": ["name"]
                                }
                            }
                        ]
                    }
                }
            }
        ]
    }
}


def swml_agent(request):
    """HTTP Cloud Function to serve SWML for AI agent."""
    # Return SWML JSON with correct content type
    response = jsonify(AGENT_CONFIG)
    response.headers['Content-Type'] = 'application/json'
    return response


# For local testing
if __name__ == "__main__":
    print(json.dumps(AGENT_CONFIG, indent=2))
