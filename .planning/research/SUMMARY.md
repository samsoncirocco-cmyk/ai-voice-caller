# Project Research Summary

**Project:** AI Voice Caller (Matt) - SignalWire AI Outbound Calling System
**Domain:** AI outbound calling / sales automation for SLED territory
**Researched:** 2026-02-17
**Confidence:** HIGH

## Executive Summary

This is a brownfield rebuild of an AI outbound calling system for Fortinet SLED cold calling. The core technical challenge has been resolved: **SignalWire Agents SDK with local server + ngrok tunnel is the ONLY architecture that works** for AI outbound calls. Previous approaches using Compatibility API and Calling API failed silently because they don't support AI voice agents. The system already has significant infrastructure in place (6 SWAIG functions on GCF, Firestore data layer, campaign runner scripts) but needs to be rebuilt on the correct API foundation.

The recommended approach is a **hybrid architecture**: Agents SDK Python server on macpro (via ngrok tunnel) for call handling, existing Google Cloud Functions for SWAIG webhooks, and Firestore for persistence. Critical gaps blocking production are: (1) voicemail detection/drop (70% of calls hit voicemail), (2) TCPA compliance tooling (DNC lists, call recording disclosure), and (3) phone number protection (only one remaining number after testing burned two others). The system must prioritize phone number preservation and rate limiting (max 1 call per 5 seconds) to avoid carrier-level blocks that persist for 24+ hours.

Key risks center on telephony reputation management, regulatory compliance, and latency optimization. Unlike API development, telephony has invisible anti-abuse systems that are unforgiving and slow to recover. The roadmap must sequence work to validate the Agents SDK foundation early, protect the remaining phone number, implement compliance before any production usage, and only then scale to full campaign volumes.

## Key Findings

### Recommended Stack

SignalWire Agents SDK (Python) is non-negotiable for AI outbound calling. The Compatibility API only supports cXML (XML), and the Calling API requires client-side Realtime SDK WebSocket connections. The Agents SDK provides server-side AI agent runtime with SWML generation, SWAIG function routing, and sub-500ms conversation latency.

**Core technologies:**
- **SignalWire Agents SDK (Python 3.12)**: AI agent runtime + SWML generation — ONLY path for server-side AI outbound calls
- **Uvicorn + Gunicorn**: ASGI server with process management — SDK is async-native, requires ASGI not WSGI
- **ngrok**: Persistent tunnel to local server — SignalWire needs stable HTTP endpoint, serverless timeouts don't work for 5-10 min calls
- **Google Cloud Functions**: SWAIG webhooks — stateless event-driven functions (save_contact, log_call, etc.)
- **Firestore**: Primary datastore — already contains contacts, call_logs, lead_scores; NoSQL fits call data patterns
- **systemd**: Service orchestration — manages both ngrok tunnel and agent server with dependency tracking

**Critical version requirements:**
- Python 3.12 (SDK requires 3.8+, GCF supports up to 3.14)
- signalwire-agents (latest from PyPI, actively developed)
- gunicorn with `-k uvicorn.workers.UvicornWorker` for ASGI support

**Infrastructure pattern:**
Local server (macpro) + ngrok tunnel for agent runtime, cloud-hosted (GCF) for webhooks. This hybrid approach avoids serverless timeout limitations (calls last 5-10 minutes) while keeping SWAIG functions stateless and scalable.

### Expected Features

AI outbound calling has evolved from robocalls to conversational AI with emotional intelligence and ultra-low latency. The 2026 market demands natural conversation quality — "Matt speaks and has real conversations" is the core value prop. For a single-user tool, conversational quality trumps enterprise features like multi-tenant support or predictive dialing.

**Must have (table stakes):**
- Natural conversation handling — core value prop, requires LLM + voice AI platform
- Voicemail detection/drop — 70% of cold calls hit voicemail, efficiency blocker (CRITICAL GAP)
- DNC compliance + call recording disclosure — legal requirement, $500-$1,500 fines per violation (CRITICAL GAP)
- Contact management + call logging — already exists via SWAIG functions
- Campaign/batch dialing — already exists
- CRM sync (Salesforce) — already exists (Firestore to SF)
- Callback scheduling — already exists
- Follow-up automation (email) — already exists

