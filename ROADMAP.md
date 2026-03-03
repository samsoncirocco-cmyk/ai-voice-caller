# AI Voice Caller - Implementation Roadmap

**Version:** 1.0  
**Date:** 2026-02-11  
**Methodology:** GSD (Get Shit Done) + DoE (Design of Experiments)  
**Status:** Phase 1 Starting Now  

---

## Executive Summary

**Mission:** Build and deploy 4 Sales Rep Brain flows to complete the AI Voice Caller system.

**Timeline:** 10-15 hours over 1-2 days  
**Current Status:** Platform ready, Discovery Mode built  
**Blocker:** None  

**Phases:**
1. **Flow Deployment** (4-6 hours) - Build and deploy 4 conversation flows
2. **Basic Testing** (2-3 hours) - Test each flow independently
3. **Integration** (3-4 hours) - Connect SignalWire and test live calls
4. **Documentation** (1-2 hours) - Update docs and commit changes

---

## Phase 1: Flow Deployment (4-6 Hours)

### Goal
Create Python builder scripts for 4 flows and deploy them to Dialogflow CX.

### Tasks

#### Task 1.1: Deploy Discovery Mode Flow (30 mins)
**Purpose:** Validate deployment process with existing script.

**Actions:**
1. Review `scripts/create-discovery-flow.py`
2. Run deployment script
3. Verify flow exists in Dialogflow CX
4. Test with `make-test-call.py`
5. Fix any deployment issues

**Success Criteria:**
- [ ] Discovery mode flow deployed
- [ ] Flow accessible via API
- [ ] Test query returns expected response

**Output:**
- `config/discovery-mode-flow-name.txt` (flow resource name)
- Console confirmation of deployment

---

#### Task 1.2: Create Cold Calling Flow (1.5 hours)
**Purpose:** Build most complex flow first (9 pages, multiple branches).

**Actions:**
1. Copy `create-discovery-flow.py` as template
2. Modify to create `create-cold-calling-flow.py`
3. Define 9 pages:
   - greeting
   - ask-decision-maker
   - gatekeeper-route
   - decision-maker-pitch
   - interest-assessment
   - objection-handling
   - next-step-proposal
   - confirmation
   - end-call
4. Add routes between pages based on intents:
   - `decision_maker.available` → decision-maker-pitch
   - `decision_maker.unavailable` → gatekeeper-route
   - `interest.high` → next-step-proposal
   - `interest.low` → objection-handling
   - `objection.handled` → next-step-proposal
   - `meeting.agree` → confirmation
   - `meeting.decline` → send-info → end-call
5. Add entry fulfillments with conversation scripts from CONVERSATION-FLOWS.md
6. Configure webhooks (gemini-responder, call-logger)
7. Test deployment

**Success Criteria:**
- [ ] Script runs without errors
- [ ] Flow created in Dialogflow CX
- [ ] All 9 pages exist
- [ ] Routes configured correctly
- [ ] TTS voice set on all pages

**Output:**
- `scripts/create-cold-calling-flow.py` (new file)
- `config/cold-calling-flow-name.txt` (flow resource name)

**Estimated Time:** 1.5 hours

---

#### Task 1.3: Create Follow-Up Flow (1 hour)
**Purpose:** Build simpler flow with context loading.

**Actions:**
1. Create `scripts/create-follow-up-flow.py`
2. Define 6 pages:
   - context-reminder
   - progress-check
   - question-handling
   - next-step-proposal
   - confirmation
   - end-call
3. Add routes:
   - `follow_up.context_confirmed` → progress-check
   - `follow_up.context_forgot` → re-explain → progress-check
   - `progress.reviewed` → question-handling
   - `progress.not_reviewed` → offer-summary → question-handling
   - `next_step.agree` → confirmation
4. Add context loading webhook (pulls previous call data)
5. Test deployment

**Success Criteria:**
- [ ] Script runs without errors
- [ ] Flow created with 6 pages
- [ ] Context webhook configured
- [ ] Routes work correctly

**Output:**
- `scripts/create-follow-up-flow.py`
- `config/follow-up-flow-name.txt`

**Estimated Time:** 1 hour

---

