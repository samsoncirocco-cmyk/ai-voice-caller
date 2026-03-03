# SignalWire Integration - Required Credentials

## Overview
SignalWire provides the phone gateway that connects Dialogflow CX to the PSTN (Public Switched Telephone Network), enabling the AI agent to make and receive phone calls.

## Required Credentials

### 1. SignalWire Account
Create an account at: https://signalwire.com/signup

### 2. Credentials Needed

Create a `signalwire.json` file in this directory with the following structure:

```json
{
  "project_id": "YOUR_PROJECT_ID",
  "auth_token": "YOUR_AUTH_TOKEN",
  "space_url": "YOUR_SPACE.signalwire.com",
  "phone_number": "+1XXXXXXXXXX",
  "webhook_url": "YOUR_DIALOGFLOW_WEBHOOK_URL"
}
```

### 3. Where to Find Each Value

#### Project ID & Auth Token
1. Log in to SignalWire Dashboard
2. Go to **API** → **Credentials**
3. Copy **Project ID** and **API Token**

#### Space URL
- Your SignalWire Space URL (e.g., `yourcompany.signalwire.com`)
- Found in the dashboard URL when logged in

#### Phone Number
1. Go to **Phone Numbers** in the SignalWire dashboard
2. Purchase a phone number (or use existing)
3. Copy the number in E.164 format (+1XXXXXXXXXX)

#### Webhook URL
This is the Dialogflow CX webhook that SignalWire will call:

**Format:**
```
https://LOCATION-dialogflow.googleapis.com/v3/projects/PROJECT_ID/locations/LOCATION/agents/AGENT_ID/sessions/SESSION_ID:detectIntent
```

**For this project:**
- Location: `us-central1`
- Project ID: `tatt-pro`
- Agent ID: (found in `dialogflow-agent.json` after running `create-agent.py`)

**Alternative:** Use Google Cloud Function as webhook proxy
- Create Cloud Function that receives SignalWire webhook
- Function calls Dialogflow CX detectIntent API
- See `cloud-functions/` directory for examples

## Setup Steps

### Step 1: Create SignalWire Account
```bash
# 1. Sign up at https://signalwire.com/signup
# 2. Verify email
# 3. Complete account setup
```

### Step 2: Purchase Phone Number
```bash
# In SignalWire Dashboard:
# 1. Navigate to Phone Numbers
# 2. Click "Buy a Number"
# 3. Search for available numbers (recommend local AZ number)
# 4. Purchase number
```

### Step 3: Configure Webhook
```bash
# In SignalWire Dashboard:
# 1. Go to Phone Numbers → [Your Number]
# 2. Under "Voice & Fax Settings":
#    - When a call comes in: Webhook
#    - URL: [Your Dialogflow webhook URL]
#    - HTTP Method: POST
# 3. Save
```

### Step 4: Create Config File
```bash
# Copy the example and fill in your values:
cp config/signalwire.json.example config/signalwire.json
# Edit signalwire.json with your credentials
```

### Step 5: Test Connection
```bash
# Run test call script in test mode:
python scripts/test-call.py +16022950104 --test

# If successful, try live mode:
python scripts/test-call.py +16022950104
```

## Python Library Installation

Install the SignalWire Python SDK:

```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
source venv/bin/activate
pip install signalwire
```

## Integration Notes

### Dialogflow CX → SignalWire Flow
1. SignalWire receives incoming/outgoing call
2. SignalWire webhook calls Dialogflow CX API
3. Dialogflow CX processes speech and returns response
4. SignalWire converts text response to speech (TTS)
5. SignalWire plays audio to caller
6. Loop continues until call ends

### Required Dialogflow CX Configuration
- Agent must have Speech-to-Text enabled ✓ (done)
- Agent must have Text-to-Speech voice configured ✓ (done)
- Webhook fulfillment must be set up in flows

### SignalWire → Dialogflow Webhook Format

SignalWire will POST to your webhook with:
```json
{
  "CallSid": "unique-call-id",
  "From": "+16022950104",
  "To": "+1YOURNUMBER",
  "CallStatus": "ringing",
  "SpeechResult": "transcribed speech from caller"
}
```

Your webhook should respond with:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">Response text from Dialogflow</Say>
    <Gather input="speech" action="/next-webhook-url" />
</Response>
```

## Cost Estimates

### SignalWire Pricing (as of 2024)
- Phone number: ~$1/month
- Outbound calls: ~$0.01/minute
- Inbound calls: ~$0.0085/minute
- TTS (text-to-speech): Included

### Test Budget
- 100 test calls × 2 minutes each = 200 minutes
- Estimated cost: ~$2-3 for testing phase

## Security Notes

### Protect Credentials
- Never commit `signalwire.json` to git
- Add to `.gitignore` (already done)
- Use environment variables in production

### Webhook Security
- Use HTTPS only
- Validate SignalWire signature on incoming requests
- Implement rate limiting

## Troubleshooting

### "Webhook not responding"
- Check webhook URL is correct
- Verify Dialogflow agent is active
- Check Cloud Function logs (if using proxy)

### "TTS voice not working"
- Verify voice name in `test-flow.json`
- Check agent language matches voice language
- Try alternative voice (see Google Cloud TTS docs)

### "Call connects but no audio"
- Check SignalWire phone number configuration
- Verify webhook URL returns proper XML/JSON
- Check Dialogflow CX logs for errors

## Next Steps

Once SignalWire is configured:
1. Update `test-call.py` with SignalWire API implementation
2. Create Cloud Function webhook (see `cloud-functions/`)
3. Test end-to-end call flow
4. Monitor Firestore for call logs
5. Iterate on conversation flow based on test results

## Support Resources

- SignalWire Documentation: https://developer.signalwire.com/
- Dialogflow CX Phone Gateway: https://cloud.google.com/dialogflow/cx/docs/concept/integration/phone-gateway
- Cloud Functions: https://cloud.google.com/functions/docs
