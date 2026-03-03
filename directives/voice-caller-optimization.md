# Directive: Voice Caller Optimization

## Goal
Continuously improve the AI Voice Caller through data-driven A/B testing, conversation refinement, and cost optimization. Target: 20% improvement in meeting book rate every quarter.

---

## A/B Testing Framework

### What We Can Test

| Category | Testable Elements | Impact |
|----------|-------------------|--------|
| **Opening** | Greeting style, name usage, intro length | First impression, hang-up rate |
| **Questions** | Killer question variants, discovery order | Engagement, lead scoring |
| **Voice** | Male vs. female, Neural2 vs. Studio | Trust, conversation length |
| **Pacing** | Fast vs. slow speech, pause lengths | Comprehension, hang-up rate |
| **Objection handling** | Different pivot strategies | Save rate, next-step rate |
| **Call timing** | Time of day, day of week | Answer rate, decision-maker rate |

### Test Infrastructure

**Variant Assignment:**
```python
# In webhook: assign variant based on call ID hash
def get_variant(call_id: str, test_name: str) -> str:
    """Deterministic variant assignment (50/50 split)"""
    hash_value = hashlib.md5(f"{call_id}-{test_name}".encode()).hexdigest()
    return "A" if int(hash_value, 16) % 2 == 0 else "B"
```

**Data Capture:**
```json
{
  "call_id": "abc123",
  "tests": {
    "greeting_test": "A",
    "killer_question_test": "B",
    "voice_test": "A"
  },
  "outcome": "meeting_booked",
  "duration_seconds": 185
}
```

**Analysis Query:**
```sql
SELECT 
  tests.greeting_test as variant,
  COUNT(*) as total_calls,
  COUNTIF(outcome = 'meeting_booked') / COUNT(*) as meeting_rate,
  AVG(duration_seconds) as avg_duration
FROM `tatt-pro.voice_caller.calls`
WHERE DATE(timestamp) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
GROUP BY 1
```

### Active Tests

| Test ID | Element | Variant A | Variant B | Start Date | Status |
|---------|---------|-----------|-----------|------------|--------|
| GT-001 | Greeting | "Hi, is this [Name]?" | "Hey [Name], got a minute?" | TBD | Planned |
| KQ-001 | Killer Question | "What happens to phones when internet goes down?" | "How do you handle phone outages?" | TBD | Planned |
| VC-001 | Voice | Neural2-D (male) | Studio-O (male) | TBD | Planned |

### Test Process

1. **Hypothesis:** "Shorter greeting will reduce hang-ups by 15%"
2. **Configure:** Create variants in Dialogflow, update webhook
3. **Run:** Minimum 100 calls per variant (200 total)
4. **Analyze:** Compare key metrics, check statistical significance
5. **Decide:** Winner becomes default, loser archived
6. **Document:** Update `optimization-log.md`

### Statistical Significance
Minimum sample sizes for 95% confidence:

| Base Rate | Detectable Lift | Calls Per Variant |
|-----------|-----------------|-------------------|
| 5% (meetings) | 50% relative (5%→7.5%) | 500 |
| 10% (meetings) | 30% relative (10%→13%) | 300 |
| 50% (engagement) | 10% relative (50%→55%) | 400 |

*At 100 calls/month, meaningful tests take 4-8 weeks.*

---

## Conversation Flow Improvement

### Weekly Flow Review Process

**Friday Review (30 minutes):**

1. **Pull this week's transcripts:**
   ```sql
   SELECT transcript, outcome, lead_score, duration_seconds
   FROM `tatt-pro.voice_caller.calls`
   WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   ORDER BY lead_score DESC
   LIMIT 20
   ```

2. **Identify patterns:**
   - What are callers saying that bot doesn't understand?
   - Where do conversations stall?
   - What objections are most common?
   - What questions work best?

3. **Log improvements:**
   - Add new training phrases to intents
   - Add new objection handlers
   - Refine Gemini prompts

4. **Deploy and monitor:**
   - Update Dialogflow agent
   - Watch next week's calls for improvement

### Conversation Quality Signals

