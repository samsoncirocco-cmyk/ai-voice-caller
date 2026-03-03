# Architecture: AI Outbound Calling with SignalWire

**Domain:** AI voice agent outbound calling system
**Researched:** 2026-02-17
**Confidence:** HIGH (verified with official docs, existing codebase, and production learning)

## Executive Summary

An AI outbound calling system using SignalWire requires orchestrating **four distinct service tiers**: a call initiation mechanism, a telephony/AI runtime (SignalWire platform), webhook handlers for AI function calls (SWAIG), and persistent data storage. The critical architectural insight is that **SignalWire Agents SDK is NOT required for outbound calling** — you can use the REST API with inline SWML to achieve the same AI conversation capabilities.

The architecture discovered through brownfield analysis reveals a **hybrid approach**: REST API call initiation + inline SWML configuration + cloud-hosted SWAIG webhooks + Firestore data layer. This is more scalable than running a persistent local server for simple outbound campaigns.

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Campaign Orchestrator                         │
│                   (Python script on macpro server)                   │
│                                                                       │
│  • Reads targets from CSV or Firestore                              │
│  • Rate limiting & retry logic                                       │
│  • Makes REST API calls to initiate outbound dials                  │
│  • Monitors call status via polling                                 │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 │ POST /api/calling/calls
                 │ {command: "dial", params: {from, to, swml: "..."}}
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SignalWire Platform                             │
│                    (Managed SaaS Service)                            │
│                                                                       │
│  • PSTN/SIP telephony layer                                         │
│  • AI runtime (ASR, LLM, TTS orchestration)                         │
│  • SWML interpreter (executes inline config)                        │
│  • Sub-500ms latency AI voice engine                                │
│  • Barge-in, turn detection, conversation state                     │
└─────┬───────────────────────────────────────────────────────┬───────┘
      │                                                         │
      │ AI decides to call function                            │
      │ POST to SWAIG webhook                                  │
      │                                                         │
      ▼                                                         ▼
┌─────────────────────────────────────┐      ┌─────────────────────────────────┐
│   SWAIG Webhook Handler (GCF)       │      │  Optional SWML Endpoint (GCF)   │
│                                     │      │                                 │
│  • save_contact                     │      │  • Returns SWML JSON for        │
│  • log_call                         │      │    Compatibility API calls      │
│  • score_lead                       │      │  • Fallback for non-inline flow │
│  • schedule_callback                │      │  • Same config as inline SWML   │
│  • send_info_email                  │      └─────────────────────────────────┘
│                                     │
│  Functions receive call context +   │
│  AI-extracted params, return JSON   │
└────────┬────────────────────────────┘
         │
         │ Write data
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Firestore (GCP)                                │
│                                                                       │
│  • contacts — contact info extracted during calls                   │
│  • call_logs — call outcomes, summaries, timestamps                 │
│  • lead_scores — lead qualification scores                          │
│  • callbacks — scheduled callback queue                             │
│  • email-queue — follow-up emails to send                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Boundaries

| Component | Responsibility | Communicates With | Deployment |
|-----------|----------------|-------------------|------------|
| **Campaign Runner** | Read targets, initiate calls, track status, rate limiting | SignalWire REST API, Firestore | Python script on macpro (can be Lambda/GCF) |
| **SignalWire Platform** | Handle telephony, run AI conversations, execute SWML | Campaign Runner (receives calls), SWAIG Webhook (sends function calls) | Managed SaaS |
| **SWAIG Webhook** | Execute AI function calls, persist data | Firestore (writes), SignalWire (receives/responds) | Google Cloud Function |
| **SWML Endpoint** (optional) | Serve SWML config for Compatibility API calls | SignalWire (responds to requests) | Google Cloud Function |
| **Firestore** | Persist contacts, logs, callbacks, emails | SWAIG Webhook (writes), Campaign Runner (reads/writes) | Managed database |
| **Dashboard** (optional) | Visualize campaign metrics, call status | Firestore (reads) | Flask app on macpro |

