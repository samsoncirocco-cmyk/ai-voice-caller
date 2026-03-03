# DIRECTIVE: Voice Caller Core System (v2)

**Purpose:** Make outbound SLED calls using AI for conversations, SWAIG webhooks for data operations, rate-limit protection to prevent number blocking.

**Updated:** 2026-02-11 (battle-tested through Day 1 build)

---

## Architecture (Proven Working)

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Directives (This file + mode-specific files)   │
│ - voice-caller-core.md (you are here)                   │
│ - voice-caller-discovery.md (future)                    │
│ - voice-caller-cold-call.md (future)                    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: AI Orchestration                               │
│ - SignalWire Native AI Agent (Fabric API)               │
│ - Model: gpt-4.1-nano | ASR: deepgram:nova-3           │
│ - Voice: amazon.Matthew                                 │
│ - Calls SWAIG functions during conversation             │
└─────────────────────────────────────────────────────────┘
                            │
                     SWAIG HTTP POST
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Execution (Google Cloud Functions)              │
│ - swaigWebhook: save_contact, log_call, score_lead      │
│ - Firestore: contacts, call_logs, lead_scores           │
│ - Retry logic + emergency logging                       │
└─────────────────────────────────────────────────────────┘
```

---

## Critical: SignalWire API Guide (Learned the Hard Way)

### What WORKS for outbound calls

**Compatibility API + Agent URL:**
```
POST https://{space}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json
Auth: Basic (project_id:auth_token)
Body (form-encoded):
  From=+16028985026
  To=+1XXXXXXXXXX
  Url=https://{space}/api/ai/agent/{agent_id}
```

This is the ONLY proven method. The agent URL is internal to SignalWire (returns 404 when fetched directly via curl, but works when SignalWire's call engine fetches it).

### What DOES NOT work

| Approach | Result | Why |
|----------|--------|-----|
| Calling API (`/api/calling/calls`) with inline SWML | Returns 200, call never materializes | Silently drops calls with `ai` block in SWML |
| Calling API with `params.url` pointing to SWML host | Returns 200, call never materializes | Same issue |
| Calling API with top-level `swml` object | Returns 200, call never materializes | Same issue |
| Compatibility API with `Swml` param | 422 error | Not a valid parameter |
| Compatibility API with `Url` pointing to JSON SWML host | Instant failure (0 dur, no SIP) | Expects LaML XML, not SWML JSON |
| cXML LaML does NOT have AI verbs | N/A | No `<AI>` or `<Connect>` to SWML from LaML |

### Fabric API patterns

| Operation | Endpoint | Method |
|-----------|----------|--------|
| List resources | `GET /api/fabric/resources` | Works |
| Get resource by ID | `GET /api/fabric/resources/{id}` | Works |
| Create AI agent | `POST /api/fabric/resources/ai_agents` | Works |
| Delete resource | `DELETE /api/fabric/resources/{id}` | Works (204) |
| Update resource | `PUT/PATCH /api/fabric/resources/{id}` | **404 - NOT SUPPORTED** |

**To update an agent:** Delete and recreate. The agent gets a new `agent_id` each time.

### Agent creation payload (flat structure, NOT nested in `ai_agent`):
```json
{
  "name": "Agent Name (must be unique in project)",
  "prompt": { "text": "...", "confidence": 0.6, "temperature": 0.3 },
  "post_prompt": { "text": "..." },
  "params": { "ai_model": "gpt-4.1-nano", "direction": "outbound", ... },
  "languages": [{ "code": "en-US", "provider": "amazon", "voice": "amazon.Matthew:standard:en-US" }],
  "SWAIG": { "functions": [...] }
}
```

---

## Rate-Limit Protection (CRITICAL)

### Failure patterns

| Pattern | Meaning | Action |
|---------|---------|--------|
| `status=failed, duration=0, sip=None` | Platform-level block | STOP. Cooldown 5+ minutes |
| `status=failed, duration=0, sip=500` | Carrier rejection | Intermittent. Retry after 60s |
| `status=failed, duration=1-2s, sip=None` | Call connected but SWML parse error | Check agent config |
| `status=completed, duration>0` | Success | Continue normally |

### Enforced limits (in `config/signalwire.json`)

```json
"rate_limits": {
  "min_interval_seconds": 30,
  "max_calls_per_hour": 20,
  "max_calls_per_day": 100,
  "cooldown_on_failure_seconds": 300,
  "max_consecutive_failures": 3
}
```

### How the rate limiter works (`make_call_v4.py`)

1. Before each call: Check Firestore `call_rate/state` document
2. Enforce minimum interval (30s between calls)
3. Enforce hourly limit (20/hr)
4. Enforce daily limit (100/day)
5. After 3 consecutive failures: automatic 5-minute cooldown
6. After each call: verify status, record success/failure
7. Platform-block pattern detected = failure count incremented

### Recovery from rate limiting

```bash
# Check if number is unblocked
python3 make_call_v4.py --check

