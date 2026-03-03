# Directive: Voice Caller Compliance

## Goal
Operate the AI Voice Caller within legal boundaries, protect the business from liability, and maintain ethical standards. Zero tolerance for compliance violations.

---

## TCPA Compliance Procedures

### What is TCPA?
The Telephone Consumer Protection Act (1991) restricts telemarketing calls. **Violations cost $500-$1,500 PER CALL.**

### B2B Exemption (Our Primary Protection)

**TCPA primarily regulates calls to consumers (B2C).** Business-to-business (B2B) calls have significantly fewer restrictions.

**Our calls qualify as B2B because:**
- Calling business phone numbers (not personal cell phones)
- Calling in professional capacity (IT directors, purchasing managers)
- Discussing business solutions (FortiVoice for organizations)
- Targeting organizations (schools, cities, counties), not individuals

### What We MUST Still Do

Even with B2B exemption:

1. **Honor opt-out requests immediately**
   - "Take me off your list" → Add to Do Not Call, never call again
   - "Don't call this number" → Same treatment
   - No exceptions, no "one more try"

2. **Don't call before 8 AM or after 9 PM** (caller's local time)
   - Our batch calling windows (9-11 AM, 2-4 PM) are safe
   - System enforces time restrictions

3. **Identify ourselves clearly**
   - "This is Paul from Fortinet" (not deceptive)
   - Don't pretend to be calling for research/survey

4. **No robocalls to cell phones without consent**
   - If we dial a cell phone (even business-assigned), higher risk
   - Mitigation: Prioritize direct office lines when available
   - If cell only: First call establishes relationship, follow-ups safer

### Bot Script Compliance Checks

| Requirement | Bot Implementation | ✓ |
|-------------|-------------------|---|
| Identify caller | "This is Paul from Fortinet" in opening | ⬜ |
| Identify company | "Fortinet" mentioned within 10 seconds | ⬜ |
| Offer opt-out | "If you'd prefer I not call again, just let me know" | ⬜ |
| Honor opt-out | If detected, say "I'll remove you from our list. Have a good day." and end | ⬜ |
| Don't mislead | No false claims about product or relationship | ⬜ |

### Opt-Out Detection

Bot must recognize these phrases and immediately add to Do Not Call:
- "Take me off your list"
- "Remove me"
- "Don't call again"
- "Stop calling"
- "Not interested, don't call back"
- "Put me on your do not call list"
- "Opt out"

**Dialogflow Intent:** `intent.opt_out` with training phrases for all above

**Webhook Action:**
```python
def handle_opt_out(phone_number: str):
    # 1. Add to Do Not Call immediately
    firestore.collection('do_not_call').document(phone_number).set({
        'phone': phone_number,
        'added_date': datetime.now(),
        'reason': 'caller_request',
        'call_id': current_call_id
    })
    
    # 2. End call gracefully
    return {
        'response': "I completely understand. I'll remove you from our list. Have a great day.",
        'action': 'end_call'
    }
```

---

## Do Not Call List Management

### Internal Do Not Call List

**Location:** Firestore collection `do_not_call`

**Schema:**
```json
{
  "phone": "+15551234567",
  "added_date": "2025-02-10T10:30:00Z",
  "reason": "caller_request | legal_risk | duplicate | wrong_number",
  "source": "bot | manual | import",
  "call_id": "abc123",
  "notes": "Optional context"
}
```

### Pre-Call Check (MANDATORY)

Before EVERY call, webhook checks Do Not Call:

```python
def can_call(phone_number: str) -> bool:
    # Check internal DNC
    dnc_doc = firestore.collection('do_not_call').document(phone_number).get()
    if dnc_doc.exists:
        log_blocked_call(phone_number, "internal_dnc")
        return False
    
    # Check national DNC (if we subscribe)
    # if check_national_dnc(phone_number):
    #     return False
    
    return True
```

### National Do Not Call Registry

**Current status:** Not required for B2B calls.

**If we ever call residential numbers:**
- Subscribe to FTC's National DNC Registry ($75/year for small businesses)
- Scrub call list against registry every 31 days
- Pay-per-query: https://www.donotcall.gov/

### DNC List Maintenance

**Daily:**
- All opt-outs from yesterday's calls added automatically

**Weekly:**
- Export DNC list for backup
- Cross-reference against call list (ensure no calls to DNC numbers)

**Monthly:**
- Audit: Review DNC additions
- Check for accidental additions (wrong number, misheard intent)

---

## Data Privacy & Call Recordings

### What We Collect

