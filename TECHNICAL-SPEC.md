# AI Voice Caller - Technical Specification
**Version:** 1.0  
**Last Updated:** 2026-02-10  
**Status:** Design Phase  
**Google Cloud Project:** tatt-pro  

---

## 1. Executive Summary

This document provides the complete technical specification for the AI Voice Caller system designed for SLED (State, Local, Education, District) prospecting. The system uses Google Cloud's Dialogflow CX as the conversation engine, integrated with Vertex AI Gemini for intelligent response generation, SignalWire for telephony, and backend services for CRM integration and data persistence.

---

## 2. System Requirements

### 2.1 Google Cloud Services

| Service | Purpose | API to Enable |
|---------|---------|---------------|
| Dialogflow CX | Conversation engine, intent recognition | `dialogflow.googleapis.com` |
| Speech-to-Text | Real-time voice transcription | `speech.googleapis.com` |
| Text-to-Speech | Natural voice synthesis | `texttospeech.googleapis.com` |
| Vertex AI | Gemini LLM integration | `aiplatform.googleapis.com` |
| Cloud Functions (2nd gen) | Webhook handlers | `cloudfunctions.googleapis.com` |
| Cloud Run | Container hosting (optional) | `run.googleapis.com` |
| Firestore | Call logs, lead database | `firestore.googleapis.com` |
| BigQuery | Analytics warehouse | `bigquery.googleapis.com` |
| Cloud Scheduler | Batch call scheduling | `cloudscheduler.googleapis.com` |
| Secret Manager | API keys, credentials | `secretmanager.googleapis.com` |

### 2.2 External Services

| Service | Purpose | Account Required |
|---------|---------|------------------|
| SignalWire | Telephony (SIP trunking, phone numbers) | SignalWire account |
| Salesforce | CRM integration | Salesforce org (fortinet.my.salesforce.com) |
| Google Calendar | Appointment scheduling | Google Workspace account |
| SendGrid/Gmail | Email delivery (confirmations) | Email provider account |

### 2.3 Infrastructure Requirements

```yaml
Compute:
  Cloud Functions:
    Runtime: Node.js 20 or Python 3.12
    Memory: 512MB minimum, 1GB recommended
    Timeout: 60 seconds (webhook), 540 seconds (batch processing)
    Region: us-central1 (same as Dialogflow)
    
  Cloud Run (optional, for long-running jobs):
    CPU: 1 vCPU
    Memory: 1GB
    Min instances: 0
    Max instances: 10

Storage:
  Firestore:
    Mode: Native (not Datastore mode)
    Location: nam5 (United States multi-region)
    
  BigQuery:
    Dataset location: US multi-region
    Table partitioning: By call_timestamp (daily)
    
Networking:
  VPC: Default VPC sufficient
  Egress: Required for SignalWire, Salesforce APIs
  Ingress: Cloud Functions allow unauthenticated (webhook endpoints)
```

### 2.4 Service Account Permissions

Create a service account `voice-caller-sa@tatt-pro.iam.gserviceaccount.com` with:

```
roles/dialogflow.client
roles/aiplatform.user
roles/cloudfunctions.invoker
roles/datastore.user
roles/bigquery.dataEditor
roles/secretmanager.secretAccessor
roles/logging.logWriter
```

---

## 3. API Endpoints and Data Flows

### 3.1 Inbound Webhooks (Dialogflow → Cloud Functions)

#### 3.1.1 Gemini Responder Webhook

**Endpoint:** `https://us-central1-tatt-pro.cloudfunctions.net/gemini-responder`

**Purpose:** Handle complex/unstructured responses using Gemini LLM

**Request (from Dialogflow):**
```json
{
  "detectIntentResponseId": "abc123",
  "intentInfo": {
    "lastMatchedIntent": "projects/tatt-pro/locations/us-central1/agents/xxx/intents/yyy",
    "displayName": "fallback.unknown",
    "confidence": 0.3
  },
  "pageInfo": {
    "currentPage": "projects/tatt-pro/locations/us-central1/agents/xxx/flows/zzz/pages/aaa",
    "displayName": "Cold Calling - Killer Question"
  },
  "sessionInfo": {
    "session": "projects/tatt-pro/locations/us-central1/agents/xxx/sessions/session-123",
    "parameters": {
      "account_name": "Phoenix Union High School District",
      "contact_name": "John Smith",
      "contact_title": "IT Director",
      "current_system": "Cisco UCM",
      "pain_points": ["aging infrastructure", "no remote support"],
      "conversation_goal": "qualify_interest",
      "lead_score": 3
    }
  },
  "text": "We're actually looking at Teams right now",
  "languageCode": "en"
}
```