**Should have (competitive differentiators):**
- Conversational intelligence — advanced prompt engineering, emotional awareness, real-time adaptation
- Real-time coaching feedback — post-call analysis for self-improvement
- Bi-directional Salesforce sync — pull account context mid-call for personalization (currently one-way)
- Lead scoring automation — already exists via score_lead function
- Territory intelligence — SLED-specific context (K-12 budget cycles, procurement rules)

**Defer (v2+):**
- Multi-channel orchestration (LinkedIn integration) — email exists, LinkedIn can wait
- Voice cloning — nice-to-have, default voice acceptable
- Hot transfer (AI to human) — low priority for single-user
- Searchable transcripts — valuable but not blocking
- Emotional intelligence — bleeding edge, high effort

**Anti-features (explicitly avoid):**
- Multi-tenant SaaS infrastructure
- Inbound call handling (focus 100% on outbound)
- Predictive dialing (requires high volume, causes "telemarketer delay")
- IVR menu trees (conversational AI is the point)
- Complex user roles/permissions (single user)

### Architecture Approach

The architecture discovered through brownfield analysis reveals a **REST API + inline SWML + cloud webhooks** pattern, NOT the Agents SDK webhook pattern initially assumed. However, the root cause fix confirms that **Agents SDK IS required** — REST API approaches (Compatibility API, Calling API) all fail silently for AI outbound calling.

**Corrected architecture: Agents SDK webhook pattern**

Major components:

1. **Campaign Orchestrator (Python script on macpro)** — Reads targets from CSV/Firestore, manages rate limiting (1 call per 5 sec), tracks campaign progress, handles resume-from-checkpoint
2. **SignalWire Agents SDK Server (macpro via ngrok)** — Local Python server using Agents SDK, generates SWML with AI agent config, exposes webhook endpoint for SignalWire to call, routes SWAIG functions to GCF endpoints
3. **SignalWire Platform (managed SaaS)** — Telephony layer (PSTN/SIP), AI runtime (ASR/LLM/TTS orchestration), sub-500ms latency engine, barge-in and turn detection
4. **SWAIG Webhook Handler (GCF)** — 6 functions already deployed: save_contact, log_call, score_lead, save_lead, schedule_callback, send_info_email
5. **Firestore (GCP)** — Collections: contacts, call_logs, lead_scores, callbacks, email-queue
6. **Dashboard (Flask on macpro)** — Real-time campaign monitoring, call metrics visualization

