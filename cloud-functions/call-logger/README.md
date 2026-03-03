# Call Logger Cloud Function

Logs AI voice calls to Firestore and optionally streams to BigQuery for analytics.

## Overview

This function tracks the entire lifecycle of voice calls:
- Call start (captures initial context)
- Mid-call updates (transcript additions)
- Call end (final outcome, metrics)

## Features

- **Lifecycle Tracking**: Start, update, and end events
- **Transcript Storage**: Full conversation history
- **Auto-Metrics**: Calculates turn counts, word averages
- **BigQuery Streaming**: Optional real-time analytics
- **Query API**: Retrieve calls by session ID

## Data Model

### Firestore Document

```javascript
{
  sessionId: "call-abc-123",
  startTime: Timestamp,
  endTime: Timestamp,
  status: "completed", // in_progress, completed, failed
  
  callerPhone: "+15551234567",
  callerName: "John Smith",
  accountName: "Cityville School District",
  accountId: "001xxx",
  
  useCase: "cold_calling",
  campaign: "feb-2024-fortivoice",
  
  transcript: [
    { role: "bot", text: "Hi, is this John?" },
    { role: "user", text: "Yes, who's calling?" }
  ],
  
  outcome: "interested",
  leadScore: 8,
  duration: 180,
  
  metrics: {
    totalTurns: 12,
    userTurns: 5,
    botTurns: 7,
    avgUserWordsPerTurn: 8,
    avgBotWordsPerTurn: 15
  },
  
  meetingBooked: true,
  emailSent: false,
  salesforceTaskId: "00Txxx",
  
  metadata: {
    phoneNumber: "+15559876543",
    dialedNumber: "+15551234567",
    region: "US-AZ",
    timezone: "America/Phoenix"
  }
}
```

## API Endpoints

### Start Call
```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "call-123",
    "action": "start",
    "accountName": "Cityville School District",
    "callerName": "John Smith",
    "callerPhone": "+15551234567",
    "useCase": "cold_calling",
    "campaign": "feb-2024"
  }'
```

### Update Call (add transcript)
```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "call-123",
    "action": "update",
    "transcript": [
      {"role": "bot", "text": "Tell me more about that"},
      {"role": "user", "text": "We use Cisco right now"}
    ],
    "currentPage": "qualification",
    "detectedIntent": "provide_system_info"
  }'
```

### End Call
```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "call-123",
    "action": "end",
    "outcome": "interested",
    "leadScore": 8,
    "meetingBooked": true,
    "transcript": [
      {"role": "bot", "text": "Thanks for your time!"}
    ]
  }'
```

### Get Call
```bash
curl "https://FUNCTION_URL?sessionId=call-123"
```

## BigQuery Integration

Enable streaming to BigQuery for analytics:

```bash
ENABLE_BIGQUERY=true ./deploy.sh
```

### Sample Queries

```sql
-- Call volume by day
SELECT 
  DATE(start_time) as call_date,
  COUNT(*) as calls,
  AVG(duration_seconds) as avg_duration
FROM `tatt-pro.voice_caller.call_logs`
GROUP BY call_date
ORDER BY call_date DESC;

-- Outcome breakdown
SELECT 
  outcome,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM `tatt-pro.voice_caller.call_logs`
GROUP BY outcome;

-- Conversion funnel
SELECT 
  use_case,
  COUNT(*) as total_calls,
  COUNTIF(outcome = 'interested') as interested,
  COUNTIF(meeting_booked = true) as meetings_booked
FROM `tatt-pro.voice_caller.call_logs`
GROUP BY use_case;
```

## Deployment

```bash
# Basic deployment (Firestore only)
./deploy.sh

# With BigQuery streaming
ENABLE_BIGQUERY=true ./deploy.sh
```

## Dialogflow Integration

Call this function at key points in your flows:

1. **Start flow**: Webhook with `action: start`
2. **After each turn**: Webhook with `action: update`
3. **End flow**: Webhook with `action: end`

Example webhook payload:
```json
{
  "sessionId": "$session.params.session_id",
  "action": "end",
  "outcome": "$session.params.call_outcome",
  "transcript": "$session.params.conversation_history"
}
```

## Troubleshooting

### "Call not found"
- Ensure `start` was called before `update` or `end`
- Check sessionId matches exactly

### BigQuery errors
- Verify dataset exists
- Check table schema matches
- Ensure Cloud Function has BigQuery permissions

### Missing transcripts
- Transcript is appended, not replaced
- Use array format: `[{role, text}]`

## License

MIT