## Data Flow: CSV Target → AI Conversation → Firestore Log

### Phase 1: Call Initiation
1. **Campaign Runner** reads next target from CSV or Firestore queue
2. Checks rate limit (platform safety: 1 call/5 sec, aggressive: 1 call/2 sec)
3. Builds inline SWML JSON containing:
   - AI agent prompt (persona, goals)
   - Static greeting (first words AI speaks)
   - Voice/TTS configuration
   - SWAIG function definitions (6 functions, all pointing to GCF webhook)
4. Makes REST API call:
   ```
   POST https://{space}.signalwire.com/api/calling/calls
   Body: {
     "command": "dial",
     "params": {
       "from": "+14806024668",
       "to": target_phone,
       "swml": "<inline SWML JSON as string>"
     }
   }
   ```
5. Receives call ID in response
6. Begins polling `/api/laml/.../Calls/{call_id}.json` for status every 5s

### Phase 2: AI Conversation (SignalWire Platform)
1. SignalWire places outbound PSTN call to target
2. On answer, SWML interpreter reads inline config
3. AI speaks static greeting immediately (no wait)
4. ASR (Deepgram Nova-3) transcribes target's speech
5. LLM (OpenAI GPT-4.1) generates response
6. TTS (Amazon Polly Matthew) synthesizes speech
7. AI conversation continues with sub-500ms turn latency
8. When AI determines it needs external data or actions:
   - AI calls SWAIG function (e.g., `save_contact`, `log_call`)
   - SignalWire POSTs to SWAIG webhook with function name + params
   - Webhook executes logic, writes to Firestore, returns result
   - AI incorporates result into conversation

### Phase 3: Data Persistence (SWAIG → Firestore)
1. AI calls `save_contact` during conversation:
   - Webhook writes to `contacts` collection
   - Params: name, email, phone, title, organization
2. AI calls `score_lead` if qualified:
   - Webhook writes to `lead_scores` collection
   - Params: score (1-10), reason, qualified (bool)
3. AI calls `schedule_callback` if target requests follow-up:
   - Webhook writes to `callbacks` collection with due date
   - Params: callback_date, callback_time, notes
4. AI calls `send_info_email` if target wants materials:
   - Webhook writes to `email-queue` collection
   - Params: email, topic
5. At end of call, AI calls `log_call`:
   - Webhook writes to `call_logs` collection
   - Params: outcome, summary, duration_estimate

### Phase 4: Post-Call Processing
1. Campaign Runner's status polling detects call completion
2. Reads call status: `completed` / `failed` / `busy` / `no-answer`
3. Reads duration: >5s suggests successful AI dialogue
4. Logs result to Firestore or local campaign tracking
5. Waits for rate limit interval
6. Proceeds to next target

## Key Architectural Decisions

### Decision 1: REST API + Inline SWML vs. Agents SDK

**Context:** SignalWire offers two paths for AI calling:
1. **Agents SDK** — Python server that responds to webhooks from SignalWire
2. **REST API + Inline SWML** — Direct API call with config embedded

**Chosen:** REST API + Inline SWML

**Rationale:**
- **Simplicity:** No persistent server required. Campaign runner is a simple script.
- **Scalability:** Each call is stateless. Can run campaign from Lambda/cron without managing server lifecycle.
- **Existing Infrastructure:** SWAIG webhooks already deployed on GCF. No need to add local server + ngrok tunnel.
- **Brownfield Fit:** Existing scripts (v4, v5) use REST API pattern. Agents SDK would require full rewrite.

**Trade-offs:**
- **Pro:** Easier deployment, no ngrok dependency, serverless-friendly
- **Con:** Less flexibility for complex multi-agent routing (not needed for this use case)

### Decision 2: Calling API vs. Compatibility API

