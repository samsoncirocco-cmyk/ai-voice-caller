# Directive: Voice Caller Implementation

## Goal
Deploy the AI Voice Caller system in 5 weeks with clear milestones, quality gates, and rollback procedures. Focus on Cold Calling (Use Case 1) first, then expand.

---

## Week-by-Week Implementation Plan

### Week 1: Infrastructure Setup
**Objective:** All cloud services provisioned and connected.

| Day | Task | Owner | Deliverable |
|-----|------|-------|-------------|
| Mon | Enable Google Cloud APIs (Dialogflow CX, Speech-to-Text, Text-to-Speech, Vertex AI) | Paul | APIs enabled in `tatt-pro` project |
| Tue | Create SignalWire account, purchase phone number | Paul | Phone number active |
| Wed | Create service account with IAM permissions | Paul | `voice-caller-sa@tatt-pro.iam.gserviceaccount.com` |
| Thu | Set up Dialogflow CX agent ("Fortinet SLED Voice Caller") | Paul | Agent created with phone gateway |
| Fri | Configure SIP trunk between SignalWire → Dialogflow | Paul | Test call connects to Dialogflow |

**Quality Gate 1:**
- [ ] Can place test call to SignalWire number
- [ ] Dialogflow receives and responds with default greeting
- [ ] All APIs show as enabled in Cloud Console

**Rollback:** If SignalWire fails SIP integration, fall back to Twilio (higher cost but proven Dialogflow integration).

---

### Week 2: Build Core Flows
**Objective:** Cold Calling flow fully functional with intent recognition.

| Day | Task | Owner | Deliverable |
|-----|------|-------|-------------|
| Mon | Design Cold Calling conversation flow (Dialogflow pages) | Paul | Flow diagram + Dialogflow pages |
| Tue | Create intents: greeting, yes/no, objections, email request | Paul | Intents with training phrases |
| Wed | Write fulfillment webhook (Cloud Function) skeleton | Paul | `/webhook` endpoint responding |
| Thu | Configure Text-to-Speech voice (Neural2-D or Studio-O) | Paul | Bot speaks naturally |
| Fri | End-to-end test: complete cold call conversation | Paul | Recording of successful call |

**Quality Gate 2:**
- [ ] Bot correctly recognizes "yes", "no", "not interested", "call back later"
- [ ] Bot handles unexpected responses without crashing
- [ ] Conversation flows to logical endpoint (book meeting, send info, or end call)
- [ ] Latency <3 seconds from user stops speaking to bot responds

**Rollback:** If intent recognition fails >50% of the time, simplify to yes/no-only flow and iterate.

---

### Week 3: Gemini Integration + Backend
**Objective:** Smart responses for unstructured input, backend logging operational.

| Day | Task | Owner | Deliverable |
|-----|------|-------|-------------|
| Mon | Create Gemini responder Cloud Function | Paul | Function deployed |
| Tue | Integrate Gemini with Dialogflow webhook | Paul | Fallback to Gemini working |
| Wed | Set up Firestore: `calls` collection with schema | Paul | Firestore collection ready |
| Thu | Write call logging: transcript, outcome, lead_score | Paul | Each call creates document |
| Fri | Salesforce integration: create task on call completion | Paul | Task appears in Salesforce |

**Quality Gate 3:**
- [ ] When caller says something unexpected, Gemini generates sensible response
- [ ] Gemini context includes account name and current goal
- [ ] Every call creates Firestore document with: timestamp, phone, outcome, transcript
- [ ] Salesforce task created for "interested" and "meeting_booked" outcomes

**Rollback:** If Gemini introduces >2 second latency, disable Gemini and use expanded intent library instead.

---

### Week 4: Calendar + Analytics + Polish
**Objective:** Full booking flow, real-time analytics, production-ready quality.

| Day | Task | Owner | Deliverable |
|-----|------|-------|-------------|
| Mon | Google Calendar API integration: check availability | Paul | Bot can query free slots |
| Tue | Calendar booking: create event, send invite | Paul | Meeting appears on calendar |
| Wed | BigQuery streaming from Firestore | Paul | Call logs in BigQuery |
| Thu | Create Data Studio dashboard: calls/day, outcomes, lead scores | Paul | Dashboard accessible |
| Fri | Voice quality tuning: SSML, pauses, emphasis | Paul | Bot sounds natural |

**Quality Gate 4:**
- [ ] "Book a meeting for tomorrow morning" → correct slot offered
- [ ] Calendar invite sent to caller's email
- [ ] Dashboard shows last 24 hours of call activity
- [ ] Listen to 10 test calls — all sound natural (no robotic pauses, correct pronunciation)

**Rollback:** If calendar integration fails, fall back to "I'll have someone reach out to schedule" and create Salesforce task instead.

---

### Week 5: Pilot & Launch
**Objective:** Prove system works with real calls, then scale.

| Day | Task | Owner | Deliverable |
|-----|------|-------|-------------|
| Mon | Select 10 low-risk pilot accounts | Paul | Account list in `pilot-accounts.csv` |
| Tue | Execute pilot calls (manual trigger, 2-3 per hour) | Paul | 10 calls completed |
| Wed | Review transcripts, identify issues | Paul | Issues logged in `pilot-issues.md` |
| Thu | Fix critical issues, re-test | Paul | All blockers resolved |
| Fri | **LAUNCH:** Batch call 50 accounts | Paul | 50 calls in one session |

