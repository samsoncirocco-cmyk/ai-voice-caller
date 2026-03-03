# Dialogflow CX Webhook for SignalWire

This Cloud Function bridges SignalWire phone calls to Dialogflow CX, enabling natural AI-powered voice conversations.

## Architecture

```
SignalWire Phone Call
  ↓ (call connected)
Webhook (this function)
  ↓ (call detectIntent API)
Dialogflow CX Agent
  ↓ (returns response)
Webhook
  ↓ (returns TwiML)
SignalWire
  ↓ (plays audio, listens)
User speaks
  ↓ (transcribes speech)
Webhook (repeat)
```

## Features

- ✅ Multi-turn conversations
- ✅ Session management (Firestore)
- ✅ Conversation logging
- ✅ Error handling with graceful fallbacks
- ✅ Automatic call cleanup
- ✅ Natural speech recognition (enhanced model)

## Deployment

### Prerequisites

1. **Google Cloud Project** with APIs enabled:
   - Cloud Functions
   - Dialogflow CX
   - Firestore
   
2. **Dialogflow CX Agent** already created:
   - Agent ID: `35ba664e-b443-4b8e-bf60-b9c445b31273`
   - Location: `us-central1`
   - Flow: Discovery Mode

3. **SignalWire Account** with:
   - Phone number purchased
   - API credentials configured

### Deploy

```bash
cd webhook
bash deploy.sh
```

This will:
1. Deploy the Cloud Function to `us-central1`
2. Make it publicly accessible (required for SignalWire webhooks)
3. Return the webhook URL

### Configure SignalWire

After deployment, configure your SignalWire phone number:

1. Go to https://6eyes.signalwire.com/phone_numbers
2. Click on your phone number: **+1 (602) 898-5026**
3. Under **"Voice & Fax"** → **"A Call Comes In"**:
   - Select: **Webhook**
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/dialogflowWebhook`
   - Method: **POST**
4. Click **Save**

## Testing

### Make a Test Call

```bash
python3 ../scripts/make-dialogflow-call.py 6022950104
```

### Monitor the Call

**Check Firestore:**
```bash
# View active calls
gcloud firestore collections describe active_calls

# View conversation logs
gcloud firestore collections describe conversation_logs
```

**View Cloud Function logs:**
```bash
gcloud functions logs read dialogflowWebhook --region=us-central1 --limit=50
```

### Expected Flow

1. **Call connects** → Webhook creates Dialogflow session
2. **AI greets** → "Hi, this is Paul from Fortinet..."
3. **User responds** → Speech transcribed by SignalWire
4. **Webhook forwards** → Calls Dialogflow detectIntent API
5. **AI responds** → Returns natural response
6. **Repeat** → Multi-turn conversation continues
7. **Call ends** → Session cleaned up, logged to Firestore

## Local Development

### Run Locally

```bash
# Install dependencies
npm install

# Start local server
npm start
```

The function will run on http://localhost:8080

### Test Locally with curl

```bash
# Simulate call start
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=test-123" \
  -d "From=+16025551234" \
  -d "To=+16028985026"

# Simulate speech input
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=test-123" \
  -d "SpeechResult=Hello, this is John from IT"
```

## Configuration

Environment variables (set during deployment):

| Variable | Value | Description |
|----------|-------|-------------|
| `GCP_PROJECT` | `tatt-pro` | Google Cloud project ID |
| `FUNCTION_URL` | Auto-detected | Webhook URL (for self-referencing) |

Hardcoded (in `index.js`):

```javascript
const LOCATION = 'us-central1';
const AGENT_ID = '35ba664e-b443-4b8e-bf60-b9c445b31273';
const LANGUAGE_CODE = 'en-US';
```

## Firestore Collections

### `active_calls`

Tracks ongoing conversations:

```json
{
  "call_sid": "CA1234...",
  "session_id": "projects/.../sessions/CA1234",
  "session_params": {
    "phone_number": "+16025551234",
    "caller_id": "+16028985026",
    "call_start_time": "2026-02-11T14:30:00Z"
  },
  "started_at": Timestamp,
  "turn_count": 5,
  "last_user_input": "Yes, that's correct",
  "last_bot_response": "Great! Let me confirm..."
}
```

### `completed_calls`

Archive of finished calls:

```json
{
  // ... all fields from active_calls, plus:
  "ended_at": Timestamp,
  "duration_seconds": 187,
  "call_status": "completed"
}
```

### `conversation_logs`

Turn-by-turn transcript:

```json
{
  "call_sid": "CA1234...",
  "timestamp": Timestamp,
  "user_input": "Hello",
  "bot_response": "Hi! This is Paul from Fortinet..."
}
```

## Troubleshooting

### Call connects but no speech

**Symptom:** Call connects, but AI doesn't speak.

**Fix:** Check Dialogflow agent has a proper greeting in the Start page.

```bash
# Test Dialogflow directly
gcloud dialogflow cx agents test \
  --agent=35ba664e-b443-4b8e-bf60-b9c445b31273 \
  --location=us-central1 \
  --query="start"
```

### Speech not recognized

**Symptom:** AI says "I didn't catch that" repeatedly.

**Fix:** Check SignalWire speech settings. The webhook uses:
- `speechModel="phone_call"` (optimized for phone audio)
- `enhanced="true"` (best quality)

### Webhook timeout

**Symptom:** Call drops after 30-60 seconds.

**Fix:** Increase Cloud Function timeout:

```bash
gcloud functions deploy dialogflowWebhook \
  --timeout=60s \
  --region=us-central1
```

### Session not persisting

**Symptom:** AI forgets previous turns.

**Fix:** Check Firestore rules allow webhook to write:

```javascript
// Firestore rules
match /active_calls/{callSid} {
  allow read, write: if request.auth != null || true;  // Allow unauthenticated for webhook
}
```

## Cost Estimation

Per call (avg 3 minutes, 10 turns):

- **Cloud Function:** ~$0.0001 (negligible)
- **Dialogflow CX:** ~$0.02 (10 requests × $0.002)
- **SignalWire:** ~$0.01/min = $0.03
- **Firestore:** ~$0.0001 (negligible)

**Total:** ~$0.05 per call

For 1,000 calls/month: **~$50/month**

## Next Steps

1. ✅ Deploy webhook
2. ✅ Configure SignalWire
3. ✅ Test with Discovery Mode flow
4. 🔲 Build more complex flows (cold calling, appointment setting)
5. 🔲 Add webhook for Salesforce integration
6. 🔲 Add webhook for calendar booking
7. 🔲 Implement lead scoring

## References

- [Dialogflow CX Sessions API](https://cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.sessions/detectIntent)
- [SignalWire TwiML](https://developer.signalwire.com/compatibility-api/reference/twiml)
- [Cloud Functions Node.js](https://cloud.google.com/functions/docs/writing)