#### Task 1.4: Create Appointment Setting Flow (1 hour)
**Purpose:** Build calendar integration flow.

**Actions:**
1. Create `scripts/create-appointment-setting-flow.py`
2. Define 7 pages:
   - purpose-confirmation
   - availability-inquiry
   - suggest-times
   - alternate-time-handling
   - calendar-booking
   - confirmation
   - end-call
3. Add routes:
   - `appointment.purpose_confirmed` → availability-inquiry
   - `availability.available` → suggest-times
   - `time_slot.accept` → calendar-booking
   - `time_slot.reject` → alternate-time-handling
   - Booking success → confirmation
   - Booking failure → retry or email fallback
4. Configure calendar webhooks (availability, booking)
5. Test deployment

**Success Criteria:**
- [ ] Script runs without errors
- [ ] Flow created with 7 pages
- [ ] Calendar webhooks configured
- [ ] Time slot suggestions work

**Output:**
- `scripts/create-appointment-setting-flow.py`
- `config/appointment-setting-flow-name.txt`

**Estimated Time:** 1 hour

---

#### Task 1.5: Create Lead Qualification Flow (1 hour)
**Purpose:** Build BANT qualification flow with scoring.

**Actions:**
1. Create `scripts/create-lead-qualification-flow.py`
2. Define 8 pages:
   - needs-assessment
   - budget-inquiry
   - authority-check
   - timeline-discussion
   - current-system-discovery
   - lead-score-calculation
   - next-step-routing
   - end-call
3. Add routes:
   - `needs.express` → budget-inquiry
   - `needs.none` → end-call (disqualified)
   - `budget.allocated` → authority-check
   - `authority.decision_maker` → timeline-discussion
   - `timeline.immediate` → lead-score-calculation (high score)
   - Score >70 → next-step-routing (propose meeting)
   - Score 40-69 → next-step-routing (schedule follow-up)
   - Score <40 → next-step-routing (send info, nurture)
4. Configure lead-scorer webhook
5. Test deployment

**Success Criteria:**
- [ ] Script runs without errors
- [ ] Flow created with 8 pages
- [ ] BANT questions configured
- [ ] Scoring webhook configured
- [ ] Routing based on score works

**Output:**
- `scripts/create-lead-qualification-flow.py`
- `config/lead-qualification-flow-name.txt`

**Estimated Time:** 1 hour

---

### Phase 1 Deliverables
- [ ] 5 flows deployed (discovery + 4 new)
- [ ] 5 Python builder scripts created
- [ ] 5 flow resource names saved to config files
- [ ] No deployment errors
- [ ] All flows accessible via Dialogflow CX API

**Phase 1 Success Check:**
```bash
# List all flows
python3 -c "
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
client = dialogflow_cx.FlowsClient(client_options={'api_endpoint': 'us-central1-dialogflow.googleapis.com'})
agent_name = open('config/agent-name.txt').read().strip()
flows = client.list_flows(parent=agent_name)
for flow in flows:
    print(f'✅ {flow.display_name}')
"
```

Expected output:
```
✅ Default Start Flow
✅ test-call
✅ discovery-mode
✅ cold-calling
✅ follow-up
✅ appointment-setting
✅ lead-qualification
```

---

## Phase 2: Basic Testing (2-3 Hours)

### Goal
Test each flow independently to verify conversation paths and intent matching.

### Tasks

#### Task 2.1: Test Discovery Mode (15 mins)
**Actions:**
1. Run `python3 scripts/make-test-call.py --flow discovery-mode`
2. Test conversation paths:
   - Happy path: Provide name and phone
   - Refuse to provide info
   - Provide only name (not phone)
   - Provide garbage input
3. Verify data logged to Firestore
4. Check intent matching accuracy

**Success Criteria:**
- [ ] All paths reachable
- [ ] Intent matching >80% accurate
- [ ] Data logged correctly
- [ ] No errors or crashes

---

#### Task 2.2: Test Cold Calling Flow (30 mins)
**Actions:**
1. Run test with decision maker scenario
2. Run test with gatekeeper scenario
3. Test objection handling paths
4. Test meeting agreement path
5. Test "not interested" path
6. Verify all 9 pages reachable