# View rate limit status
python3 make_call_v4.py --status
```

---

## SWAIG Webhook Server

**Deployed:** `https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook`
**Source:** `execution/swaig_server.py`
**Runtime:** Python 3.12, Google Cloud Functions gen2

### Request format (from SignalWire)

```json
{
  "function": "save_contact",
  "argument": {
    "parsed": [{"name": "John", "phone": "+15551234567", "account": "School"}],
    "raw": "{\"name\":\"John\",...}"
  },
  "ai_session_id": "session-uuid",
  "caller_id_num": "+16028985026",
  "project_id": "project-uuid"
}
```

### Response format (to SignalWire)

```json
{"response": "Text the AI will speak to the caller"}
```

### Functions

| Function | Firestore Collection | Retry | Emergency Log |
|----------|---------------------|-------|---------------|
| `save_contact` | `contacts` | 3x | Yes |
| `log_call` | `call_logs` | 1x | No (best effort) |
| `score_lead` | `lead_scores` | 1x | No (graceful degrade) |

---

## Current Agent Config

- **Name:** Discovery Caller
- **Agent ID:** `e2c8a606-24ce-4392-a7a8-c11bd79a7a45`
- **Resource ID:** `067f48d2-9274-4169-b62f-a5e7b3beef97`
- **SWAIG:** save_contact, log_call (both point to swaigWebhook)
- **Created via:** `POST /api/fabric/resources/ai_agents`

---

## Self-Annealing Loop

1. **Call fails?** Check `make_call_v4.py --check` first
2. **Platform block?** Wait for cooldown, don't hammer the API
3. **Carrier block (SIP 500)?** Intermittent — wait 60s, retry once
4. **SWML parse error (1-2s duration)?** Agent config issue — check Fabric API
5. **SWAIG function fails?** Check Cloud Function logs: `gcloud functions logs read swaigWebhook --project=tatt-pro`
6. **Fix → Test → Update this directive**

---

## File Map

```
ai-voice-caller/
  config/signalwire.json          # All IDs, tokens, rate limits
  make_call_v4.py                 # Production call script (rate-limited)
  make_call_v2.py                 # Legacy (no SWAIG, no rate limit)
  execution/
    swaig_server.py               # Cloud Function (SWAIG webhook handler)
    requirements.txt              # google-cloud-firestore, functions-framework
    save_contact.py               # CLI tool (legacy, superseded by swaig_server)
    log_call.py                   # CLI tool (legacy, superseded by swaig_server)
  agents/
    discovery_agent.py            # Option 1 SDK (harvest source, not deployed)
    cold_call_agent.py            # Option 1 SDK (harvest source, not deployed)
    lead_qualification_agent.py   # Option 1 SDK (BANT scoring harvested into swaig_server)
  directives/
    voice-caller-core.md          # This file
  scripts/
    test-native-ai-agent.py       # Original working test script
```

---

## Deploy Commands

```bash
# Deploy SWAIG webhook
cd execution/
gcloud functions deploy swaigWebhook \
  --gen2 --runtime=python312 --region=us-central1 \
  --source=. --entry-point=swaig_handler \
  --trigger-http --allow-unauthenticated \
  --memory=256MB --project=tatt-pro

# Test SWAIG webhook
curl -X POST https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook \
  -H "Content-Type: application/json" \
  -d '{"function":"log_call","argument":{"parsed":[{"outcome":"refused","summary":"test"}]},"ai_session_id":"test-123"}'

# Create new agent (if needed)
curl -X POST https://6eyes.signalwire.com/api/fabric/resources/ai_agents \
  -H "Content-Type: application/json" \
  -u "{project_id}:{auth_token}" \
  -d @agent_config.json

# Delete old agent
curl -X DELETE https://6eyes.signalwire.com/api/fabric/resources/{resource_id} \
  -u "{project_id}:{auth_token}"
```

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Call completion rate | >85% | Blocked by rate limit |
| Contact save accuracy | >95% | Webhook verified via curl |
| SWAIG response time | <2s | ~500ms (Cloud Function) |
| Rate limit incidents | 0/week | 1 (Day 1 rapid testing) |

---

**Status:** Cold call SWAIG harvest complete. 6 SWAIG functions deployed. Cold Caller v1 agent created.
**Priority:** P0
**Next:** Live cold call test, campaign runner integration