**Response (to Dialogflow):**
```json
{
  "fulfillmentResponse": {
    "messages": [
      {
        "text": {
          "text": [
            "I hear that a lot. Teams is great for chat and video, but a lot of districts find the voice piece needs work. Are you planning to use Teams Phone System, or would you keep voice separate?"
          ]
        }
      }
    ],
    "mergeBehavior": "REPLACE"
  },
  "sessionInfo": {
    "parameters": {
      "competitor_mentioned": "Microsoft Teams",
      "buying_stage": "evaluating",
      "lead_score": 4
    }
  }
}
```

#### 3.1.2 Calendar Availability Webhook

**Endpoint:** `https://us-central1-tatt-pro.cloudfunctions.net/calendar-availability`

**Purpose:** Check calendar availability and book meetings

**Request:**
```json
{
  "action": "check_availability",
  "sessionInfo": {
    "parameters": {
      "preferred_time": "morning",
      "preferred_date": "next_week",
      "duration_minutes": 30,
      "attendee_email": "jsmith@phoenix.k12.az.us"
    }
  }
}
```

**Response:**
```json
{
  "fulfillmentResponse": {
    "messages": [
      {
        "text": {
          "text": [
            "I have Tuesday at 9:30 AM or Wednesday at 10:00 AM available. Which works better?"
          ]
        }
      }
    ]
  },
  "sessionInfo": {
    "parameters": {
      "available_slots": [
        {"date": "2026-02-17", "time": "09:30", "display": "Tuesday at 9:30 AM"},
        {"date": "2026-02-18", "time": "10:00", "display": "Wednesday at 10:00 AM"}
      ]
    }
  }
}
```

#### 3.1.3 Salesforce Integration Webhook

**Endpoint:** `https://us-central1-tatt-pro.cloudfunctions.net/salesforce-integration`

**Purpose:** Create tasks, update leads, log call activities

**Request:**
```json
{
  "action": "create_task",
  "sessionInfo": {
    "parameters": {
      "account_id": "001XXXXXXXXXXXXXXX",
      "contact_id": "003XXXXXXXXXXXXXXX",
      "call_outcome": "interested_meeting_booked",
      "meeting_date": "2026-02-17T09:30:00-07:00",
      "notes": "Interested in FortiVoice. Currently using Cisco UCM. Budget approved for this year. Meeting with High Point Networks.",
      "lead_score": 7
    }
  }
}
```

**Response:**
```json
{
  "fulfillmentResponse": {
    "messages": []
  },
  "sessionInfo": {
    "parameters": {
      "task_id": "00TXXXXXXXXXXXXXXX",
      "salesforce_updated": true
    }
  }
}
```

#### 3.1.4 Call Logger Webhook

**Endpoint:** `https://us-central1-tatt-pro.cloudfunctions.net/call-logger`

**Purpose:** Log call details to Firestore at call end

**Request:**
```json
{
  "action": "log_call",
  "sessionInfo": {
    "session": "projects/tatt-pro/locations/us-central1/agents/xxx/sessions/session-123",
    "parameters": {
      "account_name": "Phoenix Union High School District",
      "contact_name": "John Smith",
      "phone_number": "+16025551234",
      "use_case": "cold_calling",
      "call_outcome": "interested_meeting_booked",
      "lead_score": 7,
      "call_duration_seconds": 187,
      "transcript": [
        {"role": "bot", "text": "Hi, is this John?", "timestamp": 0},
        {"role": "human", "text": "Yes, who's this?", "timestamp": 2.3},
        ...
      ]
    }
  }
}
```

### 3.2 Outbound API Calls (Cloud Functions → External Services)

#### 3.2.1 SignalWire Call Initiation

**Endpoint:** `https://{space_name}.signalwire.com/api/laml/2010-04-01/Accounts/{project_id}/Calls`

**Method:** POST

**Headers:**
```
Authorization: Basic base64({project_id}:{api_token})
Content-Type: application/x-www-form-urlencoded
```

**Body:**
```
From=+18001234567
To=+16025551234
Url=https://{dialogflow-gateway}/telephony/cx/projects/tatt-pro/locations/us-central1/agents/{agent_id}
StatusCallback=https://us-central1-tatt-pro.cloudfunctions.net/call-status-handler
StatusCallbackEvent=initiated ringing answered completed
```

#### 3.2.2 Salesforce REST API

**Authentication:** OAuth 2.0 JWT Bearer Flow

**Base URL:** `https://fortinet.my.salesforce.com/services/data/v59.0`