**Critical architectural decision:**
Use Agents SDK local server (NOT REST API with inline SWML) because:
- Compatibility API silently ignores SWML JSON (only processes cXML from webhooks)
- Calling API requires Realtime SDK WebSocket listener (fire-and-forget doesn't work)
- Agents SDK webhook pattern is the ONLY server-side solution for AI outbound calling

**Data flow:**
Campaign runner doesn't call SignalWire directly. Instead, it triggers the Agents SDK server to initiate calls. SignalWire calls the agent webhook endpoint (via ngrok tunnel), receives SWML config, executes AI conversation, and POSTs to SWAIG webhooks (GCF) as needed during the call.

### Critical Pitfalls

This project has already experienced catastrophic failures from API misselection and rate limiting. Seven EXPERIENCED pitfalls document actual brownfield pain.

**Top 5 critical pitfalls to avoid:**

1. **Wrong API Selection (EXPERIENCED)** — Used Compatibility API (cXML only) and Calling API (Realtime SDK required) for weeks before discovering Agents SDK is the only path. Silent failures with no error messages. **Prevention:** Agents SDK is non-negotiable for AI voice. Document API decision rationale in Phase 1 README to prevent backsliding.

2. **Carrier-Level Rate Limiting (EXPERIENCED)** — Rapid test calls (3-4 in succession) triggered platform/carrier blocks lasting 24+ hours. SIP 500 errors, zero-duration calls, phone number reputation damage. **Prevention:** NEVER exceed 1 call per 5 seconds. Implement exponential backoff (5s, 15s, 30s, 60s). Use test numbers for debugging, protect production numbers.

3. **Phone Number Death (EXPERIENCED)** — Number +16028985026 permanently blocked after excessive testing. Only one remaining number (+14806024668). **Prevention:** Purchase 2-3 dedicated TEST numbers before Phase 1. NEVER use production numbers for debugging. Hard limit: 5 calls per test number per day during development.

4. **TCPA Compliance Violations (NOT YET EXPERIENCED)** — AI calls are legally robocalls under TCPA. Requires prior express written consent, AI disclosure, DNC list, opt-out mechanism. Fines: $500-$1,500 PER CALL. **Prevention:** Legal review BEFORE first production call. Implement consent tracking, DNC list, disclosure in greeting. Phase 0 requirement.

5. **Webhook Timeout Death Spiral (NOT YET EXPERIENCED)** — SWAIG functions must respond within 4.5-5 seconds. Timeouts trigger auto-retries (3x total), causing triple API charges, data corruption, conversation stalls. **Prevention:** Set 3s timeout on all external calls in SWAIG functions. Return acknowledgment immediately, process async if needed. Measure execution time in Phase 1.

**Additional critical warnings:**
- Latency accumulation: STT (100-300ms) + LLM (200-800ms) + TTS (100-400ms) + SWAIG (200-1000ms) = cumulative. Target p95 < 500ms total or conversations feel broken.
- Silent production failures: Call marked "completed" but AI never spoke, or user hung up frustrated after 10s. Traditional metrics (HTTP 200) don't capture voice quality. Need transcript analysis, duration patterns, sentiment scoring.
- Dual ID confusion: SignalWire agents have Resource ID (outer, Fabric API) and Agent ID (inner, AI API). Using wrong ID causes silent failures.

## Implications for Roadmap

Based on research, the roadmap must prioritize **foundation validation**, **compliance**, and **phone number protection** before any scaling. The brownfield context means fixing critical gaps (voicemail, compliance) and de-risking telephony reputation issues take precedence over new features.

### Phase 1: Foundation - Agents SDK + Single Call Validation
**Rationale:** Must prove Agents SDK architecture works end-to-end before building on it. Research shows this is the ONLY viable path for AI outbound calling. All previous work on wrong APIs must be replaced.

**Delivers:** One successful AI outbound call with verified audio output, SWAIG function calls working, call logged to Firestore.

**Stack elements:** SignalWire Agents SDK, Uvicorn/Gunicorn, ngrok tunnel, systemd services, Python 3.12

**Architecture:** Agent SDK local server (macpro) + ngrok tunnel + SWAIG webhooks (existing GCF) + Firestore

**Avoids pitfalls:**
- Wrong API selection (document decision, code review checklist)
- Silent calls (require manual audio validation before marking complete)
- Rate limiting (implement 5s interval from day 1, even for single call tests)

**Research needs:** Standard patterns, official docs available. No additional research needed.

### Phase 2: Compliance + Phone Number Protection
**Rationale:** Legal requirement BEFORE production usage. Research shows TCPA fines are $500-$1,500 per call. Only one production number remains after testing killed two others. Must protect it.

**Delivers:** DNC list integration, consent tracking, call recording disclosure, 2-3 dedicated test numbers purchased

**Addresses features:** Compliance basics (from table stakes), voicemail detection (blocking 70% efficiency gain)

**Avoids pitfalls:**
- TCPA compliance violations (legal review, consent database)
- Phone number death (separate test/production numbers, hard limits)
- Carrier rate limiting (circuit breaker pattern, max 1 call per 5 sec)

**Research needs:** LIKELY NEEDS PHASE RESEARCH for TCPA compliance specifics, DNC list integration APIs, voicemail detection methods (SignalWire capabilities, third-party services).

### Phase 3: Campaign Runner + Batch Dialing
**Rationale:** Scale from single-call validation to batch processing. Research shows campaign runner already exists but needs integration with Agents SDK foundation.

**Delivers:** CSV target import, rate-limited call loop, status polling, resume-from-checkpoint

**Uses stack elements:** Python campaign orchestrator, Firestore for queue management, systemd for background processing

**Implements architecture:** Campaign Orchestrator component triggering Agents SDK server

**Avoids pitfalls:**
- Rate limiting at scale (exponential backoff, circuit breaker auto-pauses after 2 failures)
- Silent production failures (call quality scoring, duration pattern monitoring)

**Research needs:** Standard batch processing patterns. No additional research needed.

### Phase 4: SWAIG Function Expansion + Data Workflows
**Rationale:** Verify all 6 existing SWAIG functions work with Agents SDK. Enable post-call workflows (email, callbacks, Salesforce sync).

**Delivers:** All 6 SWAIG functions tested live, email sender, callback processor, Salesforce sync

**Addresses features:** Follow-up automation (table stakes), CRM sync (already exists, verify integration)

**Avoids pitfalls:**
- Webhook timeout death spiral (add 3s timeout to all external calls, measure execution time)
- SWAIG function naming confusion (audit names/descriptions for clarity)

**Research needs:** Standard patterns. No additional research needed.

### Phase 5: Conversational Quality + Optimization
**Rationale:** Enhance core value prop ("Matt sounds human"). Research shows conversational intelligence is the key differentiator for single-user tools, not feature breadth.

**Delivers:** Advanced prompt engineering, latency optimization (p95 < 500ms), real-time coaching feedback, bi-directional Salesforce sync

**Addresses features:** Conversational intelligence, real-time coaching, territory intelligence (should-have differentiators)

**Avoids pitfalls:**
- Latency accumulation (measure/optimize each component, streaming where possible)
- Over-prompting (use Prompt Object Model, principles not scripts)
- Geographic latency mismatch (deploy in us-west region for Arizona users)

**Research needs:** LIKELY NEEDS PHASE RESEARCH for advanced prompt engineering techniques, latency optimization strategies (streaming STT/TTS), sentiment analysis integration.

### Phase 6: Production Hardening + Cloud Migration
**Rationale:** Move from macpro dependency to cloud-native for 99.9% uptime. Research shows SSH flakiness to macpro makes incident response difficult.

**Delivers:** Campaign runner on GCF + Cloud Scheduler, retry logic, exponential backoff for rate limits, alerting (email/SMS on failures)

**Uses stack elements:** GCP Cloud Scheduler, Cloud Run (for agent server migration from macpro), structured logging (JSON to Cloud Logging)

**Avoids pitfalls:**
- SSH flakiness (migrate critical services to cloud)
- Silent production failures (alerting on call quality degradation)

**Research needs:** LIKELY NEEDS PHASE RESEARCH for Agents SDK deployment to Cloud Run (vs. local server), Cloud Scheduler configuration for campaign orchestration.

### Phase Ordering Rationale

**Dependency chain:**
- Phase 1 validates foundation (Agents SDK works) → blocks all other work
- Phase 2 enables legal production usage (compliance) → blocks Phase 3 scaling
- Phase 3 enables batch calling → required for Phase 4 workflow testing at scale
- Phase 4 verifies existing infrastructure (SWAIG, Firestore) integrates correctly
- Phase 5 optimizes core value prop (only valuable after foundation is stable)
- Phase 6 hardens for production (moves from prototype to production-grade)

**Risk mitigation sequence:**
1. Validate technical approach early (Phase 1)
2. Address legal/compliance before any production calls (Phase 2)
3. Protect remaining phone number with test number separation (Phase 2)
4. Scale gradually with monitoring (Phases 3-4)
5. Optimize only after foundation is proven (Phase 5)
6. Harden infrastructure last (Phase 6)

**Brownfield context:**
Much infrastructure exists (SWAIG functions, Firestore, campaign scripts) but built on wrong API foundation. Phases 1-2 fix the foundation, Phases 3-4 integrate existing work, Phases 5-6 enhance and harden.

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 2 (Compliance):** TCPA compliance specifics, DNC list integration APIs, voicemail detection methods — niche legal/regulatory domain, sparse documentation
- **Phase 5 (Optimization):** Advanced prompt engineering for conversational AI, latency optimization strategies (streaming STT/TTS), sentiment analysis integration — rapidly evolving domain, vendor-specific techniques
- **Phase 6 (Cloud Migration):** Agents SDK deployment to Cloud Run (vs. local server patterns), persistent tunnel alternatives to ngrok for production — architectural shift from local to cloud

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Foundation):** Official SignalWire Agents SDK docs cover setup thoroughly
- **Phase 3 (Campaign Runner):** Standard batch processing, well-documented Python patterns
- **Phase 4 (SWAIG Functions):** Webhook patterns are standard, existing functions already deployed

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All components verified via official docs, brownfield learning confirms Agents SDK requirement |
| Features | HIGH | 2026-current sources, cross-verified across multiple authoritative platforms |
| Architecture | HIGH | Verified with official docs, existing codebase, and production learning (Feb 11 proof-of-concept) |
| Pitfalls | HIGH | 7 EXPERIENCED pitfalls directly encountered in brownfield context, others sourced from official SignalWire troubleshooting guides |