**Success Criteria:**
- [ ] All pages visited in tests
- [ ] Gatekeeper routing works
- [ ] Objection handling graceful
- [ ] Meeting proposal fires correctly
- [ ] Data logged with all parameters

---

#### Task 2.3: Test Follow-Up Flow (20 mins)
**Actions:**
1. Test with "remembers previous conversation"
2. Test with "doesn't remember"
3. Test "reviewed materials"
4. Test "has questions"
5. Verify context loading

**Success Criteria:**
- [ ] Context reminder works
- [ ] Progress check accurate
- [ ] Question handling functional
- [ ] Next steps proposed correctly

---

#### Task 2.4: Test Appointment Setting Flow (30 mins)
**Actions:**
1. Test accepting first suggested time
2. Test rejecting all times, providing alternate
3. Test "not available" scenario
4. Verify calendar webhook calls (stub for now)
5. Check confirmation details

**Success Criteria:**
- [ ] Time suggestions clear
- [ ] Alternate time capture works
- [ ] Webhook called with correct data
- [ ] Confirmation accurate

---

#### Task 2.5: Test Lead Qualification Flow (30 mins)
**Actions:**
1. Test high-score path (all BANT positive)
2. Test medium-score path (mixed BANT)
3. Test low-score path (no budget/timeline)
4. Test disqualified path (no needs)
5. Verify scoring webhook calculates correctly

**Success Criteria:**
- [ ] BANT questions asked naturally
- [ ] Scoring accurate
- [ ] Routing based on score works
- [ ] Disqualification handled gracefully

---

### Phase 2 Deliverables
- [ ] Test report for each flow (pass/fail + notes)
- [ ] Intent matching accuracy measured
- [ ] Known issues documented
- [ ] Firestore data validated

**Phase 2 Success Check:**
All flows complete test calls without crashing, data logged correctly.

---

## Phase 3: Integration (3-4 Hours)

### Goal
Connect SignalWire to Dialogflow and test live phone calls.

### Tasks

#### Task 3.1: Deploy Core Cloud Functions (2 hours)

**Function 1: call-logger (30 mins)**
- Implement basic Firestore logging
- Deploy to Cloud Functions
- Test with curl
- Verify data written to Firestore

**Function 2: gemini-responder (1 hour)**
- Implement basic fallback response
- Use Gemini API for dynamic responses
- Deploy to Cloud Functions
- Test with low-confidence queries

**Function 3: Calendar Stubs (30 mins)**
- Create stub functions that return fake available times
- Deploy to Cloud Functions
- Test with appointment-setting flow
- Real calendar integration can come later

**Success Criteria:**
- [ ] All 3 functions deployed
- [ ] Functions return 200 OK
- [ ] Dialogflow can call functions
- [ ] Data flows correctly

---

#### Task 3.2: Configure SignalWire Webhook (30 mins)

**Actions:**
1. Create Cloud Function for SignalWire → Dialogflow gateway
2. Deploy to Cloud Functions
3. Get public URL
4. Configure in SignalWire dashboard:
   - Phone number: +1 (602) 898-5026
   - Webhook URL: `https://us-central1-tatt-pro.cloudfunctions.net/dialogflow-voice-gateway`
   - Method: POST
5. Test webhook with SignalWire test tool

**Success Criteria:**
- [ ] Webhook URL public and accessible
- [ ] SignalWire can reach webhook
- [ ] Webhook receives call data
- [ ] Returns valid TwiML/SignalWire response

---

#### Task 3.3: Live Call Testing (1-2 hours)

**Test Plan:**
1. **Test Call 1: Discovery Mode**
   - Call: +1 (602) 898-5026
   - Flow: discovery-mode
   - Verify: Bot answers, asks for name/phone, logs data

2. **Test Call 2: Cold Calling**
   - Call: +1 (602) 898-5026
   - Flow: cold-calling
   - Scenario: Gatekeeper
   - Verify: Bot handles gatekeeper, asks for decision maker info

3. **Test Call 3: Cold Calling (Decision Maker)**
   - Flow: cold-calling
   - Scenario: Talk to decision maker directly
   - Verify: Pitch delivered, objection handled, meeting proposed