**Endpoints Used:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sobjects/Task` | POST | Create follow-up task |
| `/sobjects/Lead/{id}` | PATCH | Update lead status |
| `/sobjects/Account/{id}` | PATCH | Update account fields |
| `/sobjects/Event` | POST | Create activity record |
| `/query?q={SOQL}` | GET | Query records |

**Example - Create Task:**
```json
POST /sobjects/Task
{
  "Subject": "Follow-up call - Voice system discussion",
  "WhoId": "003XXXXXXXXXXXXXXX",
  "WhatId": "001XXXXXXXXXXXXXXX",
  "OwnerId": "005XXXXXXXXXXXXXXX",
  "Priority": "High",
  "Status": "Not Started",
  "ActivityDate": "2026-02-17",
  "Description": "AI voice caller identified interest in FortiVoice. Lead score: 7. Current system: Cisco UCM. Pain points: aging infrastructure, no remote support."
}
```

#### 3.2.3 Google Calendar API

**Scopes Required:**
```
https://www.googleapis.com/auth/calendar
https://www.googleapis.com/auth/calendar.events
```

**Endpoints Used:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/calendars/{calendarId}/freeBusy` | POST | Check availability |
| `/calendars/{calendarId}/events` | POST | Create meeting |
| `/calendars/{calendarId}/events/{eventId}` | DELETE | Cancel meeting |

**Example - Check Free/Busy:**
```json
POST /calendars/primary/freeBusy
{
  "timeMin": "2026-02-17T08:00:00-07:00",
  "timeMax": "2026-02-21T18:00:00-07:00",
  "timeZone": "America/Phoenix",
  "items": [
    {"id": "paul@fortinet.com"}
  ]
}
```

**Example - Create Event:**
```json
POST /calendars/primary/events
{
  "summary": "FortiVoice Discovery Call - Phoenix Union HSD",
  "description": "Call with John Smith (IT Director)\nTopics: Voice modernization, local survivability\nPrepared by: AI Voice Caller",
  "start": {
    "dateTime": "2026-02-17T09:30:00-07:00",
    "timeZone": "America/Phoenix"
  },
  "end": {
    "dateTime": "2026-02-17T10:00:00-07:00",
    "timeZone": "America/Phoenix"
  },
  "attendees": [
    {"email": "jsmith@phoenix.k12.az.us"},
    {"email": "partner@highpointnetworks.com"},
    {"email": "paul@fortinet.com"}
  ],
  "conferenceData": {
    "createRequest": {
      "requestId": "meeting-123",
      "conferenceSolutionKey": {"type": "hangoutsMeet"}
    }
  }
}
```

---

## 4. Database Schemas (Firestore Collections)

### 4.1 Collection: `calls`

**Purpose:** Record of every call made by the system

```javascript
{
  // Document ID: auto-generated
  "call_id": "call_20260210_173245_abc123",
  "session_id": "projects/tatt-pro/locations/us-central1/agents/xxx/sessions/session-123",
  
  // Call metadata
  "initiated_at": Timestamp,
  "answered_at": Timestamp | null,
  "ended_at": Timestamp,
  "duration_seconds": 187,
  "call_status": "completed", // initiated, ringing, answered, completed, failed, no_answer, busy
  
  // Telephony
  "phone_number": "+16025551234",
  "caller_id": "+18001234567",
  "signalwire_call_sid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  
  // Account/Contact info
  "account": {
    "id": "001XXXXXXXXXXXXXXX",
    "name": "Phoenix Union High School District",
    "type": "K12",
    "state": "AZ"
  },
  "contact": {
    "id": "003XXXXXXXXXXXXXXX",
    "name": "John Smith",
    "title": "IT Director",
    "email": "jsmith@phoenix.k12.az.us"
  },
  
  // Conversation
  "use_case": "cold_calling", // cold_calling, follow_up, appointment_setting, lead_qualification, info_delivery
  "flow_completed": true,
  "pages_visited": ["Start", "Greeting", "Killer Question", "Interest Check", "Book Meeting"],
  "intents_matched": [
    {"intent": "confirm_identity", "confidence": 0.95},
    {"intent": "express_interest", "confidence": 0.87},
    {"intent": "confirm_time", "confidence": 0.92}
  ],
  
  // Outcomes
  "call_outcome": "interested_meeting_booked",
  /*
    Possible outcomes:
    - interested_meeting_booked
    - interested_send_info
    - callback_scheduled
    - not_interested_timing
    - not_interested_permanent
    - wrong_person
    - voicemail
    - no_answer
    - call_failed
    - opted_out
  */
  
  // Lead scoring
  "lead_score": 7,
  "lead_score_factors": {
    "current_system_age": 2,
    "user_count": 2,
    "buying_timeframe": 3,
    "expressed_pain": 2,
    "engaged_conversation": 1
  },
  
  // Discovery data collected
  "discovery_data": {
    "current_system": "Cisco UCM",
    "system_age_years": 8,
    "user_count": "250-500",
    "locations": 12,
    "contract_renewal": "2026-07",
    "pain_points": ["aging infrastructure", "no remote support", "expensive maintenance"],
    "competitors_mentioned": ["Microsoft Teams"],
    "buying_timeframe": "within_6_months",
    "budget_status": "approved"
  },
  
  // Meeting details (if booked)
  "meeting": {
    "scheduled": true,
    "datetime": Timestamp,
    "duration_minutes": 30,
    "attendees": ["jsmith@phoenix.k12.az.us", "partner@highpointnetworks.com"],
    "calendar_event_id": "xxx123",
    "meeting_link": "https://meet.google.com/xxx-yyy-zzz"
  },
  
  // Salesforce sync
  "salesforce": {
    "synced": true,
    "task_id": "00TXXXXXXXXXXXXXXX",
    "sync_timestamp": Timestamp
  },
  
  // Full transcript
  "transcript": [
    {
      "role": "bot",
      "text": "Hi, is this John?",
      "timestamp_seconds": 0,
      "ssml": "<speak>Hi, is this <break time='200ms'/> John?</speak>"
    },
    {
      "role": "human",
      "text": "Yes, who's this?",
      "timestamp_seconds": 2.3,
      "confidence": 0.94
    },
    // ... more turns
  ],
  
  // Analytics
  "gemini_calls": 2,
  "avg_response_latency_ms": 1450,
  "speech_recognition_errors": 0,
  
  // Metadata
  "created_at": Timestamp,
  "updated_at": Timestamp,
  "version": 1
}
```

