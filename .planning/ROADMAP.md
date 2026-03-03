# Roadmap: AI Voice Caller — Fortinet SLED

**Version:** v1
**Created:** 2026-02-17
**Phases:** 4
**Depth:** Quick (compress aggressively, critical path only)

## Overview

This roadmap delivers an AI outbound calling system for Fortinet SLED territory prospecting. The critical path is: validate Agents SDK foundation (Phase 1), harden infrastructure and compliance (Phase 2), scale to batch calling (Phase 3), integrate external systems (Phase 4). All 16 v1 requirements are mapped to exactly one phase.

## Phases

### Phase 1: Foundation
**Goal:** One AI outbound call successfully speaks and logs outcome

**Status:** Pending

**Dependencies:** None (start here)

**Requirements:**
- CALL-01: AI agent speaks on outbound calls using SignalWire Agents SDK with local server + ngrok tunnel
- CALL-02: AI speaks static greeting immediately on call answer, then has natural two-way conversation
- DATA-02: Every call outcome logged to Firestore call_logs with outcome, duration, summary, and timestamp

**Success Criteria:**
1. User triggers a test call that connects and AI speaks audible greeting within 3 seconds of answer
2. User has a two-way conversation with AI (asks question, AI responds naturally)
3. After call ends, user can query Firestore call_logs and see outcome, duration, and summary
4. System runs on macpro via ngrok tunnel with documented setup steps

**Completion:** 0% (0/3 requirements)

---

### Phase 2: Compliance & Persistence
**Goal:** System runs reliably 24/7 with legal compliance for production usage

**Status:** Pending

**Dependencies:** Phase 1 (requires Agents SDK foundation)

**Requirements:**
- CALL-03: Agents SDK server runs persistently on macpro via systemd with auto-restart on failure
- CALL-04: ngrok tunnel runs persistently via systemd, auto-reconnects on disconnect
- CALL-05: System detects voicemail and either drops a pre-recorded message or hangs up gracefully
- CAMP-03: DNC/opt-out list tracked in Firestore — numbers are never called again

**Success Criteria:**
1. User can reboot macpro and Agents SDK server + ngrok tunnel auto-restart within 30 seconds
2. User can simulate process crash and systemd auto-restarts service within 10 seconds
3. User triggers test call to voicemail number and AI detects + drops message OR hangs up (no 60-second dead air)
4. User adds number to DNC list in Firestore and campaign runner skips it on next batch
5. System includes TCPA-compliant disclosure in AI greeting (This call is recorded)

**Completion:** 0% (0/4 requirements)

---

### Phase 3: Campaign & Data
**Goal:** Batch dial from CSV with full SWAIG integration and callback automation

**Status:** Pending

**Dependencies:** Phase 2 (requires persistent infrastructure)

**Requirements:**
- CAMP-01: Campaign runner batch-dials targets from CSV with minimum 5-second interval between calls
- CAMP-02: Campaign resumes from last position if script is interrupted or server restarts
- CAMP-04: Callback queue auto-dials due callbacks at scheduled times
- DATA-01: All 6 SWAIG functions fire during live AI conversations (save_contact, log_call, score_lead, save_lead, schedule_callback, send_info_email)
- DATA-03: AI scores leads 1-10 during conversation based on interest level and fit
- DATA-04: AI receives call history context before each call (previous outcomes, notes, callback status)

**Success Criteria:**
1. User loads CSV with 10 targets and campaign runner dials all with minimum 5-second intervals
2. User interrupts campaign mid-run (Ctrl+C) and restarts — campaign resumes from last undialed number
3. User schedules callback during AI call and callback queue auto-dials at scheduled time
4. User reviews call transcript and confirms all 6 SWAIG functions fired correctly (contact saved, call logged, lead scored, callback scheduled, email queued)
5. User dials repeat contact and AI references previous call outcome in conversation (Last time we spoke about...)
6. User reviews lead_scores collection and sees 1-10 score with interest-level justification

**Completion:** 0% (0/6 requirements)

---

### Phase 4: Integrations & Operations
**Goal:** External system sync and operational visibility for production usage

**Status:** Pending

**Dependencies:** Phase 3 (requires campaign + data workflows)

**Requirements:**
- INTG-01: Call outcomes sync to Salesforce existing accounts (never creates new records)
- INTG-02: Follow-up emails sent from Firestore email-queue via Gmail
- INTG-03: Ops dashboard shows call stats, outcomes, lead scores, and system health

**Success Criteria:**
1. User completes 5 calls and call outcomes sync to Salesforce within 5 minutes (mapped by phone/email)
2. User queues follow-up email during AI call and email sends from Gmail within 2 minutes
3. User opens dashboard and sees: total calls today, outcome breakdown (connected/voicemail/no-answer), average lead score, system health (agent server up/down, ngrok tunnel status)
4. Dashboard updates in real-time as new calls complete (no manual refresh required)

**Completion:** 0% (0/3 requirements)

---

## Progress Summary

| Phase | Requirements | Completed | Status |
|-------|--------------|-----------|--------|
| 1 - Foundation | 3 | 0 | Pending |
| 2 - Compliance & Persistence | 4 | 0 | Pending |
| 3 - Campaign & Data | 6 | 0 | Pending |
| 4 - Integrations & Operations | 3 | 0 | Pending |
| **Total** | **16** | **0** | **0%** |

## Coverage Validation

All 16 v1 requirements mapped to exactly one phase:

| Requirement | Phase | Mapped |
|-------------|-------|--------|
| CALL-01 | 1 | ✓ |
| CALL-02 | 1 | ✓ |
| CALL-03 | 2 | ✓ |
| CALL-04 | 2 | ✓ |
| CALL-05 | 2 | ✓ |
| DATA-01 | 3 | ✓ |
| DATA-02 | 1 | ✓ |
| DATA-03 | 3 | ✓ |
| DATA-04 | 3 | ✓ |
| CAMP-01 | 3 | ✓ |
| CAMP-02 | 3 | ✓ |
| CAMP-03 | 2 | ✓ |
| CAMP-04 | 3 | ✓ |
| INTG-01 | 4 | ✓ |
| INTG-02 | 4 | ✓ |
| INTG-03 | 4 | ✓ |

**Coverage: 16/16 requirements (100%)**

No orphaned requirements.

---
*Generated: 2026-02-17*
