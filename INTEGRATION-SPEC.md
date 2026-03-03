# AI Voice Caller - Integration Specification
**Version:** 1.0  
**Last Updated:** 2026-02-10  
**Status:** Design Phase  
**Google Cloud Project:** tatt-pro  

---

## Table of Contents
1. [SignalWire Setup](#1-signalwire-setup)
2. [Dialogflow CX Agent Structure](#2-dialogflow-cx-agent-structure)
3. [Cloud Functions Specifications](#3-cloud-functions-specifications)
4. [Salesforce Integration](#4-salesforce-integration)
5. [Google Calendar Integration](#5-google-calendar-integration)
6. [Email Integration](#6-email-integration)
7. [Deployment Scripts](#7-deployment-scripts)

---

## 1. SignalWire Setup

### 1.1 Account Configuration

**SignalWire Space:**
```yaml
Space Name: fortinet-voice
Region: US-West (for Arizona proximity)
```

**Account Creation Steps:**
1. Sign up at https://signalwire.com
2. Create a new Space: `fortinet-voice`
3. Navigate to API → API Credentials
4. Copy `Project ID` and `API Token`
5. Store in Google Secret Manager

### 1.2 Phone Number Provisioning

**Purchase Number:**
```bash
# Via SignalWire Dashboard
# Phone Numbers → Buy a Phone Number
# Select:
#   - Country: United States
#   - Type: Local
#   - Area Code: 480 or 602 (Arizona local presence)
#   - Capabilities: Voice (required), SMS (optional)

# Cost: ~$1/month
```

**Recommended Numbers:**
| Purpose | Area Code | Format | Cost |
|---------|-----------|--------|------|
| Primary Outbound | 602 | (602) 555-XXXX | $1/mo |
| Backup Outbound | 480 | (480) 555-XXXX | $1/mo |

### 1.3 SIP Configuration

**Dialogflow CX Phone Gateway:**
```yaml
# In Google Cloud Console → Dialogflow CX → Agent → Integrations → Phone Gateway

Phone Gateway Settings:
  Country: United States
  Phone Number Type: Bring your own number (BYOC)
  SIP Trunk Provider: SignalWire
```

**SignalWire SIP Domain:**
```yaml
# SignalWire Dashboard → SIP → Domains → Create Domain

Domain Settings:
  Name: fortinet-voice-dfcx
  Region: us-west
  
Outbound Settings:
  Caller ID: +16025551234  # Your SignalWire number
  
Authentication:
  Username: dfcx-user
  Password: <generate-secure-password>
  
Routing:
  # Point to Dialogflow CX SIP endpoint
  Target: sip:+{E.164}@{region}-dialogflow.sip.goog
  # Example: sip:+16025559876@us-central1-dialogflow.sip.goog
```

**SignalWire → Dialogflow Connection:**
```yaml
# SignalWire Dashboard → Phone Numbers → Select Number → Settings

Voice Settings:
  Accept Incoming Calls: Yes
  Handle Calls Using: LaML Webhooks
  
  When a call comes in:
    URL: https://{region}-dialogflow.googleapis.com/v3/projects/{project}/locations/{location}/agents/{agent}/sessions/-:detectIntent
    Method: POST
  
  # For outbound, use LaML to connect to Dialogflow
```

### 1.4 LaML Application for Outbound Calls

**LaML Bin (Outbound Call Handler):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://us-central1-dialogflow.googleapis.com/v3/projects/tatt-pro/locations/us-central1/agents/{AGENT_ID}/environments/draft/sessions/{CALL_SID}:streamingDetectIntent">
      <Parameter name="first_message" value="greeting" />
      <Parameter name="account_name" value="{{AccountName}}" />
      <Parameter name="contact_name" value="{{ContactName}}" />
      <Parameter name="use_case" value="{{UseCase}}" />
    </Stream>
  </Connect>
</Response>
```

### 1.5 Outbound Calling API

**Initiate Outbound Call:**
```bash
curl -X POST \
  "https://fortinet-voice.signalwire.com/api/laml/2010-04-01/Accounts/{PROJECT_ID}/Calls" \
  -u "{PROJECT_ID}:{API_TOKEN}" \
  -d "From=+16025551234" \
  -d "To=+16025559876" \
  -d "Url=https://fortinet-voice.signalwire.com/laml-bins/{BIN_ID}" \
  -d "StatusCallback=https://us-central1-tatt-pro.cloudfunctions.net/call-status-handler" \
  -d "StatusCallbackEvent=initiated ringing answered completed"
```

**Node.js SDK:**
```javascript
const { RestClient } = require('@signalwire/compatibility-api');

const client = new RestClient(
  process.env.SIGNALWIRE_PROJECT_ID,
  process.env.SIGNALWIRE_API_TOKEN,
  { signalwireSpaceUrl: 'fortinet-voice.signalwire.com' }
);

async function initiateCall(to, params) {
  const call = await client.calls.create({
    from: process.env.CALLER_ID,
    to: to,
    url: `https://fortinet-voice.signalwire.com/laml-bins/${process.env.LAML_BIN_ID}`,
    statusCallback: process.env.STATUS_CALLBACK_URL,
    statusCallbackEvent: ['initiated', 'ringing', 'answered', 'completed'],
    // Pass session parameters
    method: 'POST',
    // Custom parameters passed to LaML bin
    statusCallbackMethod: 'POST'
  });
  
  return call.sid;
}
```

### 1.6 Call Status Webhook

**Endpoint:** `POST /call-status-handler`

**SignalWire Callback Payload:**
```json
{
  "CallSid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "AccountSid": "{PROJECT_ID}",
  "From": "+16025551234",
  "To": "+16025559876",
  "CallStatus": "completed",
  "Direction": "outbound-api",
  "Duration": "187",
  "RecordingUrl": null,
  "RecordingSid": null,
  "Timestamp": "2026-02-10T17:45:00Z"
}
```

**Status Values:**
| Status | Description | Action |
|--------|-------------|--------|
| `initiated` | Call started | Log call start |
| `ringing` | Phone ringing | - |
| `answered` | Call connected | Start timer |
| `completed` | Call ended normally | Log duration, outcome |
| `busy` | Line busy | Schedule retry |
| `no-answer` | No answer after timeout | Schedule retry |
| `failed` | Call failed | Log error, alert |
| `canceled` | Call canceled | - |

---

## 2. Dialogflow CX Agent Structure

### 2.1 Agent Configuration

**Agent Settings:**
```yaml
Agent Name: fortinet-sled-voice-caller
Display Name: Fortinet SLED Voice Caller
Default Language: en-US
Time Zone: America/Phoenix
Location: us-central1

Speech Settings:
  Speech Model: phone_call
  Speech-to-Text Model: enhanced
  Enable Speech Adaptation: true
  
Advanced Speech Settings:
  Phrase Hints:
    - Fortinet
    - FortiVoice
    - FortiGate
    - High Point Networks
    - E-Rate
    - SLED
  
Text-to-Speech Settings:
  Voice: en-US-Neural2-D (male) or en-US-Neural2-F (female)
  Speaking Rate: 1.0
  Pitch: 0
  
Logging Settings:
  Enable Stackdriver Logging: true
  Enable Interaction Logging: true
```

### 2.2 Flow Structure

```
Agent: fortinet-sled-voice-caller
│
├── Default Start Flow
│   ├── Start Page
│   └── Route to appropriate flow based on session.params.use_case
│
├── Flow: cold-calling
│   ├── Page: Greeting
│   ├── Page: Introduction
│   ├── Page: Killer Question
│   ├── Page: Interest Check
│   ├── Page: Offer Meeting
│   ├── Page: Handle Objection
│   ├── Page: Opt Out Handler
│   └── End Flow Pages (Success, Warm, Not Interested, Opted Out)
│
├── Flow: follow-up
│   ├── Page: Greeting
│   ├── Page: Email Check
│   ├── Page: Email Discussion
│   ├── Page: Quick Pitch
│   └── End Flow Pages
│
├── Flow: appointment-setting
│   ├── Page: Time Preference
│   ├── Page: Propose Options
│   ├── Page: Confirm Meeting
│   ├── Page: Capture Email
│   └── Page: Finalize Meeting
│
├── Flow: lead-qualification
│   ├── Page: Start
│   ├── Page: Current System
│   ├── Page: User Count
│   ├── Page: Timeline
│   ├── Page: Pain Points
│   ├── Page: Score Lead
│   └── Route Pages (Hot, Warm, Cold)
│
├── Flow: info-delivery
│   ├── Page: Deliver Message
│   ├── Page: Response Handler
│   ├── Page: Action Handler
│   └── End Flow Pages
│
└── Flow: common-handlers
    ├── Page: Gemini Handler
    ├── Page: No Input Handler
    ├── Page: Schedule Callback
    └── Page: Find Right Person
```

### 2.3 Default Start Flow

**Start Page Routes:**
```yaml
Routes:
  - Condition: $session.params.use_case = "cold_calling"
    Target: cold-calling.Start
    
  - Condition: $session.params.use_case = "follow_up"
    Target: follow-up.Start
    
  - Condition: $session.params.use_case = "appointment_setting"
    Target: appointment-setting.Start
    
  - Condition: $session.params.use_case = "lead_qualification"
    Target: lead-qualification.Start
    
  - Condition: $session.params.use_case = "info_delivery"
    Target: info-delivery.Start
    
  - Condition: true (default)
    Target: cold-calling.Start
```

### 2.4 Webhook Configuration

**Webhook Settings:**
```yaml
Webhooks:
  - Name: gemini-responder
    URL: https://us-central1-tatt-pro.cloudfunctions.net/gemini-responder
    Timeout: 5 seconds
    
  - Name: calendar-availability
    URL: https://us-central1-tatt-pro.cloudfunctions.net/calendar-availability
    Timeout: 5 seconds
    
  - Name: calendar-book
    URL: https://us-central1-tatt-pro.cloudfunctions.net/calendar-book
    Timeout: 5 seconds
    
  - Name: salesforce-update
    URL: https://us-central1-tatt-pro.cloudfunctions.net/salesforce-update
    Timeout: 10 seconds
    
  - Name: call-logger
    URL: https://us-central1-tatt-pro.cloudfunctions.net/call-logger
    Timeout: 5 seconds
    
  - Name: send-email
    URL: https://us-central1-tatt-pro.cloudfunctions.net/send-email
    Timeout: 5 seconds
```

### 2.5 Session Parameters

**Initialize at Call Start:**
```json
{
  "account_id": "001XXXXXXXXXXXXXXX",
  "account_name": "Phoenix Union High School District",
  "account_type": "K12",
  "account_state": "AZ",
  "contact_id": "003XXXXXXXXXXXXXXX",
  "contact_name": "John",
  "contact_title": "IT Director",
  "contact_email": "jsmith@phoenix.k12.az.us",
  "phone_number": "+16025551234",
  "use_case": "cold_calling",
  "conversation_goal": "qualify_interest",
  "lead_score": 0,
  "pain_points": [],
  "current_system": null,
  "objections_count": 0,
  "meeting_scheduled": false,
  "opted_out": false,
  "call_start_time": "2026-02-10T17:30:00Z"
}
```

### 2.6 Environment Configuration

**Environments:**
```yaml
draft:
  Description: Development/testing
  Webhook Override: None (uses function URLs directly)
  
staging:
  Description: Pre-production testing
  Webhook Override: Point to staging Cloud Functions
  
production:
  Description: Live calls
  Webhook Override: None (uses production function URLs)
  Traffic Split: 100%
```

---

## 3. Cloud Functions Specifications

### 3.1 Function: gemini-responder

**Purpose:** Generate intelligent responses using Vertex AI Gemini

**Runtime:** Node.js 20  
**Memory:** 512 MB  
**Timeout:** 60 seconds  
**Trigger:** HTTP  

**Input (Dialogflow Webhook Request):**
```typescript
interface GeminiRequest {
  detectIntentResponseId: string;
  intentInfo?: {
    lastMatchedIntent: string;
    displayName: string;
    confidence: number;
  };
  pageInfo: {
    currentPage: string;
    displayName: string;
  };
  sessionInfo: {
    session: string;
    parameters: {
      account_name: string;
      contact_name: string;
      conversation_goal: string;
      current_system?: string;
      pain_points?: string[];
      lead_score?: number;
    };
  };
  text: string;
  languageCode: string;
}
```

**Output (Dialogflow Webhook Response):**
```typescript
interface GeminiResponse {
  fulfillmentResponse: {
    messages: [{
      text: {
        text: string[];
      };
    }];
    mergeBehavior: 'REPLACE' | 'APPEND';
  };
  sessionInfo?: {
    parameters?: {
      [key: string]: any;
    };
  };
  targetPage?: string;
}
```

**Implementation:**
```javascript
const { VertexAI } = require('@google-cloud/vertexai');

const vertex = new VertexAI({
  project: 'tatt-pro',
  location: 'us-central1'
});

const model = vertex.preview.getGenerativeModel({
  model: 'gemini-1.5-flash-002',
  generationConfig: {
    maxOutputTokens: 100,
    temperature: 0.7,
    topP: 0.95
  }
});

exports.geminiResponder = async (req, res) => {
  try {
    const { text, sessionInfo, pageInfo } = req.body;
    const params = sessionInfo.parameters || {};
    
    const prompt = buildPrompt(text, params, pageInfo.displayName);
    const result = await model.generateContent(prompt);
    const response = result.response.text();
    
    // Clean for TTS
    const cleanResponse = response
      .replace(/[*_~`]/g, '')
      .replace(/\n/g, ' ')
      .trim();
    
    // Detect if we should update parameters or route
    const updates = detectParameterUpdates(text, response);
    
    res.json({
      fulfillmentResponse: {
        messages: [{
          text: { text: [cleanResponse] }
        }],
        mergeBehavior: 'REPLACE'
      },
      sessionInfo: {
        parameters: updates.parameters
      },
      targetPage: updates.targetPage
    });
    
  } catch (error) {
    console.error('Gemini error:', error);
    
    // Fallback response
    res.json({
      fulfillmentResponse: {
        messages: [{
          text: { text: ['That\'s a great question. Let me have someone follow up with more details.'] }
        }]
      }
    });
  }
};

function buildPrompt(userInput, params, currentPage) {
  return `
You are Paul, a friendly sales representative from Fortinet calling a prospect.

Context:
- Speaking with: ${params.contact_name} (${params.contact_title || 'contact'}) from ${params.account_name}
- Current goal: ${params.conversation_goal}
- Current page: ${currentPage}
- Their system: ${params.current_system || 'unknown'}
- Pain points: ${(params.pain_points || []).join(', ') || 'none mentioned'}

The caller just said: "${userInput}"

Generate a natural, conversational response that:
1. Acknowledges what they said
2. Keeps them engaged
3. Moves toward the goal
4. Sounds human, not robotic
5. Is under 50 words (phone-friendly)

Response:`;
}
```

**Error Handling:**
| Error | Response |
|-------|----------|
| Timeout | Return fallback: "Let me think about that..." |
| Rate Limit | Queue request, return fallback |
| Content Filter | "That's a great question. Let me have someone follow up." |

---

### 3.2 Function: calendar-availability

**Purpose:** Check Google Calendar for available meeting slots

**Runtime:** Node.js 20  
**Memory:** 256 MB  
**Timeout:** 30 seconds  

**Input:**
```typescript
interface CalendarAvailabilityRequest {
  sessionInfo: {
    parameters: {
      time_preference?: 'morning' | 'afternoon' | 'anytime';
      date_preference?: string;  // "next_week", "this_week", or specific date
      duration_minutes?: number;
    };
  };
}
```

**Output:**
```typescript
interface CalendarAvailabilityResponse {
  fulfillmentResponse: {
    messages: [{
      text: { text: string[] };
    }];
  };
  sessionInfo: {
    parameters: {
      available_slots: Array<{
        date: string;      // "2026-02-17"
        time: string;      // "09:30"
        datetime: string;  // ISO string
        display: string;   // "Tuesday at 9:30 AM"
      }>;
    };
  };
}
```

**Implementation:**
```javascript
const { google } = require('googleapis');
const { SecretManagerServiceClient } = require('@google-cloud/secret-manager');

const secretClient = new SecretManagerServiceClient();

exports.calendarAvailability = async (req, res) => {
  const params = req.body.sessionInfo?.parameters || {};
  const timePreference = params.time_preference || 'anytime';
  const duration = params.duration_minutes || 30;
  
  // Get service account credentials
  const credentials = await getSecret('calendar-service-account');
  
  const auth = new google.auth.GoogleAuth({
    credentials: JSON.parse(credentials),
    scopes: ['https://www.googleapis.com/auth/calendar.readonly']
  });
  
  const calendar = google.calendar({ version: 'v3', auth });
  
  // Calculate time window
  const { timeMin, timeMax } = getTimeWindow(params.date_preference);
  
  // Get busy times
  const freeBusy = await calendar.freebusy.query({
    requestBody: {
      timeMin: timeMin.toISOString(),
      timeMax: timeMax.toISOString(),
      timeZone: 'America/Phoenix',
      items: [{ id: process.env.CALENDAR_ID }]
    }
  });
  
  const busySlots = freeBusy.data.calendars[process.env.CALENDAR_ID].busy;
  
  // Find available slots
  const slots = findAvailableSlots(
    timeMin, 
    timeMax, 
    busySlots, 
    timePreference, 
    duration
  );
  
  // Format response
  const topSlots = slots.slice(0, 3);
  const displayText = formatSlotsForSpeech(topSlots);
  
  res.json({
    fulfillmentResponse: {
      messages: [{
        text: { text: [displayText] }
      }]
    },
    sessionInfo: {
      parameters: {
        available_slots: topSlots
      }
    }
  });
};

function findAvailableSlots(start, end, busy, preference, duration) {
  const slots = [];
  const current = new Date(start);
  
  while (current < end && slots.length < 10) {
    const hour = current.getHours();
    
    // Check time preference
    if (preference === 'morning' && hour >= 12) {
      current.setDate(current.getDate() + 1);
      current.setHours(8, 0, 0, 0);
      continue;
    }
    if (preference === 'afternoon' && hour < 12) {
      current.setHours(12, 0, 0, 0);
      continue;
    }
    
    // Check if slot is free
    const slotEnd = new Date(current.getTime() + duration * 60000);
    const isBusy = busy.some(b => 
      new Date(b.start) < slotEnd && new Date(b.end) > current
    );
    
    if (!isBusy && hour >= 8 && hour < 17) {
      slots.push({
        date: current.toISOString().split('T')[0],
        time: current.toTimeString().slice(0, 5),
        datetime: current.toISOString(),
        display: formatForSpeech(current)
      });
    }
    
    current.setMinutes(current.getMinutes() + 30);
  }
  
  return slots;
}

function formatForSpeech(date) {
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const day = days[date.getDay()];
  const hour = date.getHours();
  const minute = date.getMinutes();
  const ampm = hour >= 12 ? 'PM' : 'AM';
  const hour12 = hour % 12 || 12;
  const minuteStr = minute === 0 ? '' : `:${minute.toString().padStart(2, '0')}`;
  
  return `${day} at ${hour12}${minuteStr} ${ampm}`;
}
```

---

### 3.3 Function: calendar-book

**Purpose:** Create Google Calendar event for booked meeting

**Runtime:** Node.js 20  
**Memory:** 256 MB  
**Timeout:** 30 seconds  

**Input:**
```typescript
interface CalendarBookRequest {
  sessionInfo: {
    parameters: {
      selected_slot: {
        datetime: string;
        display: string;
      };
      attendee_email: string;
      account_name: string;
      contact_name: string;
      contact_title?: string;
      meeting_topics?: string;
    };
  };
}
```

**Output:**
```typescript
interface CalendarBookResponse {
  fulfillmentResponse: {
    messages: [{
      text: { text: string[] };
    }];
  };
  sessionInfo: {
    parameters: {
      calendar_event_id: string;
      meeting_link: string;
      meeting_confirmed: boolean;
    };
  };
}
```

**Implementation:**
```javascript
exports.calendarBook = async (req, res) => {
  const params = req.body.sessionInfo?.parameters || {};
  const slot = params.selected_slot;
  
  const credentials = await getSecret('calendar-service-account');
  const auth = new google.auth.GoogleAuth({
    credentials: JSON.parse(credentials),
    scopes: ['https://www.googleapis.com/auth/calendar']
  });
  
  const calendar = google.calendar({ version: 'v3', auth });
  
  const startTime = new Date(slot.datetime);
  const endTime = new Date(startTime.getTime() + 30 * 60000); // 30 min
  
  const event = {
    summary: `FortiVoice Discovery Call - ${params.account_name}`,
    description: `
Call with ${params.contact_name}${params.contact_title ? ` (${params.contact_title})` : ''}
Account: ${params.account_name}

Topics to cover:
${params.meeting_topics || 'Voice modernization, local survivability'}

Prepared by: AI Voice Caller
    `.trim(),
    start: {
      dateTime: startTime.toISOString(),
      timeZone: 'America/Phoenix'
    },
    end: {
      dateTime: endTime.toISOString(),
      timeZone: 'America/Phoenix'
    },
    attendees: [
      { email: params.attendee_email },
      { email: process.env.PARTNER_EMAIL },  // High Point Networks
      { email: process.env.OWNER_EMAIL }     // Paul
    ],
    conferenceData: {
      createRequest: {
        requestId: `voice-caller-${Date.now()}`,
        conferenceSolutionKey: { type: 'hangoutsMeet' }
      }
    },
    reminders: {
      useDefault: false,
      overrides: [
        { method: 'email', minutes: 24 * 60 },  // 1 day before
        { method: 'popup', minutes: 30 }         // 30 min before
      ]
    }
  };
  
  const result = await calendar.events.insert({
    calendarId: process.env.CALENDAR_ID,
    requestBody: event,
    conferenceDataVersion: 1,
    sendUpdates: 'all'
  });
  
  const meetingLink = result.data.conferenceData?.entryPoints?.[0]?.uri || '';
  
  res.json({
    fulfillmentResponse: {
      messages: [{
        text: { text: [''] }  // No spoken confirmation needed here
      }]
    },
    sessionInfo: {
      parameters: {
        calendar_event_id: result.data.id,
        meeting_link: meetingLink,
        meeting_confirmed: true
      }
    }
  });
};
```

---

### 3.4 Function: salesforce-update

**Purpose:** Create tasks and update records in Salesforce

**Runtime:** Node.js 20  
**Memory:** 256 MB  
**Timeout:** 60 seconds  

**Input:**
```typescript
interface SalesforceUpdateRequest {
  action: 'create_task' | 'update_lead' | 'log_activity';
  sessionInfo: {
    parameters: {
      account_id: string;
      contact_id: string;
      call_outcome: string;
      meeting_date?: string;
      notes?: string;
      lead_score?: number;
    };
  };
}
```

**Implementation:**
```javascript
const jsforce = require('jsforce');
const { SecretManagerServiceClient } = require('@google-cloud/secret-manager');

let sfConnection = null;

async function getSalesforceConnection() {
  if (sfConnection && sfConnection.accessToken) {
    return sfConnection;
  }
  
  const clientId = await getSecret('salesforce-client-id');
  const clientSecret = await getSecret('salesforce-client-secret');
  const username = await getSecret('salesforce-username');
  const password = await getSecret('salesforce-password');
  const securityToken = await getSecret('salesforce-security-token');
  
  sfConnection = new jsforce.Connection({
    loginUrl: 'https://login.salesforce.com'
  });
  
  await sfConnection.login(username, password + securityToken);
  return sfConnection;
}

exports.salesforceUpdate = async (req, res) => {
  const { action, sessionInfo } = req.body;
  const params = sessionInfo?.parameters || {};
  
  const conn = await getSalesforceConnection();
  
  let result;
  
  switch (action) {
    case 'create_task':
      result = await createTask(conn, params);
      break;
    case 'update_lead':
      result = await updateLead(conn, params);
      break;
    case 'log_activity':
      result = await logActivity(conn, params);
      break;
  }
  
  res.json({
    fulfillmentResponse: {
      messages: [{ text: { text: [''] } }]
    },
    sessionInfo: {
      parameters: {
        salesforce_updated: true,
        task_id: result?.id
      }
    }
  });
};

async function createTask(conn, params) {
  const taskData = {
    Subject: getTaskSubject(params.call_outcome),
    WhoId: params.contact_id,
    WhatId: params.account_id,
    OwnerId: process.env.SALESFORCE_OWNER_ID,  // Paul's user ID
    Priority: params.lead_score >= 5 ? 'High' : 'Normal',
    Status: 'Not Started',
    ActivityDate: params.meeting_date 
      ? params.meeting_date.split('T')[0]
      : new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    Description: buildTaskDescription(params),
    Type: 'Call'
  };
  
  return conn.sobject('Task').create(taskData);
}

function getTaskSubject(outcome) {
  const subjects = {
    'interested_meeting_booked': 'Prep for scheduled demo call',
    'interested_send_info': 'Follow up on sent materials',
    'callback_scheduled': 'Scheduled callback',
    'not_interested_timing': 'Long-term follow up',
    'voicemail': 'Follow up after voicemail'
  };
  return subjects[outcome] || 'Voice caller follow-up';
}

function buildTaskDescription(params) {
  return `
AI Voice Caller Outcome: ${params.call_outcome}
Lead Score: ${params.lead_score || 'N/A'}

${params.meeting_date ? `Meeting Scheduled: ${params.meeting_date}` : ''}

Notes:
${params.notes || 'No additional notes'}

Discovery Data:
- Current System: ${params.current_system || 'Not captured'}
- Pain Points: ${(params.pain_points || []).join(', ') || 'None mentioned'}
  `.trim();
}

async function updateLead(conn, params) {
  const leadStatus = {
    'interested_meeting_booked': 'Working - Contacted',
    'interested_send_info': 'Working - Contacted',
    'callback_scheduled': 'Working - Contacted',
    'not_interested_permanent': 'Closed - Not Converted',
    'opted_out': 'Closed - Not Converted'
  };
  
  return conn.sobject('Lead').update({
    Id: params.lead_id,
    Status: leadStatus[params.call_outcome],
    Lead_Score__c: params.lead_score,
    Last_Voice_Call__c: new Date().toISOString()
  });
}

async function logActivity(conn, params) {
  return conn.sobject('Event').create({
    Subject: 'AI Voice Call',
    WhoId: params.contact_id,
    WhatId: params.account_id,
    StartDateTime: params.call_start_time,
    EndDateTime: params.call_end_time,
    Description: params.call_summary,
    Type: 'Call'
  });
}
```

---

### 3.5 Function: call-logger

**Purpose:** Log call data to Firestore

**Runtime:** Node.js 20  
**Memory:** 256 MB  
**Timeout:** 30 seconds  

**Implementation:**
```javascript
const { Firestore } = require('@google-cloud/firestore');
const firestore = new Firestore();

exports.callLogger = async (req, res) => {
  const params = req.body.sessionInfo?.parameters || {};
  const session = req.body.sessionInfo?.session || '';
  
  const callDoc = {
    call_id: `call_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    session_id: session,
    
    // Timing
    initiated_at: new Date(params.call_start_time || Date.now()),
    ended_at: Firestore.Timestamp.now(),
    duration_seconds: params.call_duration_seconds || 0,
    
    // Contact info
    phone_number: params.phone_number,
    account: {
      id: params.account_id,
      name: params.account_name,
      type: params.account_type
    },
    contact: {
      id: params.contact_id,
      name: params.contact_name,
      title: params.contact_title,
      email: params.contact_email
    },
    
    // Conversation
    use_case: params.use_case,
    call_outcome: params.call_outcome || 'unknown',
    lead_score: params.lead_score || 0,
    
    // Discovery data
    discovery_data: {
      current_system: params.current_system,
      pain_points: params.pain_points || [],
      buying_timeline: params.buying_timeline,
      competitors_mentioned: params.competitors_mentioned || []
    },
    
    // Meeting (if booked)
    meeting: params.meeting_scheduled ? {
      scheduled: true,
      datetime: params.meeting_datetime,
      calendar_event_id: params.calendar_event_id,
      meeting_link: params.meeting_link
    } : { scheduled: false },
    
    // Opt-out
    opted_out: params.opted_out || false,
    
    // Metadata
    created_at: Firestore.Timestamp.now(),
    updated_at: Firestore.Timestamp.now()
  };
  
  // Save to Firestore
  await firestore.collection('calls').add(callDoc);
  
  // If opted out, add to DNC list
  if (params.opted_out) {
    await firestore.collection('do_not_call').doc(params.phone_number).set({
      phone_number: params.phone_number,
      opted_out_at: Firestore.Timestamp.now(),
      opt_out_source: 'voice_call',
      account_id: params.account_id,
      contact_id: params.contact_id
    });
  }
  
  res.json({
    fulfillmentResponse: {
      messages: [{ text: { text: [''] } }]
    }
  });
};
```

---

### 3.6 Function: call-status-handler

**Purpose:** Handle SignalWire call status webhooks

**Runtime:** Node.js 20  
**Memory:** 256 MB  
**Timeout:** 30 seconds  

**Implementation:**
```javascript
const { Firestore } = require('@google-cloud/firestore');
const firestore = new Firestore();

exports.callStatusHandler = async (req, res) => {
  const {
    CallSid,
    CallStatus,
    Duration,
    From,
    To,
    Timestamp
  } = req.body;
  
  console.log(`Call ${CallSid}: ${CallStatus}`);
  
  // Find call in Firestore by SignalWire SID
  const callsRef = firestore.collection('calls');
  const query = await callsRef
    .where('signalwire_call_sid', '==', CallSid)
    .limit(1)
    .get();
  
  if (!query.empty) {
    const doc = query.docs[0];
    
    const updates = {
      call_status: CallStatus,
      updated_at: Firestore.Timestamp.now()
    };
    
    if (CallStatus === 'answered') {
      updates.answered_at = Firestore.Timestamp.now();
    }
    
    if (CallStatus === 'completed') {
      updates.ended_at = Firestore.Timestamp.now();
      updates.duration_seconds = parseInt(Duration) || 0;
    }
    
    if (['no-answer', 'busy', 'failed'].includes(CallStatus)) {
      updates.call_outcome = CallStatus.replace('-', '_');
      
      // Schedule retry if appropriate
      await scheduleRetry(doc.data(), CallStatus);
    }
    
    await doc.ref.update(updates);
  }
  
  // SignalWire expects 200 OK
  res.status(200).send('OK');
};

async function scheduleRetry(callData, status) {
  const maxRetries = 2;
  const currentRetries = callData.retry_count || 0;
  
  if (currentRetries >= maxRetries) {
    return;  // No more retries
  }
  
  // Calculate retry time
  let retryDelay;
  if (status === 'busy') {
    retryDelay = 60 * 60 * 1000;  // 1 hour
  } else if (status === 'no-answer') {
    retryDelay = 24 * 60 * 60 * 1000;  // 24 hours
  } else {
    return;  // Don't retry failed calls
  }
  
  const retryAt = new Date(Date.now() + retryDelay);
  
  // Add to retry queue
  await firestore.collection('call_retry_queue').add({
    original_call_id: callData.call_id,
    contact_id: callData.contact.id,
    phone_number: callData.phone_number,
    retry_at: Firestore.Timestamp.fromDate(retryAt),
    retry_count: currentRetries + 1,
    use_case: callData.use_case,
    session_params: callData.session_params || {}
  });
}
```

---

### 3.7 Function: batch-caller

**Purpose:** Process batch calling jobs from Cloud Scheduler

**Runtime:** Node.js 20  
**Memory:** 512 MB  
**Timeout:** 540 seconds (9 minutes)  

**Trigger:** Cloud Scheduler (cron) + HTTP

**Implementation:**
```javascript
const { Firestore } = require('@google-cloud/firestore');
const { RestClient } = require('@signalwire/compatibility-api');

const firestore = new Firestore();
const signalwire = new RestClient(
  process.env.SIGNALWIRE_PROJECT_ID,
  process.env.SIGNALWIRE_API_TOKEN,
  { signalwireSpaceUrl: 'fortinet-voice.signalwire.com' }
);

exports.batchCaller = async (req, res) => {
  // Get active batch jobs
  const batchesRef = firestore.collection('call_batches');
  const activeBatches = await batchesRef
    .where('status', '==', 'in_progress')
    .get();
  
  for (const batchDoc of activeBatches.docs) {
    await processBatch(batchDoc);
  }
  
  // Also process retry queue
  await processRetryQueue();
  
  res.json({ processed: activeBatches.size });
};

async function processBatch(batchDoc) {
  const batch = batchDoc.data();
  const maxConcurrent = batch.settings?.max_concurrent_calls || 3;
  
  // Check calling window
  if (!isWithinCallingWindow(batch.schedule)) {
    return;
  }
  
  // Get pending contacts
  const pendingContacts = batch.contact_list.filter(c => c.status === 'pending');
  const inProgressCount = batch.contact_list.filter(c => c.status === 'in_progress').length;
  
  // Calculate how many calls to initiate
  const slotsAvailable = maxConcurrent - inProgressCount;
  const toCall = pendingContacts.slice(0, slotsAvailable);
  
  for (const contact of toCall) {
    // Check DNC before calling
    const isDNC = await checkDNC(contact.phone);
    if (isDNC) {
      await updateContactStatus(batchDoc, contact.contact_id, 'skipped_dnc');
      continue;
    }
    
    // Initiate call
    try {
      const callSid = await initiateCall(contact, batch);
      await updateContactStatus(batchDoc, contact.contact_id, 'in_progress', callSid);
    } catch (error) {
      console.error(`Failed to call ${contact.phone}:`, error);
      await updateContactStatus(batchDoc, contact.contact_id, 'failed');
    }
  }
  
  // Check if batch is complete
  const updatedBatch = (await batchDoc.ref.get()).data();
  const completed = updatedBatch.contact_list.every(c => 
    !['pending', 'in_progress'].includes(c.status)
  );
  
  if (completed) {
    await batchDoc.ref.update({ 
      status: 'completed',
      completed_at: Firestore.Timestamp.now()
    });
  }
}

async function initiateCall(contact, batch) {
  const call = await signalwire.calls.create({
    from: process.env.CALLER_ID,
    to: contact.phone,
    url: `https://fortinet-voice.signalwire.com/laml-bins/${process.env.LAML_BIN_ID}`,
    statusCallback: process.env.STATUS_CALLBACK_URL,
    statusCallbackEvent: ['initiated', 'ringing', 'answered', 'completed'],
    method: 'POST'
  });
  
  // Store session params for Dialogflow
  await firestore.collection('call_sessions').doc(call.sid).set({
    account_id: contact.account_id,
    account_name: contact.account_name,
    contact_id: contact.contact_id,
    contact_name: contact.contact_name,
    use_case: batch.use_case,
    batch_id: batch.batch_id
  });
  
  return call.sid;
}

function isWithinCallingWindow(schedule) {
  const now = new Date();
  const hour = now.getHours();
  const day = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'][now.getDay()];
  
  if (!schedule.days_of_week.includes(day)) {
    return false;
  }
  
  const [startHour] = schedule.call_window_start.split(':').map(Number);
  const [endHour] = schedule.call_window_end.split(':').map(Number);
  
  return hour >= startHour && hour < endHour;
}

async function checkDNC(phoneNumber) {
  const doc = await firestore.collection('do_not_call').doc(phoneNumber).get();
  return doc.exists;
}
```

---

## 4. Salesforce Integration

### 4.1 Connected App Setup

**Create Connected App in Salesforce:**
```
Setup → Apps → App Manager → New Connected App

Settings:
  Connected App Name: Fortinet Voice Caller
  API Name: Fortinet_Voice_Caller
  Contact Email: paul@fortinet.com
  
OAuth Settings:
  Enable OAuth: ✓
  Callback URL: https://localhost/callback
  Selected Scopes:
    - Access and manage your data (api)
    - Perform requests on your behalf at any time (refresh_token)
  
Settings:
  Require Secret for Web Server Flow: ✓
  Require Secret for Refresh Token Flow: ✓
```

**Retrieve Consumer Key and Secret:**
```
1. Save the Connected App
2. Click "Manage Consumer Details"
3. Copy Consumer Key and Consumer Secret
4. Store in Google Secret Manager
```

### 4.2 Authentication Flow

**Initial Token Retrieval (Username-Password Flow):**
```bash
curl -X POST https://login.salesforce.com/services/oauth2/token \
  -d "grant_type=password" \
  -d "client_id={CONSUMER_KEY}" \
  -d "client_secret={CONSUMER_SECRET}" \
  -d "username={USERNAME}" \
  -d "password={PASSWORD}{SECURITY_TOKEN}"
```

**Store Tokens:**
```javascript
// Store refresh token in Secret Manager
// Access token expires every 2 hours - refresh as needed

async function getAccessToken() {
  // Try cached token first
  if (cachedToken && cachedToken.expires_at > Date.now()) {
    return cachedToken.access_token;
  }
  
  // Refresh token
  const refreshToken = await getSecret('salesforce-refresh-token');
  const response = await fetch('https://login.salesforce.com/services/oauth2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: process.env.SF_CLIENT_ID,
      client_secret: process.env.SF_CLIENT_SECRET,
      refresh_token: refreshToken
    })
  });
  
  const data = await response.json();
  cachedToken = {
    access_token: data.access_token,
    instance_url: data.instance_url,
    expires_at: Date.now() + (2 * 60 * 60 * 1000) - 300000  // 2 hours minus 5 min buffer
  };
  
  return cachedToken.access_token;
}
```

### 4.3 API Endpoints Used

**Create Task:**
```javascript
POST /services/data/v59.0/sobjects/Task
{
  "Subject": "Follow-up call - Voice system discussion",
  "WhoId": "003XXXXXXXXXXXXXXX",  // Contact ID
  "WhatId": "001XXXXXXXXXXXXXXX",  // Account ID
  "OwnerId": "005XXXXXXXXXXXXXXX",  // User ID
  "Priority": "High",
  "Status": "Not Started",
  "ActivityDate": "2026-02-17",
  "Description": "AI voice caller notes...",
  "Type": "Call"
}
```

**Update Lead:**
```javascript
PATCH /services/data/v59.0/sobjects/Lead/{LeadId}
{
  "Status": "Working - Contacted",
  "Lead_Score__c": 7,
  "Last_Voice_Call__c": "2026-02-10T17:45:00Z"
}
```

**Query Accounts:**
```javascript
GET /services/data/v59.0/query?q=
SELECT Id, Name, Type, Phone, 
       (SELECT Id, Name, Title, Phone, Email FROM Contacts)
FROM Account 
WHERE Industry = 'Education' 
  AND BillingState = 'AZ'
LIMIT 100
```

### 4.4 Custom Fields (Optional)

**Create Custom Fields for Voice Caller:**
```
Object: Account
  - Last_Voice_Call__c (DateTime)
  - Voice_Call_Count__c (Number)
  - Voice_Lead_Score__c (Number)
  
Object: Contact
  - Do_Not_Voice_Call__c (Checkbox)
  - Voice_Call_Preference__c (Picklist: Morning, Afternoon, Anytime)
  
Object: Lead
  - Voice_Lead_Score__c (Number)
  - Voice_Call_Outcome__c (Picklist)
```

---

## 5. Google Calendar Integration

### 5.1 Service Account Setup

**Create Service Account:**
```bash
# Create service account
gcloud iam service-accounts create voice-caller-calendar \
  --display-name="Voice Caller Calendar"

# Grant Calendar API access
gcloud projects add-iam-policy-binding tatt-pro \
  --member="serviceAccount:voice-caller-calendar@tatt-pro.iam.gserviceaccount.com" \
  --role="roles/calendar.events.creator"

# Create and download key
gcloud iam service-accounts keys create calendar-sa-key.json \
  --iam-account=voice-caller-calendar@tatt-pro.iam.gserviceaccount.com

# Upload to Secret Manager
gcloud secrets create calendar-service-account \
  --data-file=calendar-sa-key.json

# Delete local key
rm calendar-sa-key.json
```

**Delegate Domain-Wide Authority:**
```
1. Go to Google Admin Console → Security → API Controls → Domain-wide Delegation
2. Add new client:
   - Client ID: (service account client ID from JSON)
   - Scopes: https://www.googleapis.com/auth/calendar
3. Enable for user: paul@fortinet.com
```

### 5.2 Calendar Configuration

**Primary Calendar Settings:**
```yaml
Calendar ID: paul@fortinet.com  # or dedicated calendar
Meeting Duration: 30 minutes
Buffer Between Meetings: 15 minutes
Available Hours: 8:00 AM - 5:00 PM MST
Available Days: Monday - Friday
```

**Create Dedicated Calendar (Optional):**
```javascript
const calendar = google.calendar({ version: 'v3', auth });

const newCalendar = await calendar.calendars.insert({
  requestBody: {
    summary: 'Voice Caller Meetings',
    timeZone: 'America/Phoenix'
  }
});

// Share with relevant people
await calendar.acl.insert({
  calendarId: newCalendar.data.id,
  requestBody: {
    role: 'writer',
    scope: { type: 'user', value: 'partner@highpointnetworks.com' }
  }
});
```

---

## 6. Email Integration

### 6.1 SendGrid Setup (Recommended)

**API Key Configuration:**
```bash
# Store in Secret Manager
gcloud secrets create sendgrid-api-key \
  --data-file=- <<< "SG.xxxxxxxxxxxxx"
```

**Email Templates:**
```javascript
// templates/follow-up-info.html
const templates = {
  follow_up_info: 'd-abc123',  // SendGrid template ID
  meeting_confirmation: 'd-def456',
  case_study: 'd-ghi789'
};
```

### 6.2 Function: send-email

**Implementation:**
```javascript
const sgMail = require('@sendgrid/mail');

exports.sendEmail = async (req, res) => {
  const params = req.body.sessionInfo?.parameters || {};
  const emailType = params.email_type || 'follow_up_info';
  
  const apiKey = await getSecret('sendgrid-api-key');
  sgMail.setApiKey(apiKey);
  
  const msg = {
    to: params.recipient_email,
    from: {
      email: 'paul@fortinet.com',
      name: 'Paul Scirocco'
    },
    templateId: templates[emailType],
    dynamicTemplateData: {
      contact_name: params.contact_name,
      account_name: params.account_name,
      content_type: params.content_type,
      meeting_date: params.meeting_date,
      meeting_link: params.meeting_link
    }
  };
  
  await sgMail.send(msg);
  
  res.json({
    fulfillmentResponse: {
      messages: [{ text: { text: [''] } }]
    },
    sessionInfo: {
      parameters: {
        email_sent: true,
        email_sent_at: new Date().toISOString()
      }
    }
  });
};
```

---

## 7. Deployment Scripts

### 7.1 Deploy All Cloud Functions

**deploy-functions.sh:**
```bash
#!/bin/bash
set -e

PROJECT_ID="tatt-pro"
REGION="us-central1"

FUNCTIONS=(
  "gemini-responder"
  "calendar-availability"
  "calendar-book"
  "salesforce-update"
  "call-logger"
  "call-status-handler"
  "batch-caller"
  "send-email"
)

for func in "${FUNCTIONS[@]}"; do
  echo "Deploying $func..."
  
  gcloud functions deploy "$func" \
    --gen2 \
    --runtime=nodejs20 \
    --region="$REGION" \
    --source="./cloud-functions/$func" \
    --entry-point="$(echo $func | sed 's/-/_/g')" \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512MB \
    --timeout=60s \
    --set-env-vars="PROJECT_ID=$PROJECT_ID" \
    --set-secrets="SIGNALWIRE_PROJECT_ID=signalwire-project-id:latest,SIGNALWIRE_API_TOKEN=signalwire-api-token:latest"
    
  echo "✓ Deployed $func"
done

echo "All functions deployed successfully!"
```

### 7.2 Deploy Dialogflow Agent

**deploy-dialogflow.sh:**
```bash
#!/bin/bash
set -e

AGENT_ID="your-agent-id"
PROJECT_ID="tatt-pro"
REGION="us-central1"

# Export current agent (backup)
echo "Backing up current agent..."
gcloud dialogflow cx agents export \
  --agent="projects/$PROJECT_ID/locations/$REGION/agents/$AGENT_ID" \
  --destination="gs://tatt-pro-backups/dialogflow/agent-backup-$(date +%Y%m%d).blob"

# Restore from local export
echo "Deploying agent..."
gcloud dialogflow cx agents restore \
  --agent="projects/$PROJECT_ID/locations/$REGION/agents/$AGENT_ID" \
  --source="./dialogflow-agent/agent-export.blob"

echo "Agent deployed successfully!"
```

### 7.3 Initialize Firestore

**init-firestore.sh:**
```bash
#!/bin/bash

# Create indexes
gcloud firestore indexes composite create \
  --collection-group=calls \
  --field-config field-path=call_outcome,order=ASCENDING \
  --field-config field-path=initiated_at,order=DESCENDING

gcloud firestore indexes composite create \
  --collection-group=calls \
  --field-config field-path=account.id,order=ASCENDING \
  --field-config field-path=initiated_at,order=DESCENDING

gcloud firestore indexes composite create \
  --collection-group=calls \
  --field-config field-path=lead_score,order=DESCENDING \
  --field-config field-path=initiated_at,order=DESCENDING

echo "Firestore indexes created!"
```

### 7.4 Setup Cloud Scheduler

**setup-scheduler.sh:**
```bash
#!/bin/bash

# Batch caller - runs every 15 minutes during business hours
gcloud scheduler jobs create http batch-caller \
  --schedule="*/15 8-17 * * 1-5" \
  --time-zone="America/Phoenix" \
  --uri="https://us-central1-tatt-pro.cloudfunctions.net/batch-caller" \
  --http-method=POST \
  --oidc-service-account-email="voice-caller-sa@tatt-pro.iam.gserviceaccount.com"

# Daily cleanup - runs at midnight
gcloud scheduler jobs create http daily-cleanup \
  --schedule="0 0 * * *" \
  --time-zone="America/Phoenix" \
  --uri="https://us-central1-tatt-pro.cloudfunctions.net/daily-cleanup" \
  --http-method=POST \
  --oidc-service-account-email="voice-caller-sa@tatt-pro.iam.gserviceaccount.com"

echo "Cloud Scheduler jobs created!"
```

### 7.5 Full Deployment

**deploy-all.sh:**
```bash
#!/bin/bash
set -e

echo "=== AI Voice Caller Full Deployment ==="
echo ""

# 1. Deploy Cloud Functions
echo "Step 1: Deploying Cloud Functions..."
./scripts/deploy-functions.sh

# 2. Deploy Dialogflow Agent
echo "Step 2: Deploying Dialogflow Agent..."
./scripts/deploy-dialogflow.sh

# 3. Initialize Firestore (first time only)
if [ "$1" == "--init" ]; then
  echo "Step 3: Initializing Firestore..."
  ./scripts/init-firestore.sh
fi

# 4. Setup Cloud Scheduler (first time only)
if [ "$1" == "--init" ]; then
  echo "Step 4: Setting up Cloud Scheduler..."
  ./scripts/setup-scheduler.sh
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Configure SignalWire phone numbers"
echo "2. Update webhook URLs in Dialogflow"
echo "3. Run test calls"
```

---

## Document Control

**Author:** AI Voice Caller Subagent  
**Created:** 2026-02-10  
**Status:** Ready for Implementation  
**Dependencies:** TECHNICAL-SPEC.md, CONVERSATION-FLOWS.md