**Indexes:**
```
- call_outcome ASC, initiated_at DESC
- account.id ASC, initiated_at DESC
- use_case ASC, initiated_at DESC
- lead_score DESC, initiated_at DESC
- initiated_at DESC
```

### 4.2 Collection: `accounts`

**Purpose:** Cache of account data for quick lookup during calls

```javascript
{
  // Document ID: Salesforce Account ID
  "salesforce_id": "001XXXXXXXXXXXXXXX",
  
  "name": "Phoenix Union High School District",
  "type": "K12", // K12, Higher_Ed, State, County, City, Special_District
  "industry": "Education",
  
  "address": {
    "street": "4502 N Central Ave",
    "city": "Phoenix",
    "state": "AZ",
    "zip": "85012"
  },
  
  // Size metrics
  "employee_count": 3500,
  "student_count": 27000,
  "location_count": 22,
  "estimated_phone_users": 800,
  
  // Current technology
  "current_voice_system": {
    "vendor": "Cisco",
    "product": "UCM",
    "version": "12.5",
    "install_date": "2018-03",
    "contract_expires": "2026-07-31"
  },
  "current_network_vendor": "Cisco",
  "current_security_vendor": "Fortinet",
  
  // Relationship
  "account_owner": "Paul Scirocco",
  "partner": "High Point Networks",
  "last_contact_date": Timestamp,
  "last_call_outcome": "interested_send_info",
  
  // Calling preferences
  "do_not_call": false,
  "opted_out_at": null,
  "preferred_call_time": "morning", // morning, afternoon, anytime
  "timezone": "America/Phoenix",
  
  // Lead scoring
  "lead_score": 5,
  "lead_status": "warm", // cold, warm, hot, customer
  
  // Call history summary
  "total_calls": 3,
  "successful_calls": 2,
  "last_successful_call": Timestamp,
  
  // Metadata
  "synced_from_salesforce_at": Timestamp,
  "created_at": Timestamp,
  "updated_at": Timestamp
}
```

### 4.3 Collection: `contacts`

**Purpose:** Contact information for call targeting

```javascript
{
  // Document ID: Salesforce Contact ID
  "salesforce_id": "003XXXXXXXXXXXXXXX",
  "account_id": "001XXXXXXXXXXXXXXX",
  
  "name": {
    "first": "John",
    "last": "Smith",
    "full": "John Smith"
  },
  "title": "IT Director",
  "department": "Information Technology",
  
  "phone": {
    "direct": "+16025551234",
    "mobile": "+16025559876",
    "preferred": "direct"
  },
  "email": "jsmith@phoenix.k12.az.us",
  
  // Calling
  "do_not_call": false,
  "opted_out_at": null,
  "best_time_to_call": "9am-11am",
  
  // History
  "total_calls": 2,
  "last_call_date": Timestamp,
  "last_call_outcome": "callback_scheduled",
  
  // Notes
  "notes": "Prefers morning calls. Asked about local survivability.",
  
  // Metadata
  "synced_from_salesforce_at": Timestamp,
  "created_at": Timestamp,
  "updated_at": Timestamp
}
```

### 4.4 Collection: `call_batches`

**Purpose:** Track batch calling jobs

