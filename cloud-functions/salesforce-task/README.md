# Salesforce Task Cloud Function

Creates Salesforce tasks and logs call activities after AI voice calls complete.

## Overview

This function integrates the AI Voice Caller with Salesforce CRM:
- Creates follow-up tasks based on call outcomes
- Logs call activities with transcripts
- Updates lead/account records
- Assigns tasks to account owners

## Features

- **Smart Task Creation**: Different task types based on call outcome
- **Connection Pooling**: Reuses Salesforce connections for performance
- **Secure Credentials**: Uses Google Secret Manager for Salesforce auth
- **Retry Logic**: Automatic retries with exponential backoff
- **Account Matching**: Fuzzy matching for account names

## Prerequisites

- Salesforce org with API access
- Salesforce Connected App or user credentials
- Google Cloud Secret Manager with secrets:
  - `sf-username`
  - `sf-password`
  - `sf-security-token`

## Setup Secrets

```bash
# Create secrets in Secret Manager
echo -n "your-sf-username" | gcloud secrets create sf-username --data-file=-
echo -n "your-sf-password" | gcloud secrets create sf-password --data-file=-
echo -n "your-security-token" | gcloud secrets create sf-security-token --data-file=-
```

## Deployment

```bash
./deploy.sh
```

## Request Format

```json
{
  "accountName": "Cityville School District",
  "outcome": "interested",
  "callSummary": "John expressed interest in FortiVoice. Wants to discuss local survivability.",
  "transcript": "Bot: Hi, is this John?\\nJohn: Yes, who's calling?...",
  "leadScore": 8,
  "contactName": "John Smith",
  "callDuration": 180,
  "sessionId": "call-123456"
}
```

### Valid Outcomes

| Outcome | Task Created | Priority |
|---------|--------------|----------|
| `interested` | Follow-up task | High |
| `send_info` | Send info task | Normal |
| `meeting_booked` | Meeting confirmation | High |
| `not_interested` | No action task | Low |
| `callback_requested` | Callback task | High |
| `voicemail` | Voicemail follow-up | Normal |
| `wrong_number` | Data cleanup | Low |
| `no_answer` | Retry call task | Normal |

## Response Format

```json
{
  "success": true,
  "task": {
    "id": "00T...",
    "subject": "AI Call - Interested, Schedule Follow-up",
    "priority": "High",
    "status": "Not Started"
  },
  "activity": {
    "id": "00U...",
    "type": "Event"
  },
  "account": {
    "id": "001...",
    "name": "Cityville School District"
  }
}
```

## Task Ownership

Tasks are assigned to the Account Owner in Salesforce. If you need different routing:

1. Modify the `createTask` function
2. Add routing logic based on:
   - Territory
   - Round-robin queue
   - Specific user ID

## Salesforce Permissions

Required permissions for the integration user:
- Read/Create on Task
- Read/Create on Event (optional)
- Read on Account
- API Enabled

## Testing

```bash
# Test locally
npm start

# Then call:
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "accountName": "Test Account",
    "outcome": "interested",
    "callSummary": "Test call summary"
  }'
```

## Troubleshooting

### "Account not found"
- Check account name matches Salesforce exactly
- Try with partial name (function does LIKE matching)
- Verify API user has access to the account

### "INVALID_SESSION_ID"
- Session expired, function will auto-reconnect
- Check credentials in Secret Manager

### "Missing required field"
- Ensure `accountName` and `outcome` are provided
- Check outcome is a valid value

## License

MIT
