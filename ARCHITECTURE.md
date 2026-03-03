# AI Voice Caller - Architecture Design
**Purpose:** Multi-use case AI voice caller for SLED prospecting  
**Google Cloud Project:** tatt-pro  
**Target Use Cases:** Cold calling, follow-ups, appointment setting, lead qualification, information delivery

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Phone Network (PSTN)                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              Telephony Provider (Twilio/SignalWire)              │
│  - Phone number provisioning                                     │
│  - SIP trunk to Google Cloud                                     │
│  - Call routing & webhooks                                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Google Dialogflow CX                           │
│  - Conversation flow engine                                      │
│  - Intent recognition                                            │
│  - Context management                                            │
│  - Multi-use case routing                                        │
└──────┬──────────────────┬────────────────┬─────────────────────┘
       │                  │                │
       ▼                  ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Speech-to-   │  │ Text-to-     │  │ Vertex AI    │
│ Text API     │  │ Speech API   │  │ Gemini       │
│              │  │              │  │              │
│ (Listens)    │  │ (Speaks)     │  │ (Thinks)     │
└──────────────┘  └──────────────┘  └──────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend Services                            │
│  - Lead database (Firestore/BigQuery)                           │
│  - Salesforce integration (create tasks, log calls)             │
│  - Calendar integration (book meetings)                          │
│  - Call recording & transcription storage                        │
│  - Analytics & reporting                                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Telephony Provider: SignalWire (Recommended)
**Why SignalWire over Twilio:**
- Built on FreeSWITCH (open source)
- Lower cost ($0.0085/min vs. Twilio $0.013/min)
- Better programmability
- Native SIP support

**What it does:**
- Provides phone number(s) for outbound calling
- Routes calls to Dialogflow CX via SIP or webhook
- Handles DTMF (keypad input)
- Records calls (optional)

**Cost:**
- Phone number: ~$1/month
- Outbound calls: $0.0085/minute
- 100 calls × 3 min avg = 300 min/month = **$2.55/month**

---

### 2. Google Dialogflow CX (Conversation Engine)
**Why Dialogflow CX:**
- Designed for phone bots (not just chatbots)
- Multi-flow support (5 use cases in one agent)
- Built-in Speech-to-Text & Text-to-Speech integration
- Context management (remembers conversation state)
- Webhook support (call your backend for data/logic)

**What it does:**
- Recognizes what the caller is saying (intent detection)
- Routes to appropriate conversation flow (cold call vs. follow-up)
- Manages conversation state (where are we in the flow?)
- Calls Gemini for smart, contextual responses
- Speaks responses via Text-to-Speech

**Cost:**
- Text requests: $0.002 per request (avg 10 requests per call = $0.02/call)
- Audio requests (phone): $0.06 per request (avg 10 = $0.60/call)
- 100 calls/month = **$62/month**

---

### 3. Vertex AI Gemini (Smart Responses)
**Why use Gemini:**
- Dialogflow handles structured flows (yes/no, menu options)
- Gemini handles unstructured responses ("Tell me more about that...")
- Gemini can adapt to objections, questions, curveballs

**What it does:**
- When caller says something unexpected → Gemini generates smart response
- Personalizes responses based on caller's account data
- Handles objections ("We're not interested" → Gemini crafts polite pivot)
- Generates follow-up questions based on conversation

**Cost:**
- Gemini Flash: $0.002 per 1K tokens (avg 500 tokens/call = $0.001/call)
- 100 calls/month = **$0.10/month**

---

### 4. Speech-to-Text API (Listens)
**What it does:**
- Converts caller's voice to text in real-time
- Detects when caller stops speaking (pause detection)
- Handles accents, background noise, phone quality

**Included in Dialogflow CX pricing** (no separate charge when using Dialogflow phone gateway)

---

### 5. Text-to-Speech API (Speaks)
**What it does:**
- Converts bot's text responses to natural-sounding voice
- Neural2 voices (very realistic)
- SSML support (pauses, emphasis, prosody)

**Voice recommendation:**
- Male: `en-US-Neural2-D` or `en-US-Neural2-J`
- Female: `en-US-Neural2-F` or `en-US-Neural2-C`
- Studio voices (even more realistic): `en-US-Studio-O` (male), `en-US-Studio-Q` (female)