```javascript
{
  // Document ID: auto-generated
  "batch_id": "batch_20260210_173000",
  
  "name": "Phoenix K12 Cold Calling - Wave 1",
  "use_case": "cold_calling",
  
  "status": "in_progress", // pending, in_progress, completed, paused, cancelled
  
  "schedule": {
    "start_time": Timestamp,
    "end_time": Timestamp,
    "timezone": "America/Phoenix",
    "days_of_week": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "call_window_start": "09:00",
    "call_window_end": "11:30"
  },
  
  "targets": {
    "total_contacts": 50,
    "calls_completed": 23,
    "calls_remaining": 27,
    "calls_in_progress": 2
  },
  
  "results": {
    "answered": 18,
    "no_answer": 3,
    "voicemail": 2,
    "failed": 0,
    "outcomes": {
      "interested_meeting_booked": 4,
      "interested_send_info": 6,
      "callback_scheduled": 3,
      "not_interested": 5
    }
  },
  
  "settings": {
    "max_concurrent_calls": 3,
    "retry_no_answer": true,
    "max_retries": 2,
    "retry_delay_hours": 24,
    "leave_voicemail": false
  },
  
  "contact_list": [
    {
      "contact_id": "003XXXXXXXXXXXXXXX",
      "phone": "+16025551234",
      "status": "completed",
      "call_id": "call_20260210_093045_xyz789",
      "outcome": "interested_meeting_booked"
    },
    {
      "contact_id": "003YYYYYYYYYYYYYYY",
      "phone": "+16025552345",
      "status": "pending",
      "call_id": null,
      "outcome": null
    }
    // ... more contacts
  ],
  
  "created_by": "paul@fortinet.com",
  "created_at": Timestamp,
  "updated_at": Timestamp
}
```

### 4.5 Collection: `do_not_call`

**Purpose:** TCPA compliance - track opt-outs

```javascript
{
  // Document ID: phone number (normalized)
  "phone_number": "+16025551234",
  
  "opted_out_at": Timestamp,
  "opt_out_source": "voice_call", // voice_call, email, manual, salesforce
  "opt_out_call_id": "call_20260210_173245_abc123",
  
  "account_id": "001XXXXXXXXXXXXXXX",
  "contact_id": "003XXXXXXXXXXXXXXX",
  
  // For auditing
  "transcript_snippet": "Please don't call me again.",
  
  "created_at": Timestamp
}
```

### 4.6 Collection: `system_config`

**Purpose:** Runtime configuration

```javascript
{
  // Document ID: "main"
  
  "calling_enabled": true,
  
  "signalwire": {
    "space_name": "fortinet-voice",
    "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "caller_ids": ["+18001234567", "+18001234568"],
    "default_caller_id": "+18001234567"
  },
  
  "dialogflow": {
    "agent_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "location": "us-central1"
  },
  
  "calendar": {
    "calendar_id": "paul@fortinet.com",
    "meeting_duration_minutes": 30,
    "buffer_minutes": 15,
    "available_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "available_hours": {"start": "08:00", "end": "17:00"},
    "timezone": "America/Phoenix"
  },
  
  "limits": {
    "max_daily_calls": 100,
    "max_concurrent_calls": 5,
    "max_call_duration_seconds": 600
  },
  
  "voices": {
    "default": "en-US-Neural2-D",
    "fallback": "en-US-Standard-D"
  },
  
  "lead_scoring": {
    "system_age_threshold_years": 5,
    "user_count_threshold": 25,
    "hot_lead_threshold": 5,
    "warm_lead_threshold": 3
  },
  
  "updated_at": Timestamp,
  "updated_by": "paul@fortinet.com"
}
```

---

## 5. Error Handling and Retry Logic

### 5.1 Telephony Errors

| Error | Detection | Action | Retry |
|-------|-----------|--------|-------|
| No Answer | SignalWire callback: `no-answer` | Log outcome, schedule retry | Yes, after 24h, max 2 |
| Busy | SignalWire callback: `busy` | Log outcome, schedule retry | Yes, after 1h, max 3 |
| Invalid Number | SignalWire callback: `failed` | Mark contact invalid, skip | No |
| Network Error | SignalWire 5xx response | Retry immediately | Yes, 3x with backoff |
| Call Timeout | Duration > 600s | Force disconnect, log | No |

### 5.2 Dialogflow Errors

| Error | Detection | Action |
|-------|-----------|--------|
| No Match (low confidence) | Intent confidence < 0.3 | Route to Gemini fallback |
| Session Timeout | Session > 5 min idle | Prompt user, end if no response |
| Webhook Timeout | Webhook > 5s | Use cached response, log error |
| Speech Recognition Error | Empty or garbage text | Ask user to repeat |

### 5.3 Backend Errors

| Service | Error | Retry Strategy |
|---------|-------|----------------|
| Gemini API | 429 (Rate Limit) | Exponential backoff: 1s, 2s, 4s, 8s |
| Gemini API | 500/503 | Retry 3x, then use template response |
| Salesforce API | 401 (Auth) | Refresh token, retry once |
| Salesforce API | 429 (Rate Limit) | Queue for async processing |
| Google Calendar | 403 (Quota) | Queue for later, warn admin |
| Firestore | Timeout | Retry 3x, continue call without logging |