| Data Type | Storage Location | Retention | Purpose |
|-----------|------------------|-----------|---------|
| Phone number | Firestore | Indefinite | Call tracking, DNC |
| Call transcript | Firestore/GCS | 90 days | Quality review, training |
| Audio recording | Cloud Storage | 30 days | Dispute resolution |
| Account name/details | Firestore | Indefinite | Personalization |
| Lead score | Firestore | Indefinite | Qualification |
| Call metadata | BigQuery | 1 year | Analytics |

### Recording Consent

**One-party consent states:** We (Fortinet/Paul) are a party to the call. Recording is legal without explicit consent in most states.

**Two-party consent states:** CA, FL, IL, MD, MA, MI, MT, NH, PA, WA require all parties to consent.

**Our approach:**
1. **Check state before calling** — Use phone number area code
2. **For two-party states, add disclosure:**
   - "This call may be recorded for quality purposes."
   - Add to opening script before substantive conversation
3. **If caller objects to recording:**
   - Disable recording for that call (SignalWire API)
   - Continue call without recording

**Implementation:**
```python
TWO_PARTY_STATES = ['CA', 'FL', 'IL', 'MD', 'MA', 'MI', 'MT', 'NH', 'PA', 'WA']

def get_recording_consent_script(area_code: str) -> str:
    state = area_code_to_state(area_code)
    if state in TWO_PARTY_STATES:
        return "Just so you know, this call may be recorded. "
    return ""  # One-party state, no disclosure needed
```

### PII Handling

**Personally Identifiable Information we may collect:**
- Name (from account data)
- Phone number
- Email (if caller provides)
- Job title
- Voice (in recordings)

**Protection measures:**
- Firestore security rules (only service account access)
- Cloud Storage encryption at rest (default)
- No PII in logs (mask phone numbers in Cloud Logging)
- Access logging for audit trail

### Data Retention Schedule

| Data | Retention | Deletion Method |
|------|-----------|-----------------|
| Call recordings | 30 days | Cloud Storage lifecycle policy |
| Transcripts | 90 days | Firestore TTL or manual purge |
| Call metadata | 1 year | BigQuery partition expiration |
| DNC list | Indefinite | Manual only |
| Account data | Indefinite | Salesforce master |

**Deletion script (run monthly):**
```bash
# Delete recordings older than 30 days
gsutil rm -r "gs://tatt-pro-voice-caller/recordings/$(date -d '30 days ago' +%Y-%m)/"

# Delete old transcripts (Firestore TTL handles this if configured)
```

---

## Legal Review Requirements

### When Legal Review is Required

| Scenario | Action | Who Reviews |
|----------|--------|-------------|
| New script/flow | Before launch | Fortinet Legal (if available) or Samson |
| Objection handling changes | Before launch | Samson |
| New use case | Before launch | Fortinet Legal |
| Complaint received | Immediately | Fortinet Legal |
| Demand letter / lawsuit | Immediately | Fortinet Legal + outside counsel |
| Regulatory inquiry | Immediately | Fortinet Legal |

### Script Approval Checklist

Before any new script goes live:

- [ ] No false or misleading claims
- [ ] Company identified clearly
- [ ] Opt-out offered
- [ ] No high-pressure tactics
- [ ] Recording disclosure included (for 2-party states)
- [ ] Complies with Fortinet brand guidelines
- [ ] Reviewed by Samson

### Legal Escalation Path

```
Issue Detected
     │
     ▼
Is it a complaint or demand letter?
     │
     ├── YES → Stop all calls to that contact
     │         → Forward to Fortinet Legal immediately
     │         → Document everything (do not delete!)
     │
     └── NO (general compliance question)
            → Research internally
            → If unclear, consult Fortinet Legal
```

---

## Risk Mitigation Checklist

### Pre-Launch Checklist

- [ ] **B2B only:** All numbers on call list are business contacts
- [ ] **DNC system:** Internal Do Not Call list functional
- [ ] **Opt-out handling:** Bot recognizes and processes opt-outs
- [ ] **Recording disclosure:** Added for two-party consent states
- [ ] **Time restrictions:** Calls only 8 AM - 9 PM local time
- [ ] **Clear identification:** Bot says "Paul from Fortinet" immediately
- [ ] **Kill switch:** Can disable all calls within 5 minutes
- [ ] **Data security:** Firestore/GCS access properly restricted
- [ ] **Retention policies:** Set up and automated

### Ongoing Compliance Checks (Weekly)

