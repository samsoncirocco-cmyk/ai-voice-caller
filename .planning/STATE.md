# Project State: AI Voice Caller — Fortinet SLED

**Last Updated:** 2026-02-17
**Current Phase:** 1 - Foundation
**Current Plan:** Not started
**Status:** Ready to begin

## Project Reference

**Core Value:** Matt speaks on outbound calls and has real, natural conversations with prospects. Everything else (logging, scoring, Salesforce sync, campaigns) is downstream of this one thing working.

**Current Focus:** Validate SignalWire Agents SDK foundation with one successful AI call that speaks and logs outcome.

## Current Position

**Phase:** 1 - Foundation
**Goal:** One AI outbound call successfully speaks and logs outcome
**Plan:** Not started
**Status:** Awaiting plan-phase command

**Progress:**
- Overall: 0% (0/16 requirements)
- Phase 1: 0% (0/3)
- Phase 2: 0% (0/4)
- Phase 3: 0% (0/6)
- Phase 4: 0% (0/3)

## Performance Metrics

**Velocity:** N/A (no completed plans yet)
**Quality:** N/A (no verifications yet)
**Blockers:** 0 active

## Accumulated Context

### Critical Decisions

1. **2026-02-17:** Architecture decision - Use SignalWire Agents SDK (local server + ngrok tunnel) as ONLY viable path for AI outbound calling. Compatibility API and Calling API both fail silently for AI agents.

2. **2026-02-17:** Phone number protection - Only one production number remains (+14806024668) after testing burned two others. Must purchase 2-3 dedicated test numbers before Phase 1 execution.

3. **2026-02-17:** Rate limiting mandate - NEVER exceed 1 call per 5 seconds. Rapid test calls trigger carrier-level blocks lasting 24+ hours.

### Known Issues & Workarounds

**Phone Number Status (2026-02-17):**
- All three SignalWire numbers currently SIP 500 blocked (trunk-level)
- Support ticket filed to lift block
- Root cause: Excessive test calls during debugging

**Workaround:** Wait for SignalWire support response before attempting calls. Purchase test numbers immediately after unblock.

**Infrastructure:**
- macpro SSH can be flaky (known constraint)
- Agents SDK server + ngrok tunnel setup exists from Feb 11 proof-of-concept but needs systemd hardening

### Open Todos

- [ ] Wait for SignalWire support to lift SIP 500 block
- [ ] Purchase 2-3 dedicated test numbers (separate from production +14806024668)
- [ ] Configure GCP Secret Manager secrets for Salesforce (sf-username, sf-password, sf-security-token)
- [ ] Configure Gmail app password in .env (GMAIL_USER, GMAIL_APP_PASSWORD)

### Active Blockers

None currently. Phone number block is being resolved via support ticket.

## Session Continuity

### What Just Happened

Roadmap created with 4 phases derived from 16 v1 requirements. Structure prioritizes:
1. Foundation validation (Agents SDK proof)
2. Compliance and persistence (production-ready infrastructure)
3. Campaign scaling (batch calling + full SWAIG)
4. External integrations (Salesforce, email, dashboard)

Coverage: 16/16 requirements mapped (100%).

### Next Steps

1. Run plan-phase command for Phase 1 to decompose Foundation phase into executable plan
2. Wait for SignalWire support to lift phone number block
3. Purchase test numbers before starting Phase 1 execution
4. Configure Salesforce and Gmail credentials in GCP Secret Manager

### Context for Next Agent

Phase 1 is a technical validation phase. The brownfield context shows previous work used wrong APIs (Compatibility, Calling) that do not support AI agents. Feb 11 proof-of-concept proved Agents SDK works (18s call with dialogue) but needs to be rebuilt as stable foundation.

Phase 1 success criteria are intentionally narrow: one call that speaks and logs. Do not expand scope — this phase validates the technical approach before building on it.

Critical constraints:
- Only one production number remains (protect it)
- Rate limiting is non-negotiable (max 1 call per 5 sec)
- Voicemail detection deferred to Phase 2 (not blocking foundation validation)

---
*Last session: 2026-02-17 - Roadmap creation*