### 5.4 Circuit Breaker Pattern

Implement circuit breaker for external services:

```javascript
const circuitBreaker = {
  gemini: {
    failures: 0,
    lastFailure: null,
    state: 'closed', // closed, open, half-open
    threshold: 5, // failures before opening
    resetTimeout: 60000 // 1 minute
  }
};

// If circuit open, skip Gemini and use template response
// After resetTimeout, try one request (half-open)
// If success, close circuit; if fail, re-open
```

### 5.5 Graceful Degradation

| Component Failure | Degraded Behavior |
|-------------------|-------------------|
| Gemini unavailable | Use scripted responses from Dialogflow |
| Calendar unavailable | "Let me have someone email you available times" |
| Salesforce unavailable | Queue to Firestore, sync later |
| Firestore unavailable | Log to Cloud Logging, reconstruct later |

---

## 6. Security Considerations

### 6.1 TCPA Compliance

**Requirements:**
1. **B2B Exemption:** System calls business contacts only, not consumers
2. **Opt-Out Mechanism:** Every call includes "Say 'stop calling' at any time to be removed"
3. **Do Not Call List:** Check `do_not_call` collection before every call
4. **Call Time Restrictions:** 8:00 AM - 9:00 PM recipient's local time
5. **Caller ID:** Always display valid, callable phone number
6. **Record Keeping:** Store call records for 5 years

**Implementation:**
```javascript
// Before initiating call
async function preCallChecks(phoneNumber, timezone) {
  // Check DNC list
  const dncDoc = await firestore.collection('do_not_call').doc(normalizePhone(phoneNumber)).get();
  if (dncDoc.exists) {
    throw new Error('BLOCKED_DNC');
  }
  
  // Check calling hours
  const recipientTime = moment().tz(timezone);
  const hour = recipientTime.hour();
  if (hour < 8 || hour >= 21) {
    throw new Error('BLOCKED_HOURS');
  }
  
  // Check daily limit
  const todayCalls = await getTodayCallCount();
  if (todayCalls >= config.limits.max_daily_calls) {
    throw new Error('BLOCKED_LIMIT');
  }
  
  return true;
}
```

### 6.2 Data Privacy

**PII Handling:**
| Data Type | Storage | Encryption | Retention |
|-----------|---------|------------|-----------|
| Phone Numbers | Firestore | At-rest (Google-managed) | 5 years |
| Call Transcripts | Firestore | At-rest | 1 year, then delete |
| Audio Recordings | Cloud Storage (optional) | At-rest | 90 days |
| Email Addresses | Firestore | At-rest | Until opt-out |

**Access Control:**
- All Cloud Functions use service account authentication
- Firestore security rules restrict access by service account
- API keys stored in Secret Manager, never in code
- All external API calls use TLS 1.3

### 6.3 API Security

**Webhook Authentication:**
```javascript
// Dialogflow webhook verification
function verifyDialogflowRequest(req) {
  const signature = req.headers['x-goog-signature'];
  const body = JSON.stringify(req.body);
  const expectedSignature = crypto
    .createHmac('sha256', process.env.WEBHOOK_SECRET)
    .update(body)
    .digest('hex');
  return signature === expectedSignature;
}
```

**Secret Management:**
```bash
# Store secrets in Secret Manager
gcloud secrets create signalwire-api-token --data-file=token.txt
gcloud secrets create salesforce-client-secret --data-file=secret.txt
gcloud secrets create calendar-service-account --data-file=sa-key.json

# Access in Cloud Functions
const {SecretManagerServiceClient} = require('@google-cloud/secret-manager');
const client = new SecretManagerServiceClient();
const [version] = await client.accessSecretVersion({
  name: 'projects/tatt-pro/secrets/signalwire-api-token/versions/latest'
});
const apiToken = version.payload.data.toString();
```

### 6.4 Audit Logging

All significant events logged to Cloud Logging:

```javascript
const {Logging} = require('@google-cloud/logging');
const logging = new Logging();
const log = logging.log('voice-caller-audit');

async function auditLog(event, data) {
  const entry = log.entry({
    resource: {type: 'cloud_function'},
    severity: 'INFO',
    labels: {
      event_type: event,
      call_id: data.callId
    }
  }, {
    timestamp: new Date().toISOString(),
    event: event,
    actor: 'voice-caller-system',
    ...data
  });
  await log.write(entry);
}

// Usage
await auditLog('CALL_INITIATED', {callId, phoneNumber: masked, accountId});
await auditLog('DNC_CHECK_PASSED', {callId, phoneNumber: masked});
await auditLog('MEETING_BOOKED', {callId, meetingTime, attendees});
await auditLog('OPT_OUT_RECORDED', {callId, phoneNumber: masked});
```

---

## 7. Testing Strategy

### 7.1 Unit Testing

**Coverage Requirements:** 80% minimum

