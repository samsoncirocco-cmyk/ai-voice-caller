# AI Voice Caller - Requirements Specification

**Version:** 1.0  
**Date:** 2026-02-11  
**Status:** Design Complete → Implementation Phase  

---

## Table of Contents
1. [Overview](#1-overview)
2. [System Requirements](#2-system-requirements)
3. [Flow 1: Cold Calling](#3-flow-1-cold-calling)
4. [Flow 2: Follow-Up Calls](#4-flow-2-follow-up-calls)
5. [Flow 3: Appointment Setting](#5-flow-3-appointment-setting)
6. [Flow 4: Lead Qualification](#6-flow-4-lead-qualification)
7. [Integration Requirements](#7-integration-requirements)
8. [Data Requirements](#8-data-requirements)
9. [Quality Requirements](#9-quality-requirements)
10. [Success Criteria](#10-success-criteria)

---

## 1. Overview

### 1.1 Purpose
Build 4 additional conversation flows for the AI Voice Caller to enable complete sales rep automation:
- Cold Calling
- Follow-Up Calls
- Appointment Setting
- Lead Qualification

### 1.2 Scope
**In Scope:**
- Dialogflow CX flow creation and deployment
- Intent and entity configuration
- Basic webhook integration
- Firestore data logging
- End-to-end call testing

**Out of Scope (Future Phases):**
- Advanced Gemini AI responses (basic fallback only)
- Salesforce integration (manual data entry acceptable)
- Real-time analytics dashboard (Firestore console acceptable)
- Automated retry logic (manual retry acceptable)

### 1.3 Success Definition
A flow is "complete" when:
1. Deployed to Dialogflow CX
2. Test call completes successfully
3. All conversation paths tested
4. Data logged to Firestore
5. No critical bugs found

---

## 2. System Requirements

### 2.1 Technical Prerequisites
- [x] Dialogflow CX agent created ("Fortinet-SLED-Caller")
- [x] Google Cloud Project configured (tatt-pro)
- [x] SignalWire phone number active (+1 602-898-5026)
- [x] Firestore database created
- [ ] Cloud Functions deployed (gemini-responder, call-logger)
- [ ] SignalWire webhook configured

### 2.2 Development Environment
- **Python:** 3.12+ with venv
- **Required Packages:**
  - google-cloud-dialogflow-cx (>=1.47.0)
  - google-cloud-firestore
  - signalwire-community (for testing)
- **GCP Auth:** Application Default Credentials configured
- **Region:** us-central1 (must match agent location)

### 2.3 Configuration Files
- [x] config/signalwire.json (credentials)
- [x] config/dialogflow-agent.json (agent metadata)
- [x] config/agent-name.txt (agent resource name)
- [x] config/firestore-schema.json (database schema)
- [ ] config/flows-deployed.json (deployment tracking)

---

## 3. Flow 1: Cold Calling

### 3.1 Functional Requirements

**Primary Goal:** Introduce Fortinet, qualify interest, schedule follow-up or meeting.

**Conversation Flow:**
1. **Greeting** → Introduce self, ask for decision maker
2. **Gatekeeper Handling** → If gatekeeper, request transfer or get contact info
3. **Decision Maker Pitch** → Brief value proposition (30 seconds)
4. **Interest Assessment** → Gauge interest, capture pain points
5. **Objection Handling** → Address common objections
6. **Next Step Agreement** → Schedule call/meeting or send info
7. **Confirmation** → Recap agreed actions
8. **End Call** → Thank and disconnect

**Required Pages (9):**
- Page 1: Greeting
- Page 2: Ask for Decision Maker
- Page 3: Gatekeeper Route (get info or transfer)
- Page 4: Decision Maker Pitch
- Page 5: Interest Assessment
- Page 6: Objection Handling
- Page 7: Next Step Proposal
- Page 8: Confirmation
- Page 9: End Call

**Required Intents:**
- `greeting.respond` - Handle greetings
- `decision_maker.available` - Decision maker on line
- `decision_maker.unavailable` - Gatekeeper scenario
- `interest.high` - Prospect is interested
- `interest.low` - Prospect not interested
- `objection.price` - Price concerns
- `objection.timing` - Bad timing
- `objection.satisfied` - Happy with current solution
- `meeting.agree` - Wants to schedule meeting
- `meeting.decline` - Doesn't want meeting
- `send_info.request` - Wants information sent
- `call_back.request` - Wants callback later

**Required Entities:**
- `@decision_maker` - IT Director, CTO, CIO, Tech Coordinator
- `@confirmation` - yes, no, maybe
- `@objection_type` - price, timing, satisfaction, authority
- `@next_step` - meeting, call, email, nothing

**Required Session Parameters:**
```json
{
  "account_name": "string",
  "contact_name": "string",
  "contact_title": "string",
  "is_decision_maker": "boolean",
  "interest_level": "high|medium|low|none",
  "pain_points": ["array", "of", "strings"],
  "objections": ["array", "of", "objections"],
  "next_step": "meeting|call|email|none",
  "meeting_scheduled": "boolean",
  "callback_date": "string (ISO 8601)",
  "email_sent": "boolean"
}
```

**Required Webhooks:**
- `gemini-responder` - When intent confidence <0.6
- `call-logger` - On call end

### 3.2 Builder Script Requirements

**Script Name:** `scripts/create-cold-calling-flow.py`

**Must Include:**
- Load agent name from config/agent-name.txt
- Create flow "cold-calling" if not exists
- Create all 9 pages with proper routes
- Configure TTS voice (en-US-Neural2-J)
- Add entry fulfillments with conversation scripts
- Configure intent routes between pages
- Add webhook calls at key decision points
- Handle errors and provide clear output
- Save flow name to config/cold-calling-flow-name.txt

**Testing Commands:**
```bash
# Deploy flow
python3 scripts/create-cold-calling-flow.py

# Test with call
python3 scripts/make-test-call.py --flow cold-calling --number +16022950104
```

---

## 4. Flow 2: Follow-Up Calls

### 4.1 Functional Requirements

**Primary Goal:** Re-engage prospect after initial contact, move conversation forward.

**Conversation Flow:**
1. **Context Check** → "We spoke last week about..."
2. **Progress Update** → "Have you had a chance to review?"
3. **Answer Questions** → Address any concerns
4. **Next Step Proposal** → Meeting, demo, or another touchpoint
5. **Confirmation** → Agree on next action
6. **End Call** → Thank and disconnect

**Required Pages (6):**
- Page 1: Context Reminder
- Page 2: Progress Check
- Page 3: Question Handling
- Page 4: Next Step Proposal
- Page 5: Confirmation
- Page 6: End Call

**Required Intents:**
- `follow_up.context_confirmed` - Prospect remembers previous conversation
- `follow_up.context_forgot` - Prospect doesn't remember
- `progress.reviewed` - Looked at materials
- `progress.not_reviewed` - Haven't looked yet
- `question.ask` - Has questions
- `next_step.agree` - Agrees to next step
- `next_step.decline` - Not ready for next step

**Required Session Parameters:**
```json
{
  "account_name": "string",
  "contact_name": "string",
  "previous_call_date": "string (ISO 8601)",
  "previous_outcome": "string",
  "materials_sent": "boolean",
  "materials_reviewed": "boolean",
  "questions_asked": ["array"],
  "next_step": "meeting|demo|call|email|none",
  "follow_up_date": "string (ISO 8601)"
}
```

**Required Webhooks:**
- `gemini-responder` - For question answering
- `call-logger` - On call end

### 4.2 Builder Script Requirements

**Script Name:** `scripts/create-follow-up-flow.py`

**Must Include:**
- Create flow "follow-up" with 6 pages
- Load previous call context from Firestore (webhook)
- Configure dynamic greetings based on context
- Handle "doesn't remember" scenario gracefully
- Capture questions and answer attempts
- Propose relevant next steps based on conversation
- Log outcome to Firestore

---

## 5. Flow 3: Appointment Setting

### 5.1 Functional Requirements

**Primary Goal:** Schedule a specific meeting time with qualified prospect.

**Conversation Flow:**
1. **Purpose Confirmation** → "You mentioned wanting to discuss..."
2. **Availability Check** → "Are you available next week?"
3. **Suggest Times** → Offer 2-3 specific slots
4. **Alternate Handling** → If none work, ask for their availability
5. **Calendar Integration** → Book meeting (webhook)
6. **Confirmation** → Send calendar invite
7. **End Call** → Thank and disconnect

**Required Pages (7):**
- Page 1: Purpose Confirmation
- Page 2: Availability Inquiry
- Page 3: Suggest Times
- Page 4: Alternate Time Handling
- Page 5: Calendar Booking
- Page 6: Confirmation
- Page 7: End Call

**Required Intents:**
- `appointment.purpose_confirmed` - Confirms reason for meeting
- `availability.available` - Has availability
- `availability.unavailable` - No availability
- `time_slot.accept` - Accepts suggested time
- `time_slot.reject` - Rejects suggested time
- `time_slot.suggest` - Suggests their own time

**Required Entities:**
- `@date` - System date entity
- `@time` - System time entity
- `@duration` - 30min, 1hr, etc.

**Required Session Parameters:**
```json
{
  "account_name": "string",
  "contact_name": "string",
  "contact_email": "string",
  "meeting_purpose": "string",
  "suggested_times": ["array", "of", "datetime"],
  "selected_time": "string (ISO 8601)",
  "meeting_duration": "number (minutes)",
  "calendar_invite_sent": "boolean",
  "calendar_event_id": "string"
}
```

**Required Webhooks:**
- `calendar-availability` - Check available slots
- `calendar-book` - Create calendar event
- `call-logger` - On call end

### 5.2 Builder Script Requirements

**Script Name:** `scripts/create-appointment-setting-flow.py`

**Must Include:**
- Create flow "appointment-setting" with 7 pages
- Integrate calendar availability webhook
- Handle timezone conversions (America/Phoenix)
- Suggest 2-3 specific times (not vague "next week")
- Capture alternate times if suggested slots don't work
- Book meeting and send calendar invite via webhook
- Handle booking failures gracefully
- Confirm meeting details before hanging up

---

## 6. Flow 4: Lead Qualification

### 6.1 Functional Requirements

**Primary Goal:** Assess lead quality using BANT criteria (Budget, Authority, Need, Timeline).

**Conversation Flow:**
1. **Needs Assessment** → What are your current challenges?
2. **Budget Inquiry** → Do you have budget allocated?
3. **Authority Check** → Are you the decision maker?
4. **Timeline Discussion** → When are you looking to implement?
5. **Current System** → What are you using now?
6. **Score Calculation** → (Webhook calculates lead score)
7. **Next Step Routing** → High score → meeting, Low score → nurture
8. **End Call** → Thank and disconnect

**Required Pages (8):**
- Page 1: Needs Assessment
- Page 2: Budget Inquiry
- Page 3: Authority Check
- Page 4: Timeline Discussion
- Page 5: Current System Discovery
- Page 6: Lead Score Calculation
- Page 7: Next Step Routing
- Page 8: End Call

**Required Intents:**
- `needs.express` - Describes pain points
- `needs.none` - No current needs
- `budget.allocated` - Has budget
- `budget.not_allocated` - No budget
- `authority.decision_maker` - Is decision maker
- `authority.influencer` - Is influencer, not decision maker
- `timeline.immediate` - Needs solution now (<3 months)
- `timeline.future` - Needs solution later (>3 months)
- `timeline.none` - No timeline

**Required Entities:**
- `@budget_range` - <10k, 10k-50k, 50k-100k, >100k
- `@timeline_period` - immediate, short-term, long-term
- `@pain_point` - security, budget, complexity, staffing

**Required Session Parameters:**
```json
{
  "account_name": "string",
  "contact_name": "string",
  "contact_title": "string",
  "needs": ["array", "of", "pain_points"],
  "budget_status": "allocated|not_allocated|unknown",
  "budget_range": "string",
  "authority_level": "decision_maker|influencer|gatekeeper",
  "timeline": "immediate|short_term|long_term|none",
  "current_system": "string",
  "lead_score": "number (0-100)",
  "qualification_status": "qualified|nurture|disqualified",
  "next_action": "meeting|follow_up|email|none"
}
```

**Required Webhooks:**
- `lead-scorer` - Calculate score based on BANT
- `salesforce-update` - Create/update lead (optional)
- `call-logger` - On call end with full qualification data

### 6.2 Builder Script Requirements

**Script Name:** `scripts/create-lead-qualification-flow.py`

**Must Include:**
- Create flow "lead-qualification" with 8 pages
- Ask BANT questions naturally (not interrogation)
- Handle "don't know" or "prefer not to say" gracefully
- Calculate lead score via webhook
- Route to appropriate next step based on score:
  - High (70+) → Schedule meeting
  - Medium (40-69) → Schedule follow-up
  - Low (<40) → Email materials, nurture sequence
- Log detailed qualification data to Firestore

---

## 7. Integration Requirements

### 7.1 SignalWire Integration

**Requirements:**
- Configure webhook URL in SignalWire dashboard
- Map phone number (+1 602-898-5026) to Dialogflow endpoint
- Handle SIP/voice → text conversion
- Stream audio to Dialogflow CX Speech-to-Text
- Receive Dialogflow responses and play via TTS
- Log call metadata (duration, cost, SIP details)

**Webhook Endpoint:**
```
POST https://us-central1-tatt-pro.cloudfunctions.net/dialogflow-voice-gateway
```

**Payload:**
```json
{
  "call_sid": "string",
  "from_number": "string",
  "to_number": "string",
  "audio_stream_url": "string"
}
```

### 7.2 Dialogflow CX Webhook Integration

**Webhooks to Deploy:**

1. **gemini-responder**
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/gemini-responder`
   - Trigger: Low-confidence intent match (<0.6)
   - Timeout: 5 seconds
   - Payload: Session parameters + user text
   - Response: Dynamic fulfillment text

2. **call-logger**
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/call-logger`
   - Trigger: Call end (all flows)
   - Timeout: 3 seconds
   - Payload: All session parameters
   - Response: Success confirmation

3. **calendar-availability** (appointment-setting only)
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/calendar-availability`
   - Trigger: When asking for availability
   - Timeout: 3 seconds
   - Response: Available time slots

4. **calendar-book** (appointment-setting only)
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/calendar-book`
   - Trigger: When time is confirmed
   - Timeout: 5 seconds
   - Response: Calendar event ID + invite sent confirmation

5. **lead-scorer** (lead-qualification only)
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/lead-scorer`
   - Trigger: After BANT questions
   - Timeout: 2 seconds
   - Response: Lead score (0-100) + qualification status

### 7.3 Firestore Integration

**Collections:**

1. **calls** (call-level data)
   ```json
   {
     "call_id": "string",
     "phone_number": "string",
     "account_name": "string",
     "flow_name": "string",
     "start_time": "timestamp",
     "end_time": "timestamp",
     "duration_seconds": "number",
     "outcome": "string",
     "next_action": "string",
     "created_at": "timestamp"
   }
   ```

2. **contacts** (contact info discovered)
   ```json
   {
     "contact_id": "string (auto-generated)",
     "account_name": "string",
     "contact_name": "string",
     "title": "string",
     "phone": "string",
     "email": "string",
     "is_decision_maker": "boolean",
     "last_contact_date": "timestamp",
     "total_calls": "number",
     "lead_score": "number",
     "qualification_status": "string",
     "created_at": "timestamp",
     "updated_at": "timestamp"
   }
   ```

3. **conversations** (turn-by-turn transcripts)
   ```json
   {
     "conversation_id": "string",
     "call_id": "string (foreign key)",
     "turns": [
       {
         "speaker": "bot|user",
         "text": "string",
         "timestamp": "timestamp",
         "intent": "string",
         "confidence": "number"
       }
     ]
   }
   ```

---

## 8. Data Requirements

### 8.1 Input Data
**For each call, must provide:**
- `account_name` - School/district name
- `main_phone` - Phone number to call
- `flow_name` - Which flow to use (cold-calling, follow-up, etc.)

**Optional:**
- `contact_name` - If known from previous call
- `contact_title` - If known
- `previous_call_date` - For follow-up flows
- `notes` - Additional context

### 8.2 Output Data
**After each call, must capture:**
- Call metadata (duration, cost, timestamp)
- Contact information (name, title, phone, email)
- Conversation transcript (full turn-by-turn)
- Intent matches and confidence scores
- Next action (meeting scheduled, follow-up needed, etc.)
- Lead score (if qualification flow)

### 8.3 Data Validation
**Before making call:**
- Phone number is E.164 format (+16022950104)
- Account name exists and is not empty
- Flow name is valid

**After call ends:**
- At least one contact name captured
- Outcome is one of: qualified, follow-up, disqualified, no-answer
- Next action is recorded

---

## 9. Quality Requirements

### 9.1 Performance
- **Response Latency:** <1.5 seconds from user speech end to bot response start
- **TTS Quality:** Clear, professional male voice (en-US-Neural2-J)
- **Speech Recognition:** >95% accuracy for clear English speech
- **Call Setup:** <3 seconds from dial to first greeting

### 9.2 Reliability
- **Uptime:** >99% (Dialogflow CX SLA)
- **Error Handling:** All errors caught and logged
- **Graceful Degradation:** If webhook fails, continue with default response
- **Retry Logic:** Webhooks retry up to 3 times with exponential backoff

### 9.3 Usability
- **Natural Conversation:** Sounds human, not robotic
- **Interrupt Handling:** Allows user to interrupt bot
- **Clarification:** Asks for clarification if input unclear
- **Politeness:** Always professional, never pushy

### 9.4 Security
- **Credentials:** No hardcoded secrets (use environment variables)
- **Data Privacy:** Log only necessary PII (no full credit cards, SSNs)
- **Access Control:** Firestore rules restrict data access
- **Audit Trail:** All calls logged with timestamps

---

## 10. Success Criteria

### 10.1 Flow Deployment Success
A flow is "successfully deployed" when:
- [x] Flow exists in Dialogflow CX agent
- [x] All pages created with correct routes
- [x] All intents configured and training phrases added
- [x] All entities created
- [x] TTS voice configured on all pages
- [x] Webhooks configured (even if not implemented yet)
- [x] Flow accessible via API

### 10.2 Flow Testing Success
A flow is "successfully tested" when:
- [ ] Test call completes without errors
- [ ] All conversation paths reachable
- [ ] Intent matching accuracy >80%
- [ ] Data logged to Firestore correctly
- [ ] Webhook calls succeed (or fail gracefully)
- [ ] End-to-end latency <2 seconds

### 10.3 System Integration Success
System is "successfully integrated" when:
- [ ] SignalWire → Dialogflow webhook working
- [ ] Phone call triggers correct flow
- [ ] Audio quality acceptable (clear, no distortion)
- [ ] Conversation feels natural (not robotic)
- [ ] Data flows to Firestore correctly
- [ ] At least 3 successful test calls completed

### 10.4 Production Readiness
System is "production ready" when:
- [ ] All 5 flows deployed and tested
- [ ] All critical webhooks implemented
- [ ] SignalWire integration validated
- [ ] Firestore schema validated
- [ ] Error handling tested
- [ ] Cost per call measured and acceptable (<$0.10)
- [ ] No critical bugs found in last 10 test calls
- [ ] Documentation complete

---

## Acceptance Criteria

### Phase 1: Flow Deployment (4-6 hours)
- [ ] `create-cold-calling-flow.py` created and tested
- [ ] `create-follow-up-flow.py` created and tested
- [ ] `create-appointment-setting-flow.py` created and tested
- [ ] `create-lead-qualification-flow.py` created and tested
- [ ] All 4 flows deployed to Dialogflow CX
- [ ] All flow names saved to config files

### Phase 2: Basic Testing (2-3 hours)
- [ ] Each flow tested with `make-test-call.py`
- [ ] Intent matching validated
- [ ] Conversation paths tested
- [ ] Error handling verified
- [ ] No critical bugs found

### Phase 3: Integration (3-4 hours)
- [ ] SignalWire webhook configured
- [ ] Live phone call tested (each flow)
- [ ] Audio quality validated
- [ ] Firestore logging verified
- [ ] End-to-end flow confirmed

### Phase 4: Documentation (1-2 hours)
- [ ] PROJECT.md updated with deployment status
- [ ] REQUIREMENTS.md updated with actual results
- [ ] Test results documented
- [ ] Known issues logged
- [ ] Next steps identified

---

**Total Estimated Time:** 10-15 hours  
**Priority:** High (blocks production launch)  
**Owner:** Paul (AI Agent)  
**Reviewer:** Samson  
**Status:** Ready to begin implementation

---

**Last Updated:** 2026-02-11 06:31 MST  
**Next Action:** Create ROADMAP.md and begin Phase 1