**Quality Gate 5 (Launch Gate):**
- [ ] Pilot: ≥80% of calls complete without technical failure
- [ ] Pilot: ≥50% of calls have meaningful conversation (>30 seconds)
- [ ] Pilot: At least 1 meeting booked or 2 "send info" requests
- [ ] Kill switch tested and working
- [ ] Daily call limit enforced (max 100)

**Rollback:** If pilot success rate <50%, halt launch, analyze failures, reschedule for following week.

---

## Critical Path Items

These MUST happen in order — any delay cascades:

1. **SignalWire ↔ Dialogflow SIP trunk** (Week 1, Day 4-5)
   - Without this, no phone calls work
   - Backup: Twilio

2. **Intent recognition accuracy >70%** (Week 2, Day 5)
   - Without this, bot can't hold conversation
   - Backup: Simplify to yes/no flow

3. **Gemini latency <2 seconds** (Week 3, Day 2)
   - Without this, conversations feel broken
   - Backup: Disable Gemini, expand intents

4. **Call logging to Firestore** (Week 3, Day 4)
   - Without this, no visibility into what's happening
   - Backup: Log to Cloud Logging, query later

---

## Dependencies and Blockers

### External Dependencies
| Dependency | Risk | Mitigation |
|------------|------|------------|
| SignalWire approval | Low | Apply early, have Twilio as backup |
| Google Cloud quota | Low | Request quota increases proactively |
| Salesforce API access | Medium | Ensure Paul has API user permissions |
| Calendar API auth | Low | OAuth2 already set up |

### Internal Dependencies
| Dependency | Required By | Status |
|------------|-------------|--------|
| GCP project (`tatt-pro`) access | Week 1 | ✅ Ready |
| Salesforce `sf` CLI authentication | Week 3 | ✅ Ready |
| Account list (CSV) | Week 5 | Exists in `projects/sled-toolkit/accounts.csv` |
| High Point Networks coordination | Week 5 | TBD — for meeting handoffs |

### Potential Blockers
1. **SignalWire SIP issues** — Dialogflow phone gateway can be finicky
   - *Watch for:* "No carrier" errors, one-way audio
   - *Fix:* Check SIP settings, may need regional number

2. **Dialogflow webhook timeout** — Max 5 seconds
   - *Watch for:* Gemini calls timing out
   - *Fix:* Pre-warm functions, cache prompts

3. **Salesforce rate limits** — 100,000 API calls/day
   - *Watch for:* 500 calls/day won't hit this
   - *Fix:* Batch updates if scaling beyond

---

## Quality Gates Summary

| Gate | Week | Criteria | Pass/Fail |
|------|------|----------|-----------|
| QG1 | 1 | Test call connects to Dialogflow | ⬜ |
| QG2 | 2 | Intent recognition >70%, latency <3s | ⬜ |
| QG3 | 3 | Gemini fallback working, call logging active | ⬜ |
| QG4 | 4 | Calendar booking working, dashboard live | ⬜ |
| QG5 | 5 | Pilot >80% success, at least 1 meeting booked | ⬜ |

**Rule:** Do not proceed to next week until current quality gate passes.

---

## Rollback Procedures

### Level 1: Feature Rollback
*Something specific breaks — disable feature, continue with reduced functionality.*

| Feature | Rollback | Impact |
|---------|----------|--------|
| Gemini integration | Disable webhook fallback | Bot uses only pre-defined responses |
| Calendar booking | Disable | Bot says "I'll have someone follow up" |
| Salesforce tasks | Disable | Manual task creation from call logs |

### Level 2: Flow Rollback
*Entire conversation flow broken — switch to simpler flow.*

1. Create `emergency-flow` with minimal yes/no logic
2. Update Dialogflow start page to use emergency flow
3. Log all calls for manual follow-up

### Level 3: Full Rollback
*System completely broken — stop all calls.*

1. **Kill switch:** In SignalWire, disable phone number routing
2. **Alternative:** In Dialogflow, set default response to "We're experiencing issues, goodbye"
3. **Notify:** Alert Samson via Telegram
4. **Postmortem:** Document failure in `directives/voice-caller-postmortem.md`

---

## Post-Launch Checklist

- [ ] All 5 quality gates passed
- [ ] Kill switch tested and documented
- [ ] Cost monitoring alert set at $50/day
- [ ] Operations directive reviewed (`voice-caller-operations.md`)
- [ ] Compliance checklist complete (`voice-caller-compliance.md`)
- [ ] First batch of 50 calls completed
- [ ] Post-pilot retrospective written

---

## Edge Cases

- **Dialogflow phone gateway not available in region:** Use SIP trunk directly to Cloud Functions
- **Voice sounds robotic:** Switch from Neural2 to Studio voice (10x cost but worth it)
- **Calls going to voicemail:** Implement voicemail detection, leave brief message or hang up
- **Caller transfers to someone else:** Bot should restart intro with new person

---

## Lessons Learned
*(To be updated during implementation)*

- TBD
