# Directive: Voice Caller Operations

## Goal
Run the AI Voice Caller system daily with consistent quality, cost control, and rapid incident response. This is the operational runbook.

---

## Daily Operations Procedures

### Morning Startup (8:00 AM MST)
1. **System health check:**
   ```bash
   # Check Dialogflow agent status
   gcloud dialogflow agents list --project=tatt-pro
   
   # Check SignalWire balance
   curl -s "https://api.signalwire.com/v1/accounts/{ACCOUNT_ID}/balance" -u {API_KEY}:
   
   # Verify Cloud Functions running
   gcloud functions list --project=tatt-pro --filter="name~voice-caller"
   ```

2. **Review yesterday's calls:**
   - Open BigQuery dashboard
   - Check: total calls, success rate, average duration
   - Flag any calls with `outcome = "error"` for review

3. **Prepare today's call list:**
   - Pull from `accounts.csv` or Salesforce lead queue
   - Remove any accounts on Do Not Call list
   - Max 100 accounts per batch

### Batch Calling Execution (9:00-11:00 AM, 2:00-4:00 PM)
**Best call windows:** 9-11 AM and 2-4 PM local time for contact

1. **Start batch:**
   ```bash
   python3 scripts/batch-call.py --list today-batch.csv --limit 50 --delay 30
   ```
   - `--delay 30`: 30 seconds between calls (prevents simultaneous calls)
   - `--limit 50`: Max 50 calls per batch

2. **Monitor in real-time:**
   - Watch Firestore console for new call documents
   - Check for errors in Cloud Logging
   - Listen to any flagged calls

3. **Mid-batch checkpoint (after 25 calls):**
   - Success rate ≥ 70%? → Continue
   - Success rate < 50%? → Pause, investigate, resume or abort

### End of Day Review (5:00 PM MST)
1. **Generate daily report:**
   ```sql
   -- BigQuery query
   SELECT 
     DATE(timestamp) as date,
     COUNT(*) as total_calls,
     COUNTIF(outcome = 'meeting_booked') as meetings,
     COUNTIF(outcome = 'send_info') as send_info,
     COUNTIF(outcome = 'not_interested') as not_interested,
     COUNTIF(outcome = 'error') as errors,
     AVG(duration_seconds) as avg_duration
   FROM `tatt-pro.voice_caller.calls`
   WHERE DATE(timestamp) = CURRENT_DATE()
   GROUP BY 1
   ```

2. **Update Salesforce:**
   - Verify all tasks created
   - Add notes for hot leads
   - Update opportunity stages

3. **Plan tomorrow:**
   - Identify follow-up calls needed
   - Queue new accounts

---

## Cost Monitoring and Budget Controls

### Monthly Budget: $100 (100-150 calls/month)

| Component | Cost/Unit | Monthly Cap |
|-----------|-----------|-------------|
| SignalWire calls | $0.0085/min | $3.00 |
| Dialogflow CX audio | $0.06/request | $65.00 |
| Text-to-Speech | $0.000016/char | $10.00 |
| Gemini Flash | $0.002/1K tokens | $0.50 |
| BigQuery | $5/TB queried | $5.00 |
| Buffer | — | $16.50 |

### Real-Time Cost Alerts
Set up in Google Cloud Billing:
```bash
# Create budget alert at 50%, 75%, 100%
gcloud billing budgets create \
  --billing-account={BILLING_ACCOUNT} \
  --display-name="Voice Caller Monthly" \
  --budget-amount=100USD \
  --threshold-rules=percent=50 \
  --threshold-rules=percent=75 \
  --threshold-rules=percent=100
```

### Daily Spending Limit
- **Hard limit:** $10/day
- **Soft warning:** $5/day
- **Implemented via:** Call counter in Firestore + webhook check

```python
# In webhook: check daily call count before proceeding
def check_daily_limit():
    today_calls = firestore.collection('calls') \
        .where('date', '==', today) \
        .count()
    if today_calls >= 100:
        raise Exception("Daily call limit reached")
```