**Overall confidence:** HIGH

Research is grounded in actual brownfield experience (API failures, rate limiting blocks, phone number death) and official documentation. The technical approach (Agents SDK) has been validated with an 18-second proof-of-concept call on Feb 11. Compliance and optimization areas are well-researched from 2026-current industry sources.

### Gaps to Address

**Legal compliance specifics:**
Research identifies TCPA requirements at high level, but not legal counsel review. Phase 2 requires actual legal consultation for SLED/government calling specifics, state-by-state disclosure requirements, and consent documentation standards.

**Carrier-specific rate limiting:**
Experienced platform-level blocks but don't have documented carrier-specific thresholds. May vary by carrier (AT&T vs. Verizon vs. T-Mobile). Monitor during Phase 3 and adjust rate limiting accordingly.

**Long-term phone number reputation recovery:**
No documented recovery path for burned numbers. Once blocked, appears permanent. Focus on prevention (test number separation) rather than recovery.

**Agents SDK production deployment patterns:**
Official docs focus on development (local server + ngrok). Production patterns (Cloud Run deployment, high availability, zero-downtime deploys) less documented. Phase 6 may need vendor consultation or community research.

**Voicemail detection capabilities:**
Research flags voicemail detection as critical (70% of calls) but doesn't specify SignalWire's built-in capabilities vs. third-party integration requirements. Phase 2 research needed.

