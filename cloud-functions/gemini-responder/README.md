# Gemini Responder Cloud Function

Intelligent response generation for the AI Voice Caller using Vertex AI Gemini.

## Overview

This Cloud Function serves as a Dialogflow CX webhook, generating context-aware, conversational responses when the structured dialog flows can't handle a user's input.

## Features

- **Contextual Responses**: Uses conversation history, account data, and pain points to generate relevant responses
- **Rate Limiting**: Protects against abuse with per-session rate limiting
- **Retry Logic**: Automatic retries with exponential backoff for transient failures
- **TTS Optimization**: Cleans responses for natural-sounding text-to-speech
- **Interaction Logging**: Logs all interactions to Firestore for analytics

## Prerequisites

- Google Cloud Project with billing enabled
- Vertex AI API enabled
- Firestore in Native mode
- Cloud Functions API enabled

## Installation

```bash
# Install dependencies
npm install

# Run locally
npm start

# Run tests
npm test
```

## Deployment

```bash
# Deploy to Google Cloud
./deploy.sh

# Dry run (see what would be deployed)
./deploy.sh --dry-run
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_PROJECT` | Google Cloud Project ID | `tatt-pro` |
| `GCP_LOCATION` | Region for Vertex AI | `us-central1` |
| `GEMINI_MODEL` | Gemini model to use | `gemini-1.5-flash` |

## Request Format

The function expects Dialogflow CX webhook format:

```json
{
  "sessionInfo": {
    "session": "projects/xxx/locations/xxx/agents/xxx/sessions/xxx",
    "parameters": {
      "account_name": "Cityville School District",
      "account_type": "K12",
      "current_system": "Cisco",
      "conversation_history": [
        {"role": "bot", "text": "Hi, is this John?"},
        {"role": "user", "text": "Yes, who's calling?"}
      ]
    }
  },
  "text": "I'm not really interested right now",
  "pageInfo": {
    "currentPage": "handle-objection"
  }
}
```

## Response Format

Returns Dialogflow CX fulfillment response:

```json
{
  "fulfillmentResponse": {
    "messages": [{
      "text": {
        "text": ["Totally understand. Can I ask - is it more about timing, or is voice modernization not on your radar at all?"]
      }
    }]
  },
  "sessionInfo": {
    "parameters": {
      "last_gemini_response": "...",
      "conversation_history": [...]
    }
  }
}
```

## Dialogflow CX Integration

1. Deploy the function
2. Copy the function URL
3. In Dialogflow CX Console:
   - Go to **Manage** > **Webhooks**
   - Create new webhook with the function URL
4. In your flow:
   - Add a route with webhook fulfillment
   - Select the Gemini responder webhook

## Monitoring

View logs in Cloud Console:
```bash
gcloud functions logs read gemini-responder --region=us-central1 --limit=50
```

View Firestore interactions:
```bash
# In Cloud Console, navigate to Firestore > gemini_interactions
```

## Costs

- **Gemini 1.5 Flash**: ~$0.002 per 1K tokens
- **Average call**: ~500 tokens = $0.001
- **100 calls/month**: ~$0.10

## Troubleshooting

### "Rate limit exceeded"
- Default: 100 requests/minute per session
- Increase `RATE_LIMIT_MAX_REQUESTS` if needed

### Slow responses (>2s)
- Check Vertex AI quotas
- Consider upgrading to dedicated endpoint
- Monitor cold start frequency

### Response sounds robotic
- The function cleans text for TTS
- If issues persist, check Dialogflow TTS voice settings

## License

MIT