### Cost Optimization Triggers
| Condition | Action |
|-----------|--------|
| Daily spend > $5 | Alert Samson via Telegram |
| Daily spend > $10 | Auto-pause all calls |
| Monthly > $75 | Review and reduce call volume |
| Individual call > $2 | Flag for review (likely stuck in loop) |

---

## Performance Monitoring

### Key Metrics Dashboard
Create in Google Data Studio or BigQuery dashboard:

**Real-Time Metrics:**
- Calls in progress (should be 0-3)
- Calls completed today
- Current error rate (last 10 calls)

**Daily Metrics:**
- Total calls
- Success rate (calls with meaningful conversation ≥30s)
- Meeting book rate
- Average call duration
- Cost per call

**Weekly Metrics:**
- Qualified leads generated
- Conversion rate (calls → meetings)
- Cost per qualified lead
- Most common objections

### Latency Monitoring
**Target:** Bot responds within 2 seconds of user finishing

```sql
-- Check latency from logs
SELECT 
  AVG(response_latency_ms) as avg_latency,
  PERCENTILE_CONT(response_latency_ms, 0.95) as p95_latency
FROM `tatt-pro.voice_caller.call_events`
WHERE event_type = 'bot_response'
  AND DATE(timestamp) = CURRENT_DATE()
```

**Alert thresholds:**
- P95 > 3 seconds → Warning
- P95 > 5 seconds → Critical (conversations breaking)

### Success Rate Thresholds
| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Call completion rate | ≥80% | 60-79% | <60% |
| Intent recognition | ≥75% | 60-74% | <60% |
| Meeting book rate | ≥10% | 5-9% | <5% |
| Error rate | <5% | 5-15% | >15% |

---

## Incident Response Procedures

### Severity Levels

**P1 (Critical) — All calls failing:**
- Bot not responding
- All calls dropping immediately
- Gemini returning errors

**P2 (High) — Degraded service:**
- High latency (>5 seconds)
- Intent recognition <50%
- Calendar booking broken

**P3 (Medium) — Partial issues:**
- Individual call failures
- Single component slow
- Non-blocking bugs

**P4 (Low) — Cosmetic:**
- Voice sounds off
- Minor logging issues

### Incident Response Flow

```
┌────────────────────────────────────────────────────────┐
│                    INCIDENT DETECTED                   │
│  (Error spike, cost spike, user report, alert)         │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│              1. STOP THE BLEEDING (5 min)              │
│  - If P1: Activate kill switch (disable SignalWire)   │
│  - If P2: Pause batch calling                         │
│  - If P3/P4: Continue monitoring                      │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│              2. IDENTIFY ROOT CAUSE (15 min)           │
│  - Check Cloud Logging for errors                     │
│  - Check Dialogflow test console                      │
│  - Check SignalWire dashboard                         │
│  - Check Gemini API status                            │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│              3. APPLY FIX OR WORKAROUND                │
│  - Feature rollback (disable Gemini, calendar, etc.)  │
│  - Redeploy Cloud Functions                           │
│  - Restart Dialogflow agent                           │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│              4. VERIFY AND RESUME                      │
│  - Place 3 test calls                                 │
│  - Confirm logs showing success                       │
│  - Resume batch calling                               │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│              5. POSTMORTEM (within 24 hours)           │
│  - Document what happened                             │
│  - Document root cause                                │
│  - Document fix and prevention                        │
│  - Update this runbook                                │
└────────────────────────────────────────────────────────┘
```

### Kill Switch Activation
**When to activate:** All P1 incidents, or rapid cost increase

**How to activate:**
```bash
# Option 1: Disable SignalWire routing
curl -X PATCH "https://api.signalwire.com/v1/phone_numbers/{NUMBER_SID}" \
  -u {API_KEY}: \
  -d '{"voice_url": ""}'

# Option 2: Disable Dialogflow phone gateway
gcloud dialogflow agents update --project=tatt-pro \
  --phone-gateway-enabled=false

# Option 3: Set all calls to fail-safe response
# Update Dialogflow start flow to say "goodbye" and hang up
```

### Common Issues & Fixes