| Signal | What It Means | Action |
|--------|---------------|--------|
| Hang-up in first 10s | Opening not engaging | Test new greetings |
| "What?" / "I don't understand" | Bot unclear | Improve TTS clarity, slow down |
| Long pause (>5s) | Bot/caller confused | Add clarification prompts |
| Repeated same response | Intent not recognized | Add training phrases |
| Call >5 minutes | Very engaged OR stuck | Review transcript |
| Caller asks off-topic question | Engaged but wandering | Gemini should redirect |

### Objection Library

Build and refine over time:

| Objection | Current Response | Success Rate | Improvements |
|-----------|------------------|--------------|--------------|
| "Not interested" | "Totally understand. Can I ask if it's not a fit now, or not a fit ever?" | TBD | — |
| "Just send email" | "Happy to! What email? Anything specific you'd like me to focus on?" | TBD | — |
| "Already have a solution" | "Got it. Are you happy with it, or open to seeing alternatives?" | TBD | — |
| "Who is this?" | "This is Paul from Fortinet. I work with IT leaders on voice solutions." | TBD | — |
| "How did you get my number?" | "Your organization is on our partner's list for SLED solutions." | TBD | — |

### Gemini Prompt Refinement

**Current system prompt:**
```
You are a friendly, professional sales assistant helping Paul from Fortinet. 
You're on a phone call with a potential customer. Keep responses under 30 words.
Be conversational, not robotic. If asked something you don't know, offer to 
have Paul follow up personally.

Context:
- Account: {account_name}
- Current goal: {goal}
- Conversation so far: {transcript}

Respond to: {user_input}
```

**Improvement areas:**
- Add industry context (K12, higher ed, city, county)
- Add account-specific pain points
- Add competitive intelligence (what system they likely have)
- Tune for conciseness (shorter = better for phone)

---

## Lead Scoring Refinement

### Current Scoring Model
*(See voice-caller-operations.md for point values)*

### Calibration Process (Monthly)

1. **Export scored leads from last month:**
   ```sql
   SELECT call_id, lead_score, outcome, 
     -- Check if we later booked meeting or closed deal
     (SELECT 1 FROM salesforce_opportunities 
      WHERE account_id = c.account_id 
      AND stage = 'Closed Won') as converted
   FROM `tatt-pro.voice_caller.calls` c
   WHERE DATE(timestamp) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
   ```