**Test Cases:**
```javascript
// Gemini responder tests
describe('GeminiResponder', () => {
  it('generates appropriate response for objection', async () => {
    const context = {utterance: "We're not interested", goal: 'qualify'};
    const response = await generateResponse(context);
    expect(response).toContain('understand');
    expect(response.length).toBeLessThan(200);
  });
  
  it('handles empty utterance gracefully', async () => {
    const context = {utterance: '', goal: 'qualify'};
    const response = await generateResponse(context);
    expect(response).toContain('repeat');
  });
  
  it('respects token limits', async () => {
    const context = {utterance: 'Tell me everything about your product', goal: 'qualify'};
    const response = await generateResponse(context);
    expect(tokenCount(response)).toBeLessThan(100);
  });
});

// DNC compliance tests
describe('DNCCompliance', () => {
  it('blocks calls to DNC numbers', async () => {
    await firestore.collection('do_not_call').doc('+16025551234').set({opted_out_at: new Date()});
    await expect(preCallChecks('+16025551234', 'America/Phoenix')).rejects.toThrow('BLOCKED_DNC');
  });
  
  it('blocks calls outside business hours', async () => {
    jest.spyOn(Date, 'now').mockReturnValue(new Date('2026-02-10T06:00:00-07:00'));
    await expect(preCallChecks('+16025551234', 'America/Phoenix')).rejects.toThrow('BLOCKED_HOURS');
  });
});
```

### 7.2 Integration Testing

**Test Scenarios:**

| Scenario | Components | Expected Outcome |
|----------|------------|------------------|
| Complete cold call flow | SignalWire → Dialogflow → Gemini → Calendar → Salesforce | Meeting booked, task created |
| DNC opt-out | Dialogflow → Firestore | Number added to DNC, call ended |
| Calendar booking | Dialogflow → Calendar API | Event created, invite sent |
| Salesforce task creation | Cloud Function → Salesforce API | Task visible in Salesforce |
| Error recovery | Gemini timeout | Fallback response used, call continues |

**Integration Test Environment:**
- Use Dialogflow test agent (separate from production)
- Use SignalWire test phone numbers
- Use Salesforce sandbox org
- Use separate Firestore database (test project)

### 7.3 End-to-End Testing

**Test Script:**
```bash
#!/bin/bash
# e2e-test.sh

echo "=== E2E Test: Cold Calling Flow ==="

# 1. Create test contact in Firestore
gcloud firestore documents create \
  --collection=contacts \
  --document-id=test-contact-001 \
  --data='{"name": "Test User", "phone": "+1TESTPHONE"}'

# 2. Initiate test call via SignalWire
CALL_SID=$(curl -X POST "https://fortinet-voice.signalwire.com/api/laml/2010-04-01/Accounts/$PROJECT_ID/Calls" \
  -u "$PROJECT_ID:$API_TOKEN" \
  -d "From=+18001234567" \
  -d "To=+1TESTPHONE" \
  -d "Url=$DIALOGFLOW_GATEWAY" \
  | jq -r '.sid')

echo "Call initiated: $CALL_SID"

# 3. Wait for call to complete (max 5 min)
for i in {1..30}; do
  STATUS=$(curl -s "https://fortinet-voice.signalwire.com/api/laml/2010-04-01/Accounts/$PROJECT_ID/Calls/$CALL_SID" \
    -u "$PROJECT_ID:$API_TOKEN" | jq -r '.status')
  if [ "$STATUS" = "completed" ]; then
    echo "Call completed"
    break
  fi
  sleep 10
done

# 4. Verify Firestore call log
CALL_DOC=$(gcloud firestore documents query calls --filter="signalwire_call_sid=$CALL_SID" --limit=1)
if [ -n "$CALL_DOC" ]; then
  echo "✅ Call logged to Firestore"
else
  echo "❌ Call not found in Firestore"
  exit 1
fi

# 5. Verify Salesforce task (if meeting booked)
# ... check Salesforce API

echo "=== E2E Test Complete ==="
```

### 7.4 Load Testing

**Tool:** Artillery or k6

**Scenarios:**
```yaml
# artillery-config.yml
config:
  target: "https://us-central1-tatt-pro.cloudfunctions.net"
  phases:
    - duration: 60
      arrivalRate: 1  # 1 request per second
    - duration: 120
      arrivalRate: 5  # 5 requests per second
    - duration: 60
      arrivalRate: 10 # 10 requests per second (stress test)

scenarios:
  - name: "Gemini Responder"
    flow:
      - post:
          url: "/gemini-responder"
          json:
            text: "We're looking at Teams right now"
            sessionInfo:
              parameters:
                conversation_goal: "qualify_interest"
```