**Context:** SignalWire has three REST APIs:
1. **Calling API** (`/api/calling/calls`) — Native SWML support with inline `swml` param
2. **Compatibility API** (`/api/laml/.../Calls`) — Twilio-compatible, expects cXML via `Url` param
3. **Agents SDK** (not REST) — Python framework

**Chosen:** Calling API with inline SWML (primary), Compatibility API with SWML GCF endpoint (fallback)

**Rationale:**
- **Root Cause Fix:** Compatibility API with `Url=/api/ai/agent/{id}` silently fails because agent endpoints don't return valid cXML. This caused 100% silent call failures in production.
- **Inline SWML Works:** Calling API accepts full SWML config as JSON string in request body. No separate HTTP round-trip needed.
- **Fallback Safety:** If Calling API rate-limits or rejects, can fall back to Compatibility API with `Url=https://...gcf.../swmlOutbound` (returns SWML JSON, not cXML, but sometimes works)

**Trade-offs:**
- **Pro:** Direct control, no Url parsing, no 404 risks from bad agent URLs
- **Con:** Call IDs from Calling API don't always appear in Compatibility API status endpoint (different ID namespaces)

### Decision 3: SWAIG Webhooks on GCF (not local server)

**Context:** SWAIG functions can be:
1. Webhook URLs (custom HTTP endpoints)
2. DataMap tools (REST API calls on SignalWire's server)
3. Local Agents SDK server routes

**Chosen:** Webhook URLs on Google Cloud Functions

**Rationale:**
- **Already Deployed:** 6 SWAIG functions already live on GCF from previous iteration
- **No ngrok Needed:** Cloud-hosted webhooks don't require tunneling
- **Persistent:** Unlike local server (macpro has flaky SSH), GCF is always reachable
- **Firestore Access:** GCF functions in `tatt-pro` project have native Firestore access

**Trade-offs:**
- **Pro:** Zero local server maintenance, survives macpro reboots, production-grade uptime
- **Con:** GCF cold starts (~200-500ms), but tolerable for SWAIG calls during live conversation

### Decision 4: Firestore for Data Layer

**Context:** Data storage options:
1. Firestore (NoSQL, GCP-native)
2. PostgreSQL/MySQL (relational)
3. SQLite (local file)

**Chosen:** Firestore

**Rationale:**
- **Already Provisioned:** Project `tatt-pro` has Firestore enabled, collections already exist
- **GCF Integration:** SWAIG webhook functions have zero-config Firestore access
- **Schema Flexibility:** NoSQL fits SWAIG's dynamic params (different functions write different fields)
- **Real-time Updates:** Dashboard can subscribe to Firestore changes for live campaign monitoring

**Trade-offs:**
- **Pro:** No schema migrations, GCP-native, scales automatically
- **Con:** No JOINs (acceptable for this use case — no complex relational queries needed)

### Decision 5: Campaign Runner on macpro (not serverless)

**Context:** Campaign orchestration can run:
1. Local script on macpro
2. Lambda/GCF with Cloud Scheduler triggers
3. Kubernetes cron job

**Chosen:** Local script on macpro (Phase 1), migrate to Cloud Scheduler + GCF later (Phase 2+)

**Rationale:**
- **Brownfield:** Existing `campaign_runner.py` already runs on macpro
- **Rapid Iteration:** Easier to test/debug locally during initial rollout
- **SSH Recovery:** macpro SSH is currently down, but script can be deployed when access returns
- **Future-Proof:** Script is stateless, easy to move to GCF + Cloud Scheduler when stable

**Trade-offs:**
- **Pro:** Faster initial deployment, easier debugging
- **Con:** Requires macpro uptime (mitigated by systemd/supervisor), not as resilient as cloud-native

## Patterns to Follow

### Pattern 1: Inline SWML for Outbound Calls

**What:** Embed full SWML config directly in REST API call, avoiding separate SWML endpoint.

**When:** Any outbound call initiation via Calling API.

**Example:**
```python
swml = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {"answer": {}},  # CRITICAL: Must answer before AI starts
            {
                "ai": {
                    "prompt": {"text": "You are Matt, calling from Fortinet..."},
                    "params": {
                        "direction": "outbound",
                        "wait_for_user": False,
                        "static_greeting": "Hi! This is Matt from Fortinet...",
                        "outbound_attention_timeout": 30000
                    },
                    "voice": "amazon.Matthew:standard:en-US",
                    "SWAIG": {
                        "functions": [
                            {
                                "function": "save_contact",
                                "description": "Save contact info",
                                "parameters": {...},
                                "web_hook_url": "https://...gcf.../swaigWebhook"
                            }
                        ]
                    }
                }
            }
        ]
    }
}

response = requests.post(
    "https://{space}.signalwire.com/api/calling/calls",
    json={
        "command": "dial",
        "params": {
            "from": "+14806024668",
            "to": target_phone,
            "swml": json.dumps(swml)
        }
    },
    auth=(project_id, auth_token)
)
```

**Why:** Eliminates HTTP round-trip for SWML fetch, reduces failure modes (no 404s from bad URLs), keeps config co-located with call logic.

### Pattern 2: Status Polling with Exponential Backoff

**What:** Poll Compatibility API for call status after initiating via Calling API, with increasing intervals.

**When:** After every outbound call, to detect completion and measure duration.

**Example:**
```python
def poll_call_status(call_id, max_polls=12, base_interval=5):
    for i in range(max_polls):
        time.sleep(base_interval * (1.2 ** i))  # Exponential backoff
        resp = requests.get(
            f"https://{space}.signalwire.com/api/laml/.../Calls/{call_id}.json",
            auth=(project_id, auth_token)
        )
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status in ("completed", "failed", "busy", "no-answer"):
                return status
    return "timeout"
```

**Why:** Calling API call IDs may not immediately appear in Compatibility API namespace. Exponential backoff reduces API load while ensuring we catch completion.

### Pattern 3: Rate Limit Guardian

**What:** Enforce minimum interval between outbound calls to avoid platform-level rate limiting.

**When:** Campaign runner loop, between each call initiation.

**Example:**
```python
RATE_LIMIT_SECONDS = 5  # Conservative: 1 call per 5 seconds
last_call_time = 0

def make_call_with_rate_limit(target):
    global last_call_time
    elapsed = time.time() - last_call_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)

    result = make_call(target)
    last_call_time = time.time()
    return result
```

**Why:** SignalWire has undocumented platform-level rate limiting. Rapid calls (e.g., 3 calls in 10 seconds) trigger SIP 500 blocks lasting 2-3 hours. Rate limiting prevents this.

### Pattern 4: SWAIG Function Idempotency

**What:** SWAIG webhook handlers should be idempotent — calling twice with same params produces same result.

**When:** All SWAIG function implementations.

**Example:**
```python
@functions_framework.http
def swaig_webhook(request):
    data = request.get_json()
    function = data["function"]

    if function == "save_contact":
        # Upsert, not insert — overwrites if phone already exists
        db.collection("contacts").document(data["phone"]).set(data, merge=True)
        return jsonify({"response": "Contact saved"})
```

**Why:** SignalWire may retry SWAIG calls on network hiccups. Idempotency prevents duplicate data (e.g., double-logging calls, duplicate contacts).

### Pattern 5: Static Greeting for Outbound

**What:** Always include `static_greeting` param in AI config for outbound calls.

**When:** All outbound AI conversations.

**Example:**
```python
"params": {
    "direction": "outbound",
    "wait_for_user": False,
    "static_greeting": "Hi! This is Matt calling from Fortinet...",
    "outbound_attention_timeout": 30000
}
```

**Why:** Without `static_greeting`, AI waits for target to speak first. On outbound calls, target answers and says nothing → awkward silence. Static greeting ensures AI speaks immediately after answer.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Using Agent Dashboard URLs as Call Endpoints

**What:** Setting `Url=/api/ai/agent/{agent_id}` in Compatibility API calls.

**Why Bad:** Agent endpoints return 404 or non-XML responses. Compatibility API expects cXML. Result: SIP 500 or silent calls (0 duration).

**Instead:** Use Calling API with inline SWML, or point `Url` at a GCF that returns valid cXML (with `<Connect><AI>` verb).

### Anti-Pattern 2: Omitting `answer` Before `ai` in SWML

**What:** SWML sections like `{"main": [{"ai": {...}}]}` without preceding `{"answer": {}}`.

**Why Bad:** SignalWire may not answer the call before starting AI. Results in 1-2 second calls with no audio.

**Instead:** Always structure as `{"main": [{"answer": {}}, {"ai": {...}}]}`.

### Anti-Pattern 3: Rapid Successive Calls Without Rate Limiting

**What:** Placing calls in a tight loop (e.g., 10 calls in 30 seconds).

**Why Bad:** Triggers platform-level rate limiting. Subsequent calls fail with SIP 500 or 0 duration, blocking all calls for 2-3 hours.

**Instead:** Enforce minimum 2-5 second intervals between calls. Use `time.sleep()` after each call.

### Anti-Pattern 4: Polling Call Status Immediately After Initiation

**What:** Polling `/api/laml/.../Calls/{call_id}.json` within 1 second of call placement.

**Why Bad:** Call IDs from Calling API may not propagate to Compatibility API namespace instantly. Early polls return 404.

**Instead:** Wait 3-5 seconds before first poll, use exponential backoff.

### Anti-Pattern 5: Hardcoding Phone Numbers in SWML

**What:** Embedding target phone numbers in SWML config stored in Fabric or GCF endpoints.

**Why Bad:** Static SWML can only call one number. Campaign runner can't dynamically select targets.

**Instead:** Use inline SWML in Calling API requests, generated per-target at runtime.

## Build Order and Dependencies

### Phase 1: Core Calling Infrastructure (Week 1)
**Goal:** Place a single outbound AI call that speaks and logs results.

**Components:**
1. SWML inline config builder (Python function)
2. Calling API client (REST call wrapper)
3. Single-target test script

**Dependencies:**
- SignalWire credentials (project ID, auth token)
- One phone number (already have: +14806024668)
- SWAIG webhook already deployed (already exists)

**Success Criteria:**
- One call to personal number results in AI speaking greeting
- Call duration >10 seconds
- AI can call `log_call` SWAIG function successfully

**Risks:**
- Calling API may reject inline SWML (fallback: Compatibility API + GCF SWML endpoint)

---

### Phase 2: Campaign Runner (Week 2)
**Goal:** Dial a list of targets from CSV, track results.

**Components:**
1. CSV parser
2. Rate-limited call loop
3. Status polling + result logging
4. Resume-from-checkpoint (handle interruptions)

**Dependencies:**
- Phase 1 working
- `arizona-sled-targets.csv` (already exists)
- Firestore write access for campaign tracking

**Success Criteria:**
- Campaign script dials 10 targets sequentially
- Rate limiting prevents platform blocks
- Script resumes from last position if interrupted

**Risks:**
- Rate limiting threshold unknown (mitigate: start conservative at 1 call/5 sec)

---

### Phase 3: SWAIG Function Expansion (Week 2-3)
**Goal:** Enable all 6 SWAIG functions, ensure data persistence works.

**Components:**
1. Verify all 6 SWAIG functions deployed
2. Test each function with live call
3. Validate Firestore writes

**Dependencies:**
- Phase 1 working
- SWAIG webhook deployed (already exists)
- Firestore collections created (already exist)

**Success Criteria:**
- AI can call all 6 functions during conversation
- Firestore collections populate correctly
- No cold-start timeouts on GCF (under 3s response time)

**Risks:**
- GCF cold starts may cause SWAIG timeouts (mitigate: keep functions warm with scheduled pings)

---

### Phase 4: Post-Call Workflows (Week 3-4)
**Goal:** Act on call results — send emails, schedule callbacks, sync to Salesforce.

**Components:**
1. Email sender (reads `email-queue` collection, sends via Gmail)
2. Callback processor (reads `callbacks` collection, places calls when due)
3. Salesforce sync (reads `contacts` and `lead_scores`, upserts to SF)

**Dependencies:**
- Phase 3 working (Firestore populated)
- Gmail app password (needs setup)
- Salesforce credentials (needs setup: username, password, security token)

**Success Criteria:**
- Follow-up emails sent within 1 hour of call completion
- Callbacks auto-dial at scheduled times
- Lead scores sync to Salesforce within 24 hours

**Risks:**
- Salesforce API rate limits (mitigate: batch upserts, 1x daily sync)

---

### Phase 5: Monitoring and Dashboard (Week 4+)
**Goal:** Visualize campaign health, call metrics, lead pipeline.

**Components:**
1. Flask dashboard (already exists on macpro)
2. Real-time Firestore subscriptions
3. Call success rate charts
4. Lead funnel visualization

**Dependencies:**
- Phase 4 working (full data pipeline)
- macpro uptime (or migrate to Cloud Run)

**Success Criteria:**
- Dashboard shows live call status (in-progress, completed, failed)
- Daily/weekly success rate visible
- Lead scores distribution chart

**Risks:**
- macpro SSH still down (mitigate: deploy dashboard to Cloud Run)

---

### Phase 6: Production Hardening (Week 5+)
**Goal:** Move from macpro to fully cloud-native, add resilience.

**Components:**
1. Migrate campaign runner to GCF + Cloud Scheduler
2. Add retry logic for failed calls
3. Implement exponential backoff for rate limit violations
4. Set up alerting (email/SMS on campaign failures)

**Dependencies:**
- Phase 5 stable
- GCP Cloud Scheduler configured
- SendGrid or similar for alerting

**Success Criteria:**
- Campaigns run fully serverless (no macpro dependency)
- Auto-retry failed calls (max 3 attempts)
- Team receives alerts on >20% failure rate

**Risks:**
- Cloud Scheduler cold starts may delay campaigns (mitigate: use Cloud Run with min instances)

## Agents SDK vs. This Architecture

### When Would You Use Agents SDK?

The Agents SDK is a Python framework for running a **local server** that SignalWire calls via webhook. It's ideal for:

1. **Multi-agent routing** — SIP calls route to different agents based on username
2. **Complex state management** — Persistent conversation state across calls
3. **Custom authentication** — Per-agent security tokens, basic auth
4. **Advanced SWAIG patterns** — DataMap tools that execute on SignalWire's server without webhooks

### Why This Architecture Doesn't Need Agents SDK

| Requirement | This Project | Agents SDK Solution | Chosen Approach |
|-------------|--------------|---------------------|-----------------|
| Outbound call initiation | Campaign script dials targets | Agents SDK server receives webhook, dials | REST API + inline SWML |
| AI configuration | Inline SWML in API call | Agent class with `prompt`, `voice`, etc. | Inline SWML |
| SWAIG functions | Cloud Functions (GCF) | Agent server routes | GCF (already deployed) |
| State persistence | Firestore via SWAIG | Agent SDK state manager | Firestore |
| Deployment | Script on macpro or Lambda | Local server + ngrok or cloud server | Serverless-first |

**Bottom line:** Agents SDK is overkill for a **single-agent, outbound-only, campaign-driven** system. It excels at **inbound routing, multi-agent coordination, and complex state**. This project needs **batch dialing, data logging, and follow-up workflows** — better served by REST API + webhooks.

### Migration Path to Agents SDK (If Needed)

If requirements change to need Agents SDK features (e.g., inbound call handling, multi-agent routing):

1. **Phase 1:** Deploy Agents SDK server on macpro or Cloud Run
2. **Phase 2:** Expose via persistent ngrok tunnel (dev) or public IP (prod)
3. **Phase 3:** Move SWAIG functions from GCF to Agent SDK routes
4. **Phase 4:** Use Agent SDK's `dial()` method instead of REST API calls

**Estimated effort:** 2-3 weeks (rewrite campaign runner, migrate SWAIG, test inbound routing)

## Scalability Considerations

| Concern | At 10 Calls/Day | At 100 Calls/Day | At 1000 Calls/Day |
|---------|------------------|------------------|-------------------|
| **Call Initiation** | Local script, manual trigger | Cron job on macpro | Cloud Scheduler + GCF |
| **Rate Limiting** | 1 call/5 sec (no risk) | 1 call/3 sec (safe) | 1 call/2 sec + burst protection |
| **SWAIG Cold Starts** | Acceptable (<500ms) | Keep functions warm with pings | Use min instances on GCF |
| **Firestore Writes** | No concern | No concern | Batch writes in SWAIG (10 calls → 1 write) |
| **Salesforce Sync** | Real-time API calls | Daily batch (1x 24hr) | Daily batch + webhook triggers |
| **Dashboard** | Flask on macpro | Flask on macpro | Migrate to Cloud Run, add caching |
| **Cost** | ~$0.05/call ($0.50/day) | ~$5/day | ~$50/day (mostly SignalWire minutes) |

**Bottlenecks to Watch:**
1. **SignalWire rate limits** — Undocumented platform limits exist. If hitting blocks at 1 call/2 sec, slow to 1 call/5 sec.
2. **GCF cold starts** — SWAIG functions take 200-500ms to wake. At high call volumes, keep warm with scheduled pings.
3. **Firestore write limits** — 10K writes/sec per collection. At 1000 calls/day with 6 SWAIG calls each → 6K writes/day (no risk).
4. **macpro uptime** — If campaign runner stays local, macpro downtime blocks campaigns. Migrate to cloud for 99.9% uptime.

## Sources

### Official Documentation
- [SignalWire Agents SDK Docs](https://developer.signalwire.com/sdks/agents-sdk/)
- [SignalWire Agents SDK on GitHub](https://github.com/signalwire/signalwire-agents)
- [Locally Test Webhooks with ngrok](https://developer.signalwire.com/platform/basics/guides/technical-troubleshooting/how-to-test-webhooks-with-ngrok/)
- [SignalWire Calling API](https://developer.signalwire.com/rest/signalwire-rest/endpoints/calling/calling-api/)
- [Compatibility REST API — Create a Call](https://developer.signalwire.com/rest/compatibility-api/endpoints/create-a-call/)
- [Getting Started with SignalWire AI Agent](https://developer.signalwire.com/swml/guides/ai/getting-started/)
- [SWML `ai` Method Reference](https://developer.signalwire.com/swml/methods/ai/)

### Blog Posts and Guides
- [SignalWire Agents SDK for Python: Core Features](https://signalwire.com/blogs/developers/agents-sdk-python-core-features)
- [Introducing the SignalWire AI Agents SDK](https://signalwire.com/blogs/developers/introducing-signalwire-ai-agents-sdk)
- [Building an AI Agent from SWML + Node.js](https://signalwire.com/blogs/developers/ai-agent-swml-nodejs)
- [Building Context-Aware Call Flows with AI Agents](https://signalwire.com/blogs/developers/context-aware-call-flows)

### Project-Specific Knowledge
- Existing codebase at `/Users/ciroccofam/ai-voice-caller-fix/`
- Production learning documented in user memory at `/Users/ciroccofam/.claude/projects/-Users-ciroccofam/memory/signalwire-voice-caller.md`
- Feb 11 proof-of-concept: 18-second call with AI dialogue using Agents SDK + ngrok
- Feb 17 root cause fix: Calling API with inline SWML is correct approach for outbound