2. **Analyze:**
   - Are high-score leads actually converting?
   - Are any low-score leads converting (signals we're missing)?
   - What's the score threshold for actionable leads?

3. **Adjust:**
   - Increase/decrease point values based on correlation
   - Add new signals if patterns emerge
   - Remove signals that don't predict conversion

### Predictive Signals to Add

| Signal | How to Detect | Expected Value |
|--------|---------------|----------------|
| Contract renewal timing | Salesforce data | High |
| Recent RFP activity | E-Rate data | High |
| Expansion/construction | News API | Medium |
| Leadership change | LinkedIn | Medium |
| Budget cycle alignment | Calendar (Q1-Q2 for SLED) | High |

---

## Cost Optimization Strategies

### Current Cost Structure
| Component | % of Cost | Optimization Opportunity |
|-----------|-----------|--------------------------|
| Dialogflow CX | 80% | Reduce requests per call |
| Text-to-Speech | 10% | Use Neural2 vs. Studio |
| SignalWire | 3% | Reduce call duration |
| Gemini | <1% | Already minimal |
| BigQuery | 6% | Optimize queries |

### Optimization Tactics

**1. Reduce Dialogflow Requests:**
- Target: 10 → 8 requests per call (20% savings)
- How: Combine related flows, reduce back-and-forth
- Monitor: `avg_requests_per_call` metric

**2. Text-to-Speech Optimization:**
- Use Neural2 ($0.000016/char) not Studio ($0.00016/char)
- Cache common phrases (greeting, goodbye) — speak from audio file
- Keep responses short (target: <100 chars per response)

**3. Call Duration Optimization:**
- Efficient conversations = lower SignalWire cost
- Set 5-minute soft limit (bot starts wrapping up)
- Detect dead-end conversations early, exit gracefully

**4. Batch Scheduling:**
- Call during high-answer-rate times (9-11 AM)
- Avoid voicemails (wasted cost, low value)
- Use voicemail detection — hang up, don't leave message

**5. Failed Call Handling:**
- No answer after 30s → hang up (don't wait for voicemail)
- Busy signal → retry once, then queue for tomorrow
- Wrong number → mark and remove from list

### Cost Tracking Dashboard

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Cost per call | $0.78 | $0.65 | ⬜ |
| Cost per qualified lead | TBD | $10.00 | ⬜ |
| Cost per meeting booked | TBD | $25.00 | ⬜ |
| Dialogflow requests/call | 10 | 8 | ⬜ |
| Avg call duration | 3 min | 2.5 min | ⬜ |

---

## Success Metrics and KPIs

### Primary KPIs (Report Weekly)

| KPI | Definition | Target | Current |
|-----|------------|--------|---------|
| **Meeting Book Rate** | Meetings / Calls | 10% | TBD |
| **Qualified Lead Rate** | Score ≥7 / Calls | 15% | TBD |
| **Cost Per Meeting** | Total Cost / Meetings | <$25 | TBD |
| **Conversation Rate** | Calls >30s / All Calls | 60% | TBD |

### Secondary KPIs (Report Monthly)

| KPI | Definition | Target | Current |
|-----|------------|--------|---------|
| **Answer Rate** | Answered / Attempted | 40% | TBD |
| **Intent Recognition** | Understood / Total Intents | 80% | TBD |
| **Avg Call Duration** | Sum(duration) / Calls | 2.5 min | TBD |
| **Objection Save Rate** | Recovered / Objections | 20% | TBD |
| **Follow-up Conversion** | Meetings from follow-ups | 15% | TBD |

### Dashboard Requirements

**Real-Time View:**
- Calls in progress
- Today's calls (total, successful, failed)
- Current spend vs. daily limit

**Daily View:**
- Calls by outcome (pie chart)
- Lead scores distribution
- Hourly call volume (best times)
- Error rate

**Weekly View:**
- KPI trends (line charts)
- A/B test results
- Top objections (word cloud)
- Pipeline value generated

### Monthly Report Template

```markdown
# Voice Caller Monthly Report - [MONTH YEAR]

## Summary
- Total Calls: [X]
- Meetings Booked: [Y] ([Z]% rate)
- Qualified Leads: [A]
- Total Cost: $[B]
- Cost Per Meeting: $[C]

## Key Wins
- [Notable success]
- [Best performing day/time]
- [Effective objection handling]

## Challenges
- [What didn't work]
- [Technical issues]

## Optimizations Made
- [A/B test results]
- [Flow improvements]
- [Cost savings]

## Next Month Focus
- [Priority 1]
- [Priority 2]
- [Priority 3]
```

---

## Continuous Improvement Cycle

```
┌──────────────────────────────────────────────────────────────┐
│                        WEEKLY CYCLE                          │
└──────────────────────────────────────────────────────────────┘

Monday-Thursday: Execute calls, collect data
         │
         ▼
Friday: Review transcripts, analyze metrics
         │
         ▼
Friday: Identify 1-2 improvements
         │
         ▼
Friday: Deploy updates to Dialogflow/webhooks
         │
         ▼
Next Week: Measure impact, repeat

┌──────────────────────────────────────────────────────────────┐
│                       MONTHLY CYCLE                          │
└──────────────────────────────────────────────────────────────┘

Week 1-3: Run A/B tests, collect data
         │
         ▼
Week 4: Analyze test results, declare winners
         │
         ▼
Week 4: Update lead scoring model
         │
         ▼
Week 4: Publish monthly report
         │
         ▼
Week 4: Plan next month's tests
         │
         ▼
Next Month: Repeat with new hypotheses
```

---

## Optimization Log

Track all changes and their impact:

| Date | Change | Hypothesis | Result | Impact |
|------|--------|------------|--------|--------|
| TBD | — | — | — | — |

---

## Edge Cases

- **No clear winner in A/B test:** Run for another 100 calls before deciding
- **Winner has worse secondary metrics:** Weigh primary vs. secondary, may keep loser
- **External factor skewing results:** (Holiday, news event) — exclude those days from analysis
- **Diminishing returns:** Focus on new areas, not over-optimizing existing

---

## Lessons Learned
*(To be updated during optimization)*

- TBD
