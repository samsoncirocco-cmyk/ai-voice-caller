# Failure Modes & Mitigation Strategies

## Overview
Comprehensive analysis of all possible failure points in the AI Voice Caller system, with mitigation strategies and recovery procedures.

## CRITICAL FAILURE MODES

### 1. Dialogflow CX API Unavailable
**Symptom:** 503 Service Unavailable or timeout  
**Impact:** All calls fail  
**Likelihood:** Low (Google SLA: 99.95%)  
**Mitigation:**
- Implement exponential backoff retry (max 3 attempts)
- Queue failed calls for retry after 5 minutes
- Send alert to monitoring dashboard
- Fallback to recorded message: "System temporarily unavailable"

**Recovery:**
```python
from google.api_core import retry

@retry.Retry(predicate=retry.if_transient_error, timeout=30.0)
def make_api_call(client, request):
    return client.detect_intent(request=request)
```

### 2. SignalWire Connection Failure
**Symptom:** Webhook not responding, no call audio  
**Impact:** Calls connect but can't communicate  
**Likelihood:** Medium (depends on network)  
**Mitigation:**
- Health check endpoint (`/health`) that SignalWire pings every 60s
- Auto-restart webhook server on 3 consecutive failures
- Backup webhook URL (secondary Cloud Function)
- SMS alert to admin on failure

**Recovery:**
- Primary webhook: `https://us-central1-tatt-pro.cloudfunctions.net/dialogflow-webhook`
- Backup webhook: `https://us-east1-tatt-pro.cloudfunctions.net/dialogflow-webhook-backup`

### 3. Regional Endpoint Misconfiguration
**Symptom:** 400 error, "Please refer to docs to find correct endpoint"  
**Impact:** All API calls fail  
**Likelihood:** Low (fixed in code)  
**Mitigation:**
- Always use `ClientOptions(api_endpoint=f"{LOCATION}-dialogflow.googleapis.com")`
- Validate endpoint in startup self-test
- Environment variable override for testing

**Prevention:**
```python
# ALWAYS use regional endpoint
API_ENDPOINT = f"{LOCATION}-dialogflow.googleapis.com"
client_options = ClientOptions(api_endpoint=API_ENDPOINT)
client = dialogflow.SessionsClient(client_options=client_options)
```

### 4. TTS Voice Not Available
**Symptom:** Call connects but no audio or robotic voice  
**Impact:** Poor caller experience  
**Likelihood:** Low  
**Mitigation:**
- Validate voice configuration on startup
- Fallback to default voice if configured voice fails
- Test voice synthesis before production deployment

**Fallback Chain:**
1. Primary: `en-US-Neural2-J` (Male, configured)
2. Fallback: `en-US-Standard-D` (Male, basic)
3. Last resort: Default system voice

### 5. Session State Corruption
**Symptom:** Bot repeats itself, forgets context, loops  
**Impact:** Poor caller experience, calls may hang  
**Likelihood:** Low  
**Mitigation:**
- Session timeout after 30 minutes of inactivity
- Max turn limit (100 turns) before forced end
- Context validation on each turn
- Manual session reset endpoint

**Detection:**
```python
# Detect conversation loops
if len(conversation_history) > 5:
    last_5 = conversation_history[-5:]
    if len(set(last_5)) == 1:
        # Bot is repeating - reset session
        force_end_call()
```

### 6. Rate Limiting / Quota Exceeded
**Symptom:** 429 Too Many Requests or quota errors  
**Impact:** Some calls fail during high volume  
**Likelihood:** Medium (during campaigns)  
**Mitigation:**
- Monitor quota usage in real-time
- Implement call queue with rate limiting
- Request quota increase before campaigns
- Graceful degradation: queue calls, process later

**Limits (Dialogflow CX):**
- Queries per minute: 1,200 (default)
- Concurrent sessions: 500 (default)
- Quota increase: Request via Google Cloud Console