| Issue | Symptoms | Fix |
|-------|----------|-----|
| SignalWire down | All calls fail to connect | Wait, or switch to Twilio |
| Dialogflow webhook timeout | Bot says "something went wrong" | Check Cloud Function logs, reduce Gemini calls |
| Gemini rate limit | Fallback responses only | Reduce call volume, request quota increase |
| One-way audio | Caller can't hear bot | Check SIP codec settings |
| Bot in infinite loop | Same response repeating | Kill call, fix intent/flow logic |
| Caller stuck on hold | Silence for >30 seconds | Add timeout transitions in Dialogflow |

---

## Lead Management Workflow

### Lead Scoring During Call
Bot assigns score based on responses:

| Signal | Points |
|--------|--------|
| Caller engages (>30s conversation) | +2 |
| Answers discovery questions | +2 |
| Mentions timeline ("next year") | +1 |
| Mentions budget/funding | +3 |
| Asks questions about product | +2 |
| Agrees to meeting | +5 |
| Asks to send info | +1 |
| Says "not now" (not "never") | +1 |
| Immediate hang-up | -3 |
| "Remove from list" | -5 |

### Lead Routing by Score

**Hot Lead (Score ≥ 7):**
- Action: Immediate Salesforce task with "Hot Lead" priority
- Follow-up: Call from Paul within 24 hours
- Note: Meeting already booked or highly engaged

**Warm Lead (Score 3-6):**
- Action: Salesforce task with 1-week follow-up
- Follow-up: Send email with relevant case study
- Note: Interested but not ready now

**Cold Lead (Score 0-2):**
- Action: Add to nurture campaign (quarterly check-in)
- Follow-up: Automated email sequence
- Note: Not currently active

**Dead Lead (Score < 0):**
- Action: Add to Do Not Call list if requested
- Follow-up: None for 12 months
- Note: Remove from active prospecting

### Lead Handoff Process

1. **Bot completes call** → Firestore document created
2. **Webhook fires** → Creates Salesforce task
3. **Morning review** → Paul reviews hot/warm leads
4. **Partner handoff** → High Point Networks for meeting-booked leads

### Salesforce Task Format
```
Subject: Voice Bot - [OUTCOME] - [ACCOUNT NAME]
Description:
  Call Date: [TIMESTAMP]
  Duration: [DURATION]
  Lead Score: [SCORE]
  Outcome: [OUTCOME]
  
  Summary: [GEMINI-GENERATED SUMMARY]
  
  Key Points:
  - [EXTRACTED KEY POINTS]
  
  Next Steps: [RECOMMENDED NEXT STEPS]
  
  Transcript: [LINK TO FULL TRANSCRIPT]
```

---

## Weekly Operations Review

Every Friday:

1. **Metrics review:**
   - Total calls this week
   - Meetings booked
   - Cost vs. budget
   - Success rate trend

2. **Quality review:**
   - Listen to 5 random calls
   - Identify conversation improvements
   - Note any awkward bot responses

3. **Pipeline review:**
   - Follow up on all hot leads
   - Update Salesforce opportunities
   - Plan next week's call list

4. **Optimization:**
   - Review A/B test results
   - Update conversation flows if needed
   - Adjust calling times if patterns emerge

---

## Edge Cases

- **Bot calls during holiday** → Check holiday calendar before batch
- **Caller transfers to multiple people** → Bot should restart intro each time
- **Extremely long call (>10 min)** → Auto-terminate, flag for review
- **Caller requests callback to different number** → Capture, flag, don't auto-call
- **System goes over budget** → Auto-pause, alert immediately

---

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/batch-call.py` | Execute batch calls | `python3 batch-call.py --list accounts.csv --limit 50` |
| `scripts/test-call.py` | Test single call | `python3 test-call.py --number +15551234567` |
| `scripts/daily-report.py` | Generate daily metrics | `python3 daily-report.py` |
| `scripts/kill-switch.py` | Emergency stop | `python3 kill-switch.py --activate` |
| `scripts/cost-check.py` | Check current spend | `python3 cost-check.py` |

---

## Lessons Learned
*(To be updated during operations)*

- TBD