**Cost:**
- Neural2: $0.000016 per character (avg 500 chars/response × 10 responses = 5K chars = $0.08/call)
- Studio: $0.000160 per character (10x more expensive but ultra-realistic)
- 100 calls/month (Neural2) = **$8/month**

---

### 6. Backend Services (Custom)

**Firestore (Call Log & Lead Database):**
- Store call transcripts
- Track call outcomes (interested, not interested, callback, booked meeting)
- Lead scoring based on responses
- **Cost:** Free tier covers this easily

**Salesforce Integration:**
- Create task after call ("Follow up with [account]")
- Log call activity on opportunity
- Update lead status based on call outcome
- **Built via webhook from Dialogflow**

**Calendar Integration (Google Calendar API):**
- When caller agrees to meeting → check your availability
- Book meeting automatically
- Send calendar invite
- **Cost:** Free (Google Calendar API)

**BigQuery (Analytics):**
- Call volume by day/time
- Success rate by use case
- Objection frequency
- Conversion metrics
- **Cost:** ~$5/month for storage + queries

---

## Total Monthly Cost Estimate

| Component | Cost |
|-----------|------|
| SignalWire (100 calls × 3 min) | $2.55 |
| Dialogflow CX (100 calls) | $62.00 |
| Gemini Flash (100 calls) | $0.10 |
| Text-to-Speech Neural2 (100 calls) | $8.00 |
| Firestore (call logs) | $0 (free tier) |
| BigQuery (analytics) | $5.00 |
| **Total** | **$77.65/month** |

**At scale (500 calls/month):** ~$350/month

---

## 5 Use Case Flows

### Use Case 1: Cold Calling (Qualify Interest)

**Goal:** Introduce Fortinet, ask killer question, gauge interest, book meeting or send info

**Conversation Flow:**
```
Bot: "Hi, is this [Name]?"
Caller: "Yes, who's this?"

Bot: "This is Paul calling from Fortinet. I work with IT leaders in 
     [state] on voice and network solutions. Quick question: what 
     happens to your phones when the internet goes down?"

Caller: [Response]
  
  Option A - They have an answer:
    Bot: "Got it. Are you happy with that setup, or is it something 
         you'd want to improve?"
  
  Option B - They don't know:
    Bot: "That's a common gap. Most districts/cities don't realize 
         their phones are internet-dependent until an outage hits. 
         Would you be open to a 15-minute call to discuss local 
         survivability options?"
  
  Option C - Not interested:
    Bot: "Totally understand. Can I ask - is voice system 
         modernization on your roadmap for this year or next?"
    
    If still no:
      Bot: "No problem. Can I send you a quick overview in case 
           priorities change? Just your email."

Outcomes:
✅ Interested → Book meeting (transfer to Use Case 3)
✅ Maybe → Send info (get email, mark as warm lead)
❌ Not interested → Log outcome, ask permission to follow up in 6 months
```

---

### Use Case 2: Follow-Up Calls (After Email)

**Goal:** Confirm they got email, gauge interest, book meeting

**Conversation Flow:**
```
Bot: "Hi [Name], this is Paul from Fortinet. I sent you an email 
     last week about [topic - voice modernization / FortiVoice]. 
     Did you get a chance to look at it?"

Caller: [Response]

  Option A - Yes, read it:
    Bot: "Great! What did you think? Any questions I can answer?"
  
  Option B - No, didn't see it:
    Bot: "No worries, inboxes are crazy. Quick summary: we're helping 
         [schools/cities] in [state] with [pain point they mentioned]. 
         Would it be worth a 15-minute call to explore if it fits 
         your situation?"
  
  Option C - Not interested:
    Bot: "Understood. Can I ask - is there a better time to revisit 
         this? Maybe when your current contract renews?"

Outcomes:
✅ Interested → Book meeting
✅ Need more info → Offer to send different resource (case study, pricing)
⏰ Not now → Schedule callback for later date
```

---

### Use Case 3: Appointment Setting (Book Demo)