### 7. Authentication Failure
**Symptom:** 401 Unauthorized, 403 Forbidden  
**Impact:** All API calls fail  
**Likelihood:** Low (ADC configured)  
**Mitigation:**
- Validate credentials on startup
- Auto-refresh service account keys
- Alert on auth failure
- Fallback to backup service account

**Health Check:**
```python
def validate_auth():
    try:
        client = dialogflow.AgentsClient(client_options=get_client_options())
        agent = client.get_agent(name=AGENT_NAME)
        return True
    except Exception as e:
        alert_admin(f"Auth failure: {e}")
        return False
```

### 8. Firestore Logging Failure
**Symptom:** Call completes but not logged  
**Impact:** Lost analytics, no audit trail  
**Likelihood:** Medium  
**Mitigation:**
- Log to Firestore asynchronously (don't block call)
- Fallback to local file logging if Firestore unavailable
- Batch upload failed logs every hour
- Alert on logging failure rate > 5%

**Fallback:**
```python
try:
    log_to_firestore(call_data)
except Exception as e:
    log_to_file(call_data)  # Fallback
    scheduled_retry_queue.add(call_data)
```

## MODERATE FAILURE MODES

### 9. Page Transition Failure
**Symptom:** Bot stuck on one page, doesn't move forward  
**Impact:** Call hangs, poor experience  
**Likelihood:** Low (flow tested)  
**Mitigation:**
- Timeout on each page (30 seconds max)
- Explicit transition handlers for all expected inputs
- Fallback transition on unmatched input
- Manual override: "Transfer to human" keyword

### 10. Malformed Input Handling
**Symptom:** Crashes on special characters, very long input  
**Impact:** Individual call fails  
**Likelihood:** Low (tested in stress tests)  
**Mitigation:**
- Input sanitization before sending to Dialogflow
- Max input length limit (1000 chars)
- Graceful error handling on API exceptions
- Log malformed inputs for analysis

**Input Sanitization:**
```python
def sanitize_input(text):
    # Remove control characters
    text = ''.join(char for char in text if char.isprintable())
    # Limit length
    text = text[:1000]
    # Remove excessive whitespace
    text = ' '.join(text.split())
    return text
```

### 11. Language Detection Failure
**Symptom:** Non-English caller gets English-only response  
**Impact:** Poor experience for non-English speakers  
**Likelihood:** Medium (if targeting multilingual regions)  
**Mitigation:**
- Detect language in first 2 turns
- Offer language selection menu
- Gracefully decline non-English: "Press 1 for English, Presione 2 para Español"
- Transfer to human if language mismatch

### 12. Call Quality Issues
**Symptom:** Choppy audio, dropped words, latency  
**Impact:** Poor caller experience  
**Likelihood:** Medium (network-dependent)  
**Mitigation:**
- Use SignalWire HD Voice codec
- Monitor latency metrics
- Alert on average latency > 2 seconds
- Optimize webhook response time (< 500ms target)

**Latency Budget:**
- Speech-to-Text: 300-500ms
- Dialogflow API: 200-400ms
- Text-to-Speech: 300-500ms
- Network round-trip: 100-200ms
- **Total target: < 1.5 seconds**

### 13. Webhook Timeout
**Symptom:** SignalWire times out waiting for response  
**Impact:** Call drops or repeats prompt  
**Likelihood:** Medium  
**Mitigation:**
- Set webhook timeout to 10 seconds max
- Optimize Dialogflow API call (< 1 second target)
- Return partial response if Dialogflow slow
- Alert on timeout rate > 1%

### 14. Cost Overrun
**Symptom:** Unexpected high bill  
**Impact:** Budget exceeded  
**Likelihood:** Medium (during campaigns)  
**Mitigation:**
- Set daily call limit (budget / cost per call)
- Alert on cost > 80% of budget
- Auto-pause campaigns at 100% budget
- Monitor cost per call in real-time

**Budget Control:**
```python
DAILY_BUDGET = 50.00  # $50/day
COST_PER_CALL = 0.07  # ~$0.07 per call
MAX_CALLS_PER_DAY = int(DAILY_BUDGET / COST_PER_CALL)  # ~714 calls

if calls_today >= MAX_CALLS_PER_DAY:
    pause_campaign()
    alert_admin("Daily call limit reached")
```

## MINOR FAILURE MODES

### 15. Metadata Logging Incomplete
**Symptom:** Some fields missing in logs  
**Impact:** Reduced analytics quality  
**Likelihood:** Medium  
**Mitigation:**
- Required fields validation
- Default values for optional fields
- Schema validation before logging

### 16. Time Zone Mismatch
**Symptom:** Calls at wrong time (e.g., 3am local time)  
**Impact:** Angry recipients, low conversion  
**Likelihood:** Medium  
**Mitigation:**
- Always use recipient's time zone for scheduling
- Respect DNC hours (9am-9pm local time)
- Daylight saving time handling

### 17. Phone Number Validation Failure
**Symptom:** Invalid numbers attempted  
**Impact:** Wasted API calls, cost  
**Likelihood:** Medium  
**Mitigation:**
- Validate E.164 format before calling
- Check against DNC list
- Skip landlines if mobile-only campaign

### 18. Conversation Loop Detection
**Symptom:** Bot and caller repeat same exchange  
**Impact:** Poor experience, wasted time  
**Likelihood:** Low  
**Mitigation:**
- Detect loops (3+ identical exchanges)
- Force transition or transfer to human
- Log for flow improvement

## DISASTER RECOVERY

### Total System Failure
**Scenario:** Everything down (Google, SignalWire, all APIs)  
**Response:**
1. Pause all outbound calls immediately
2. Set inbound calls to voicemail
3. SMS blast to admins
4. Status page update
5. Incident report within 1 hour

### Data Loss
**Scenario:** Firestore corruption or deletion  
**Response:**
1. Restore from daily backup (last 30 days retained)
2. Replay call logs from SignalWire webhook archive
3. Validate data integrity
4. Resume operations

### Security Breach
**Scenario:** Unauthorized access to credentials  
**Response:**
1. Rotate all API keys immediately (SignalWire, Google Cloud)
2. Audit access logs
3. Lock down agent (disable all flows)
4. Forensic investigation
5. Report to stakeholders

## MONITORING & ALERTING

### Critical Alerts (Page Immediately)
- API authentication failure
- 5+ consecutive call failures
- Average latency > 5 seconds
- Cost > 150% of daily budget
- Security event detected

### Warning Alerts (Email)
- API error rate > 5%
- Call success rate < 90%
- Average latency > 2 seconds
- Cost > 80% of daily budget
- Quota usage > 80%

### Info Alerts (Dashboard Only)
- Daily summary report
- Weekly performance metrics
- Monthly cost analysis
- Call quality trends

## TESTING STRATEGY

### Pre-Production Testing
1. **Unit tests:** All API clients, input sanitization
2. **Integration tests:** Full call flow (recorded audio)
3. **Stress tests:** 10 concurrent calls, 100-turn conversation
4. **Failure injection:** Simulate API failures, network issues
5. **Security tests:** SQL injection, XSS, malformed input

### Production Monitoring
1. **Health checks:** Every 60 seconds
2. **Synthetic calls:** Every 15 minutes (test number)
3. **Latency monitoring:** Real-time dashboard
4. **Cost tracking:** Updated hourly
5. **Error rate tracking:** Alert on spikes

### Incident Response
1. **Detection:** Automated alerts + manual reports
2. **Triage:** Classify severity (Critical/Major/Minor)
3. **Mitigation:** Apply immediate fix or workaround
4. **Communication:** Update status page, notify stakeholders
5. **Root cause analysis:** Within 24 hours of resolution
6. **Prevention:** Update code, tests, monitoring

## RUNBOOK LINKS

- **Incident Response:** `/docs/incident-response.md`
- **API Troubleshooting:** `/docs/api-troubleshooting.md`
- **Cost Management:** `/docs/cost-management.md`
- **Security Procedures:** `/docs/security.md`

## REVISION HISTORY

- **2026-02-10:** Initial failure modes analysis (v1.0)
- **TBD:** Update after first production incident