4. **Test Call 4: Follow-Up**
   - Flow: follow-up
   - Verify: Context loaded, progress checked, next steps proposed

5. **Test Call 5: Appointment Setting**
   - Flow: appointment-setting
   - Verify: Times suggested, booking confirmed

6. **Test Call 6: Lead Qualification**
   - Flow: lead-qualification
   - Verify: BANT questions asked, score calculated, routed correctly

**For Each Test:**
- [ ] Call connects
- [ ] Audio quality acceptable
- [ ] Bot responds within 2 seconds
- [ ] Conversation feels natural
- [ ] Data logged to Firestore
- [ ] No crashes or errors

---

### Phase 3 Deliverables
- [ ] SignalWire webhook configured
- [ ] 3 Cloud Functions deployed
- [ ] 6 live test calls completed successfully
- [ ] Audio quality validated
- [ ] End-to-end integration confirmed

**Phase 3 Success Check:**
Can call the phone number, have a conversation with any of the 5 flows, and data is logged.

---

## Phase 4: Documentation (1-2 Hours)

### Goal
Update all documentation with deployment results and commit changes.

### Tasks

#### Task 4.1: Update PROJECT.md (20 mins)
- Update status to "Deployed ✅"
- Add deployment dates
- Document any known issues
- Update success metrics

#### Task 4.2: Update REQUIREMENTS.md (20 mins)
- Mark all requirements as met or pending
- Document actual vs. expected results
- Note any deviations

#### Task 4.3: Update SETUP-STATUS.md (10 mins)
- Update step 3 status (flows deployed)
- Add step 4 (integration complete)
- Add step 5 (production ready)

#### Task 4.4: Create DEPLOYMENT-REPORT.md (30 mins)
Document:
- What was built
- Test results
- Known issues
- Next steps
- Production readiness assessment

#### Task 4.5: Git Commit and Push (10 mins)
```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
git add .
git commit -m "Deploy 4 Sales Rep Brain flows - Cold Calling, Follow-Up, Appointment Setting, Lead Qualification

- Created 4 Python builder scripts
- Deployed all flows to Dialogflow CX
- Tested each flow independently
- Integrated SignalWire webhook
- Deployed core Cloud Functions
- 6 live test calls successful
- All data logging to Firestore
- System production ready"
git push
```

#### Task 4.6: Log to Activity Feed (5 mins)
```bash
bash /home/samson/.openclaw/workspace/tools/post-activity.sh \
  "AI Voice Caller: 4 Sales Rep Brain flows deployed and tested successfully. System production ready." \
  "voice-caller-gsd-build" \
  "completed"
```

---

### Phase 4 Deliverables
- [ ] PROJECT.md updated
- [ ] REQUIREMENTS.md updated
- [ ] SETUP-STATUS.md updated
- [ ] DEPLOYMENT-REPORT.md created
- [ ] Changes committed to git
- [ ] Activity feed updated

---

## Success Metrics

### Technical Metrics
| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Flows deployed | 5/5 | 1/5 | 🟡 In Progress |
| Test calls successful | 6/6 | 0/6 | ⏳ Pending |
| Intent accuracy | >80% | TBD | ⏳ Pending |
| Response latency | <1.5s | TBD | ⏳ Pending |
| Data logging | 100% | TBD | ⏳ Pending |
| Webhook uptime | >99% | TBD | ⏳ Pending |

### Business Metrics (Post-Launch)
| Metric | Target | Notes |
|--------|--------|-------|
| Calls per day | 50-100 | After production launch |
| Contact rate | >70% | Live person answers |
| Qualification rate | >30% | Qualified leads |
| Meeting booking rate | >10% | Meetings scheduled |
| Cost per call | <$0.10 | SignalWire + Dialogflow |
| Cost per qualified lead | <$5 | Total cost / qualified |

---

## Risk Management

### High-Risk Items (Must Address)
1. **SignalWire webhook integration untested**
   - Mitigation: Test with live calls early in Phase 3
   - Fallback: Use test-call.py for initial validation

2. **Cloud Functions not yet implemented**
   - Mitigation: Deploy stubs first, iterate later
   - Fallback: Hardcode responses in Dialogflow if webhooks fail