**Performance Targets:**
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Webhook Latency (p50) | < 1 second | > 2 seconds |
| Webhook Latency (p99) | < 3 seconds | > 5 seconds |
| Error Rate | < 1% | > 5% |
| Gemini Fallback Rate | < 20% | > 30% |

### 7.5 User Acceptance Testing (UAT)

**Phase 1: Internal Testing (Week 1)**
- Call yourself from test number
- Test all 5 use cases
- Verify calendar integration
- Verify Salesforce tasks

**Phase 2: Pilot (Week 2)**
- 10 low-risk accounts
- Monitor all calls in real-time
- Review 100% of transcripts
- Collect feedback

**Phase 3: Soft Launch (Week 3-4)**
- 50 accounts
- Sample 20% of transcripts
- Track success metrics
- Iterate on scripts

---

## 8. Deployment Architecture

### 8.1 Environment Strategy

| Environment | Purpose | Project |
|-------------|---------|---------|
| Development | Local testing, feature dev | tatt-pro-dev |
| Staging | Integration testing, UAT | tatt-pro-staging |
| Production | Live calls | tatt-pro |

### 8.2 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy Voice Caller

on:
  push:
    branches: [main]
    paths:
      - 'cloud-functions/**'
      - 'dialogflow-agent/**'

jobs:
  deploy-functions:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      
      - name: Deploy Cloud Functions
        run: |
          cd cloud-functions/gemini-responder
          gcloud functions deploy gemini-responder \
            --gen2 \
            --runtime=nodejs20 \
            --region=us-central1 \
            --trigger-http \
            --allow-unauthenticated \
            --memory=512MB \
            --timeout=60s
            
      - name: Deploy Dialogflow Agent
        run: |
          cd dialogflow-agent
          gcloud dialogflow cx agents restore \
            --source=agent-export.blob \
            --location=us-central1
```

### 8.3 Monitoring & Alerting

**Cloud Monitoring Dashboards:**
- Call Volume (calls/hour)
- Success Rate (%)
- Average Call Duration
- Gemini Latency (p50, p99)
- Error Rate by Type

**Alerts:**
```yaml
# Alert: High Error Rate
condition:
  filter: 'resource.type="cloud_function" AND metric.type="cloudfunctions.googleapis.com/function/execution_count"'
  comparison: COMPARISON_GT
  threshold_value: 0.1
  duration: 300s
notification_channels:
  - email:paul@fortinet.com
  - sms:+16025551234

# Alert: Gemini Timeout
condition:
  filter: 'jsonPayload.error_type="GEMINI_TIMEOUT"'
  comparison: COMPARISON_GT
  threshold_value: 5
  duration: 600s
```

---

## 9. Appendices

### 9.1 SSML Reference

```xml
<!-- Natural pacing -->
<speak>
  Hi, is this <break time="200ms"/> John?
  <break time="500ms"/>
  This is Paul from Fortinet.
  <break time="300ms"/>
  <emphasis level="moderate">Quick question</emphasis> for you...
</speak>

<!-- Spelling out acronyms -->
<speak>
  We work with <say-as interpret-as="characters">IT</say-as> leaders on voice solutions.
</speak>

<!-- Phone numbers -->
<speak>
  You can reach me at <say-as interpret-as="telephone">+1-800-123-4567</say-as>
</speak>

<!-- Slower for important info -->
<speak>
  Your meeting is scheduled for
  <prosody rate="slow">Tuesday at 9:30 AM</prosody>.
</speak>
```

### 9.2 Lead Scoring Matrix

| Factor | Question/Signal | Points |
|--------|-----------------|--------|
| System Age | Current system > 5 years old | +2 |
| User Count | 25+ phone users | +2 |
| Buying Timeline | Planning changes within 12 months | +3 |
| Pain Points | Mentioned 2+ pain points | +2 |
| Engaged | Asked questions, stayed on call 3+ min | +1 |
| Budget | Budget approved/allocated | +2 |
| Decision Maker | Title: Director, VP, CIO, CTO | +1 |
| Competitor Mention | Actively evaluating alternatives | +2 |

**Score Interpretation:**
- 0-2: Cold — Add to nurture campaign
- 3-4: Warm — Send info, follow up in 2 weeks
- 5-6: Hot — Book meeting this week
- 7+: Very Hot — Immediate action, escalate to partner

### 9.3 Glossary

| Term | Definition |
|------|------------|
| SLED | State, Local, Education, District (government sector) |
| TCPA | Telephone Consumer Protection Act |
| DNC | Do Not Call |
| SIP | Session Initiation Protocol |
| PSTN | Public Switched Telephone Network |
| SSML | Speech Synthesis Markup Language |
| CX | Customer Experience (Dialogflow CX) |
| TTS | Text-to-Speech |
| STT | Speech-to-Text |

---

**Document Control:**
- Author: AI Voice Caller Subagent
- Reviewed by: —
- Approved by: —
- Next Review: After Phase 1 Implementation