**Goal:** Schedule meeting with you or partner (High Point Networks)

**Conversation Flow:**
```
Bot: "Sounds like this could be a fit. Would you be open to a 
     15-minute call with our partner High Point Networks? They can 
     walk through how this works and answer technical questions."

Caller: "Sure, when?"

Bot: "Let me check availability. Are mornings or afternoons better 
     for you?"

Caller: "Mornings."

Bot: "Perfect. How about [next available morning slot from your calendar]?"

Caller: "That works."

Bot: "Great! I'll send you a calendar invite to [their email - ask if 
     you don't have it]. You'll get a confirmation email with a Teams/Zoom 
     link. Anything else I can help with before we wrap up?"

Outcomes:
✅ Meeting booked → Create Salesforce task, send calendar invite
❌ Can't commit to time → Offer to send scheduling link
```

---

### Use Case 4: Lead Qualification (Discovery Questions)

**Goal:** Ask discovery questions, score lead, determine next steps

**Conversation Flow:**
```
Bot: "Before we schedule something, let me ask a few quick questions 
     to make sure we're focusing on the right solution for you. 
     Sound good?"

Caller: "Sure."

Bot: "First, what phone system are you running today?"

Caller: [Response - Cisco / cloud / Avaya / etc.]

Bot: "Got it. And how many users do you have across all locations?"

Caller: [Response]

Bot: "Perfect. Last question - are you planning any changes to your 
     voice system in the next 6-12 months?"

Caller: [Response]

Bot: "Based on what you've shared, I think there's definitely a fit 
     here. [Personalized recommendation based on their answers]. 
     Would you like to schedule a quick call to dive deeper?"

Lead Scoring:
- System >5 years old: +2 points
- 25+ users: +2 points
- Planning changes within 12 months: +3 points
- Mentioned pain points: +2 points

Score ≥5 → Hot lead, book meeting immediately
Score 3-4 → Warm lead, send info + follow up in 2 weeks
Score <3 → Cold lead, nurture drip campaign

Outcomes:
✅ Hot lead → Book meeting
⏰ Warm lead → Send info, schedule follow-up
📧 Cold lead → Add to nurture list
```

---

### Use Case 5: Information Delivery (Quick Announcements)

**Goal:** Deliver specific information (new product launch, event invite, contract renewal reminder)

**Conversation Flow:**
```
Bot: "Hi [Name], this is a quick call from Fortinet. I wanted to let 
     you know about [specific information]:
     
     Option A - Product launch:
       'FortiOS 8.0 launches next month with agentic AI security. 
        If you're interested in seeing a preview, we're hosting a 
        webinar on [date]. Would you like me to send you the link?'
     
     Option B - Contract renewal:
       'Your FortiGate support contract expires on [date]. I wanted 
        to reach out early so you have time to budget for renewal. 
        Should I have our partner send you a quote?'
     
     Option C - Event invitation:
       'We're hosting a SLED roundtable in [city] on [date] to discuss 
        [topic]. Several IT directors from [nearby districts/cities] 
        are attending. Would you be interested in joining?'

Caller: [Response]

Bot: "Great! I'll [send link / have partner reach out / register you]. 
     Anything else I can help with today?"

Outcomes:
✅ Accepted → Take action (send link, create task, register)
❌ Declined → Log outcome, ask permission to follow up later
```

---

## Conversation Design Principles

### 1. Keep It Conversational (Not Robotic)
**Bad:** "Hello. This is an automated call from Fortinet Corporation regarding network security solutions."  
**Good:** "Hi, is this [Name]? This is Paul from Fortinet. Quick question for you..."

### 2. Ask Permission Early
**Example:** "Is this a good time for a quick question?" or "Do you have 2 minutes?"  
**Why:** Gives caller control, reduces hang-ups

### 3. Use The Killer Question
**For voice calls:** "What happens to your phones when the internet goes down?"  
**Why:** Uncovers gaps, creates urgency

### 4. Handle Objections Gracefully
**Objection:** "We're not interested."  
**Response:** "Totally understand. Can I ask - is it not a fit right now, or not a fit ever? Just so I know whether to check back later."