3. **Audio quality unknown**
   - Mitigation: Test early with live calls
   - Fallback: Adjust TTS settings, codec, or voice

### Medium-Risk Items (Monitor)
4. **Intent matching accuracy untested**
   - Mitigation: Test with variety of inputs
   - Fallback: Tune training phrases, add more examples

5. **Response latency may exceed 1.5s**
   - Mitigation: Optimize webhook response times
   - Fallback: Add "thinking" messages ("Let me check...")

### Low-Risk Items (Acceptable)
6. **Calendar integration not real yet**
   - Acceptable: Stubs work for testing, real integration later

7. **Salesforce integration not built**
   - Acceptable: Manual data entry acceptable for initial launch

---

## Timeline

### Day 1 (6-8 hours)
- **Morning (3-4 hours):** Phase 1 - Deploy all flows
- **Afternoon (2-3 hours):** Phase 2 - Basic testing
- **Evening (1 hour):** Start Phase 3 - Deploy Cloud Functions

### Day 2 (4-7 hours)
- **Morning (2-3 hours):** Phase 3 - SignalWire integration + live call testing
- **Afternoon (1-2 hours):** Phase 4 - Documentation and commit
- **Evening (1-2 hours):** Buffer for issues, iteration, refinement

**Total:** 10-15 hours over 1-2 days

---

## Go/No-Go Criteria

### Phase 1 → Phase 2 (Proceed to Testing)
- [ ] All 5 flows deployed without errors
- [ ] All flows accessible via Dialogflow CX API
- [ ] No critical bugs in deployment scripts

### Phase 2 → Phase 3 (Proceed to Integration)
- [ ] At least 4/5 flows pass basic tests
- [ ] Intent matching accuracy >70%
- [ ] Data logging works
- [ ] No show-stopper bugs found

### Phase 3 → Phase 4 (Proceed to Documentation)
- [ ] SignalWire webhook working
- [ ] At least 3/6 live test calls successful
- [ ] Audio quality acceptable
- [ ] Data flowing to Firestore
- [ ] No critical crashes

### Phase 4 → Production (Launch)
- [ ] All 6 test calls successful
- [ ] Documentation complete
- [ ] Known issues documented
- [ ] Cost per call measured and acceptable
- [ ] Samson approves

---

## Emergency Rollback Plan

If something goes catastrophically wrong:

1. **Disable SignalWire webhook**
   - Log into SignalWire dashboard
   - Remove webhook URL
   - Phone calls won't trigger bot (no harm)

2. **Revert to test-call.py**
   - Continue testing via API (no phone)
   - Fix issues offline
   - Re-enable webhook when fixed

3. **Delete bad flows**
   ```bash
   # List flows
   python3 scripts/list-flows.py
   
   # Delete specific flow
   python3 scripts/delete-flow.py --flow-name "problematic-flow"
   ```

4. **Restore from git**
   ```bash
   git log --oneline  # Find last good commit
   git reset --hard <commit-hash>
   git push -f  # Force push if necessary
   ```

---

## Next Steps After Completion

### Immediate (Within 24 Hours)
1. Run 10-20 real prospect calls (SLED list)
2. Collect feedback and conversation logs
3. Identify improvement areas
4. Tune training phrases based on real data

### Short-Term (Within 1 Week)
5. Implement real calendar integration
6. Build Salesforce integration
7. Add analytics dashboard
8. Optimize conversation scripts based on learnings

### Medium-Term (Within 1 Month)
9. Scale to 50-100 calls per day
10. A/B test different conversation approaches
11. Build automated retry logic
12. Add sentiment analysis
13. Create real-time coaching dashboard

---

## Conclusion

**This roadmap provides a clear path from current state (platform ready) to production ready (all flows deployed and tested).**

**Timeline:** 10-15 hours  
**Confidence:** High (95%)  
**Blockers:** None  
**Risk:** Low (all critical bugs already fixed)  

**Ready to execute.**

---

**Last Updated:** 2026-02-11 06:31 MST  
**Status:** Ready to begin Phase 1  
**Next Action:** Task 1.1 - Deploy Discovery Mode flow
