# Calendar Booking Cloud Function

Books meetings via Google Calendar during AI voice calls.

## Overview

This function enables the AI Voice Caller to:
- Check calendar availability in real-time
- Find open time slots within working hours
- Book meetings with Google Meet links
- Send calendar invitations to attendees

## Features

- **Availability Check**: Returns available slots for next 5 business days
- **Working Hours**: Only books within 8 AM - 5 PM, Mon-Fri
- **Buffer Time**: 15-minute buffer between meetings
- **Google Meet**: Auto-creates Meet link for each booking
- **Email Invites**: Automatically sends calendar invites

## Prerequisites

1. Google Cloud Project with Calendar API enabled
2. Service account with domain-wide delegation
3. Service account JSON key in Secret Manager

## Setup Google Workspace Integration

### 1. Create Service Account
```bash
gcloud iam service-accounts create calendar-booking \
  --display-name="Calendar Booking Service"
```

### 2. Enable Domain-Wide Delegation
1. Go to GCP Console > IAM > Service Accounts
2. Click on the service account
3. Click "Show Advanced Settings"
4. Check "Enable G Suite Domain-wide Delegation"
5. Copy the Client ID

### 3. Configure Workspace Admin
1. Go to admin.google.com > Security > API Controls
2. Click "Manage Domain Wide Delegation"
3. Add new client with:
   - Client ID: (from step 2)
   - Scopes: `https://www.googleapis.com/auth/calendar`

### 4. Store Credentials
```bash
gcloud secrets create calendar-service-account \
  --data-file=path/to/service-account.json
```

## Deployment

```bash
./deploy.sh
```

## API Endpoints

### Check Availability
```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "action": "check_availability",
    "startDate": "2024-02-15T00:00:00Z"
  }'
```

Response:
```json
{
  "available": true,
  "slots": [
    {
      "start": "2024-02-15T09:00:00-07:00",
      "end": "2024-02-15T09:30:00-07:00",
      "displayTime": "Thursday, February 15 at 9:00 AM"
    }
  ],
  "spokenResponse": "I have Thursday, February 15 at 9:00 AM, or Thursday, February 15 at 10:00 AM available.",
  "fulfillmentResponse": {...}
}
```

### Book Meeting
```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "action": "book",
    "startTime": "2024-02-15T09:00:00-07:00",
    "attendeeEmail": "john@cityville.edu",
    "attendeeName": "John Smith",
    "accountName": "Cityville School District",
    "contactPhone": "555-123-4567",
    "notes": "Interested in local survivability"
  }'
```

Response:
```json
{
  "success": true,
  "booking": {
    "eventId": "abc123...",
    "htmlLink": "https://calendar.google.com/event?eid=...",
    "meetLink": "https://meet.google.com/abc-defg-hij",
    "start": "2024-02-15T09:00:00-07:00",
    "end": "2024-02-15T09:30:00-07:00"
  },
  "spokenResponse": "Perfect! I've booked the meeting for Thursday, February 15 at 9:00 AM..."
}
```

## Dialogflow Integration

1. Create webhook pointing to function URL
2. In booking flow, add webhook fulfillment
3. Pass parameters from session:
```json
{
  "action": "$session.params.calendar_action",
  "startTime": "$session.params.selected_time",
  "attendeeEmail": "$session.params.email",
  "attendeeName": "$session.params.contact_name",
  "accountName": "$session.params.account_name"
}
```

## Customization

### Change Working Hours
Edit in `index.js`:
```javascript
const WORK_START_HOUR = 9;  // 9 AM
const WORK_END_HOUR = 18;   // 6 PM
const WORK_DAYS = [1, 2, 3, 4, 5]; // Mon-Fri
```

### Different Meeting Duration
Set environment variable:
```bash
MEETING_DURATION=15  # 15-minute meetings
```

### Multiple Calendars
For team scheduling, create a shared calendar and use its ID:
```bash
CALENDAR_ID=team-demos@your-domain.com
```

## Troubleshooting

### "No available slots"
- Check working hours configuration
- Verify calendar isn't fully booked
- Extend date range in request

### "Calendar API error"
- Verify service account has domain-wide delegation
- Check Workspace admin authorized the client ID
- Ensure Calendar API is enabled in GCP

### "Permission denied"
- Service account needs Secret Manager access
- Check domain-wide delegation scopes

## License

MIT