**Objection:** "Just send me an email."  
**Response:** "Happy to! What email should I use? And anything specific you'd like me to focus on?"

### 5. Always Offer Value Before Asking
**Bad:** "Can we schedule a meeting?"  
**Good:** "Based on what you said about [pain point], I think there's a way to [solve it]. Would a 15-minute call to explore that be worth your time?"

### 6. Natural Pauses & Pacing
**Use SSML (Speech Synthesis Markup Language):**
```xml
<speak>
  Hi, is this <break time="300ms"/> John?
  <break time="500ms"/>
  This is Paul from Fortinet.
  <emphasis level="moderate">Quick question</emphasis> for you...
</speak>
```

### 7. Detect & Adapt to Tone
**If caller sounds rushed:**
→ "I can hear you're busy. Want me to call back later, or can I ask one quick question?"

**If caller sounds curious:**
→ "I can tell this might be interesting to you. Want me to go deeper, or should I send you something to review?"

**How:** Use Gemini to analyze tone from transcript, adjust response

---

## Technical Implementation

### Phase 1: Setup (Week 1)
1. **Google Cloud setup:**
   - Enable Dialogflow CX API
   - Enable Speech-to-Text API
   - Enable Text-to-Speech API
   - Enable Vertex AI API
   - Create service account with permissions

2. **SignalWire account:**
   - Sign up: signalwire.com
   - Purchase phone number ($1/month)
   - Configure SIP trunk to Dialogflow

3. **Dialogflow CX agent:**
   - Create agent: "Fortinet SLED Voice Caller"
   - Configure phone gateway (connect to SignalWire)
   - Set up default start flow

### Phase 2: Build Flows (Week 2)
1. **Create 5 main flows:**
   - Flow 1: Cold Calling
   - Flow 2: Follow-Up
   - Flow 3: Appointment Setting
   - Flow 4: Lead Qualification
   - Flow 5: Information Delivery

2. **Define intents for each flow:**
   - Yes/No responses
   - Time preferences
   - Objections
   - Questions
   - Hang-up detection

3. **Write fulfillment webhooks:**
   - Check calendar availability
   - Create Salesforce tasks
   - Score leads
   - Send emails

### Phase 3: Gemini Integration (Week 2-3)
1. **Set up Vertex AI Gemini endpoint:**
   - Create Cloud Function (Node.js or Python)
   - Accept webhook from Dialogflow
   - Call Gemini API with conversation context
   - Return smart response

2. **Context injection:**
   - Pass account data to Gemini (company name, current system, pain points)
   - Pass conversation history
   - Pass current goal (qualify, book meeting, etc.)

3. **Response generation:**
   - Gemini generates contextual response
   - Format for Text-to-Speech (remove special characters)
   - Return to Dialogflow

### Phase 4: Backend Services (Week 3-4)
1. **Firestore setup:**
   - Collection: `calls`
   - Fields: timestamp, caller_id, account_name, use_case, outcome, transcript, lead_score
   
2. **Salesforce integration:**
   - Webhook to create tasks
   - Update opportunity/lead status
   - Log call activity

3. **Calendar integration:**
   - Google Calendar API
   - Check availability
   - Create events
   - Send invites

4. **BigQuery analytics:**
   - Stream call logs from Firestore
   - Create dashboards (Data Studio)
   - Track success metrics

### Phase 5: Testing & Refinement (Week 4)
1. **Internal testing:**
   - Call yourself
   - Test all 5 use cases
   - Verify Salesforce integration
   - Check calendar booking

2. **Pilot with 10 accounts:**
   - Low-risk accounts
   - Monitor transcripts
   - Identify failure points
   - Refine responses

3. **Optimize:**
   - Improve voice (maybe switch to Studio quality)
   - Tune intent recognition
   - Adjust conversation flows based on real data

### Phase 6: Launch (Week 5)
1. **Batch calling:**
   - Upload 50-100 leads
   - Schedule calls (mornings 9-11am)
   - Monitor results real-time

2. **Daily review:**
   - Check call outcomes
   - Listen to flagged calls
   - Adjust scripts

3. **Scale:**
   - Increase call volume
   - Add more phone numbers if needed
   - Expand to new use cases