## Sources

### Primary (HIGH confidence)
- [SignalWire Agents SDK Official Docs](https://developer.signalwire.com/sdks/agents-sdk/)
- [SignalWire Agents SDK GitHub](https://github.com/signalwire/signalwire-agents)
- [SignalWire Common Webhook Errors Guide](https://developer.signalwire.com/platform/basics/guides/technical-troubleshooting/common-webhook-errors/)
- [SignalWire Rate Limits Documentation](https://developer.signalwire.com/platform/basics/general/signalwire-rate-limits/)
- Existing codebase at `/Users/ciroccofam/ai-voice-caller-fix/`
- Production learning: Feb 11, 2026 proof-of-concept (18s call with AI dialogue using Agents SDK + ngrok)

### Secondary (MEDIUM confidence)
- [AI Outbound Calling in 2026: Strategy, Tech & Results](https://oneai.com/learn/ai-outbound-calling-guide)
- [Voice AI Latency Benchmarks 2026](https://www.trillet.ai/blogs/voice-ai-latency-benchmarks)
- [AI Calling Mistakes: 21 Fatal Errors Killing Your ROI](https://qcall.ai/ai-calling-mistakes)
- [TCPA Compliance for AI Outbound Dialing](https://borndigital.ai/ai-outbound-dialing-compliance-issues/)
- [Webhook Timeout Best Practices](https://www.svix.com/resources/webhook-university/reliability/webhook-timeout-best-practices/)

### Tertiary (LOW confidence, needs validation)
- Community discussions on SignalWire platform-level rate limiting (undocumented officially)
- Inference about Agents SDK Cloud Run deployment (not officially documented pattern)

---
*Research completed: 2026-02-17*
*Ready for roadmap: yes*