- [ ] Review opt-out requests — all processed?
- [ ] Check DNC list growth — any patterns?
- [ ] Listen to flagged calls — any compliance issues?
- [ ] Verify no calls to DNC numbers
- [ ] Confirm call times within allowed windows

### Compliance Incident Log

Document any compliance issues:

| Date | Issue | Severity | Resolution | Prevented Future? |
|------|-------|----------|------------|-------------------|
| — | — | — | — | — |

---

## State-Specific Requirements

### Primary Markets (IA, NE, SD)

| State | Recording Consent | Other Notes |
|-------|-------------------|-------------|
| Iowa | One-party | No special restrictions for B2B |
| Nebraska | One-party | No special restrictions for B2B |
| South Dakota | One-party | No special restrictions for B2B |

**Good news:** All three primary states are one-party consent. No recording disclosure required.

### If Expanding to Other States

Check these two-party consent states:
- **California:** Explicit consent required. Add disclosure.
- **Florida:** Explicit consent required. Add disclosure.
- **Illinois:** Very strict. Ensure clear disclosure.
- **Pennsylvania:** Explicit consent required.

### Mini-TCPA Laws

Some states have additional telemarketing restrictions:
- **Florida:** State DNC list (if calling consumers)
- **Texas:** Specific disclosures required

**For B2B, these generally don't apply, but monitor if rules change.**

---

## Response Templates

### If Caller Threatens Legal Action

**Bot response:**
"I understand you're upset. I'll have Paul reach out to you directly to address your concerns. For now, I'm removing you from our list. What's the best email for Paul to contact you?"

**Immediate actions:**
1. Add to DNC
2. Flag call for review
3. Alert Samson via Telegram
4. Document full transcript

### If Caller Claims DNC Violation

**Bot response:**
"I apologize if this call was unwelcome. I'll make sure you're removed from our list immediately. We take these concerns seriously."

**Actions:**
1. Add to DNC
2. Check: Were they already on DNC? (If yes, major issue)
3. Document incident
4. If already on DNC: Stop all calls, investigate, escalate

### If Caller Demands Information About Data

**Bot response:**
"I understand you'd like to know what information we have. I'll have Paul follow up with you about that. What's the best email to send that to?"

**Actions:**
1. Create Salesforce task: "Data privacy inquiry"
2. Follow up within 48 hours with written response
3. If formal request (e.g., CCPA), escalate to Fortinet Legal

---

## Audit Trail Requirements

Maintain records for at least 5 years:

1. **Call logs:** Who, when, outcome
2. **DNC list changes:** Who added, when, why
3. **Opt-out requests:** Exact transcript showing request and our response
4. **Complaints:** Full documentation
5. **Script versions:** Dated copies of all scripts used

**Storage:**
- Call logs: BigQuery (partitioned, archived to GCS after 1 year)
- DNC changes: Firestore with history collection
- Complaints: Google Drive (Samson's legal folder)
- Scripts: Git history in this repo

---

## Red Flags to Watch

If you see any of these, STOP and escalate:

🚨 **Call to someone already on DNC**
- How did this happen? Investigate immediately.
- Apologize personally (not bot).
- Review and fix the gap in DNC checking.

🚨 **Pattern of hang-ups + angry callbacks**
- May indicate our approach is too aggressive.
- Review scripts, reduce call volume, investigate.

🚨 **Formal complaint to FTC or state AG**
- Stop all calling.
- Document everything.
- Engage Fortinet Legal.

🚨 **Attorney contact**
- Do not respond directly.
- Forward to Fortinet Legal immediately.
- Preserve all records.

---

## Quarterly Compliance Audit

Every quarter, conduct:

1. **DNC list audit:**
   - Compare DNC list against call history
   - Verify no calls to DNC numbers in past quarter
   - Check opt-out processing time (should be <24 hours)

2. **Script audit:**
   - Listen to 10 random calls
   - Verify compliance with approved scripts
   - Check for proper identification and opt-out offers

3. **Data retention audit:**
   - Verify old recordings deleted per policy
   - Check access logs for unauthorized access
   - Confirm encryption active

4. **Incident review:**
   - Review any complaints or escalations
   - Document learnings and preventive measures

---

## Edge Cases

- **Caller gives consent for personal cell, then rescinds:** Remove from call list, add to DNC
- **Caller is both DNC and active opportunity:** Never call, rely on email only
- **Attorney general subpoena for records:** Comply, engage outside counsel, preserve everything
- **Caller claims we called despite DNC and demands compensation:** Check records, if true → Fortinet Legal immediately

---

## Lessons Learned
*(To be updated during operations)*

- TBD