---

## Code Architecture

### Directory Structure
```
ai-voice-caller/
├── dialogflow-agent/
│   ├── flows/
│   │   ├── cold-calling.json
│   │   ├── follow-up.json
│   │   ├── appointment-setting.json
│   │   ├── lead-qualification.json
│   │   └── information-delivery.json
│   ├── intents/
│   ├── entities/
│   └── webhooks/
│
├── cloud-functions/
│   ├── gemini-responder/
│   │   ├── index.js
│   │   ├── package.json
│   │   └── config.json
│   │
│   ├── salesforce-integration/
│   │   ├── index.js
│   │   └── sf-api.js
│   │
│   └── calendar-booking/
│       ├── index.js
│       └── google-calendar.js
│
├── backend/
│   ├── firestore-schema.json
│   ├── bigquery-schema.json
│   └── analytics-queries.sql
│
├── scripts/
│   ├── deploy-dialogflow.sh
│   ├── deploy-cloud-functions.sh
│   ├── batch-call.py
│   └── test-call.py
│
├── config/
│   ├── signalwire.json
│   ├── dialogflow.json
│   └── salesforce.json
│
└── docs/
    ├── ARCHITECTURE.md (this file)
    ├── CONVERSATION-FLOWS.md
    ├── API-REFERENCE.md
    └── TROUBLESHOOTING.md
```

---

## Success Metrics

### Call Quality Metrics
- **Completion rate:** % of calls that don't hang up immediately
- **Conversation length:** Avg time per call (target: 2-4 minutes)
- **Intent recognition accuracy:** % of responses correctly understood
- **Hang-up rate:** % of calls where caller hangs up (target: <50%)

### Business Metrics
- **Lead qualification rate:** % of calls that produce qualified lead
- **Meeting booking rate:** % of calls that result in scheduled meeting
- **Conversion rate:** % of calls that advance opportunity
- **Cost per qualified lead:** Total spend / qualified leads

### Technical Metrics
- **Latency:** Time from caller stops speaking to bot responds (target: <2 seconds)
- **Gemini fallback rate:** % of times Dialogflow couldn't handle response
- **Error rate:** % of calls with technical failures
- **Uptime:** % of time system is available

---

## Risk Mitigation

### Risk 1: Caller Immediately Hangs Up
**Mitigation:**
- Lead with value in first 5 seconds
- Use conversational tone (not robotic)
- Ask permission early ("Do you have 2 minutes?")

### Risk 2: Bot Doesn't Understand Caller
**Mitigation:**
- Gemini fallback for unstructured responses
- Clarification prompts ("Did you say [X] or [Y]?")
- Escalation path ("I didn't catch that. Can I have someone call you back?")

### Risk 3: Caller Asks Complex Question
**Mitigation:**
- Gemini generates answer if possible
- Offer to send detailed info via email
- Schedule callback with you for complex questions

### Risk 4: Legal/Compliance (TCPA, Do Not Call)
**Mitigation:**
- Only call B2B contacts (TCPA exempt)
- Honor opt-outs immediately
- Keep Do Not Call list in Firestore
- Include opt-out option in every call ("If you'd prefer not to receive calls, just say 'opt out'")

### Risk 5: High Cost if Bot Goes Haywire
**Mitigation:**
- Set daily call limit (max 100 calls/day)
- Monitor costs in real-time (Cloud Billing alerts)
- Manual approval for batches >50 calls
- Kill switch (disable Dialogflow agent instantly)

---

## Next Steps

1. **Confirm use case priority:** Which of the 5 should we build first?
2. **Get SignalWire account:** $1/month phone number
3. **Enable Google Cloud APIs:** Dialogflow CX, Speech, Vertex AI
4. **Build first flow:** Start with Use Case 1 (Cold Calling)
5. **Test with real calls:** Call yourself, test conversation
6. **Pilot with 10 accounts:** Low-risk testing
7. **Scale to 50-100 calls:** Full production

**Time to launch:** 4-6 weeks  
**Monthly cost (100 calls):** ~$80  
**Monthly cost (500 calls):** ~$350  

Ready to build this? 🤖📞
