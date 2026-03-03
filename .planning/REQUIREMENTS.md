# Requirements: AI Voice Caller — Fortinet SLED

**Version:** v1
**Date:** 2026-02-17
**Total:** 16 requirements across 4 categories

## v1 Requirements

### Core Calling

- [ ] **CALL-01**: AI agent speaks on outbound calls using SignalWire Agents SDK with local server + ngrok tunnel
- [ ] **CALL-02**: AI speaks static greeting immediately on call answer, then has natural two-way conversation
- [ ] **CALL-03**: Agents SDK server runs persistently on macpro via systemd with auto-restart on failure
- [ ] **CALL-04**: ngrok tunnel runs persistently via systemd, auto-reconnects on disconnect
- [ ] **CALL-05**: System detects voicemail and either drops a pre-recorded message or hangs up gracefully

### Data & SWAIG

- [ ] **DATA-01**: All 6 SWAIG functions fire during live AI conversations (save_contact, log_call, score_lead, save_lead, schedule_callback, send_info_email)
- [ ] **DATA-02**: Every call outcome logged to Firestore call_logs with outcome, duration, summary, and timestamp
- [ ] **DATA-03**: AI scores leads 1-10 during conversation based on interest level and fit
- [ ] **DATA-04**: AI receives call history context before each call (previous outcomes, notes, callback status)

### Campaign

- [ ] **CAMP-01**: Campaign runner batch-dials targets from CSV with minimum 5-second interval between calls
- [ ] **CAMP-02**: Campaign resumes from last position if script is interrupted or server restarts
- [ ] **CAMP-03**: DNC/opt-out list tracked in Firestore — numbers are never called again
- [ ] **CAMP-04**: Callback queue auto-dials due callbacks at scheduled times

### Integrations

- [ ] **INTG-01**: Call outcomes sync to Salesforce existing accounts (never creates new records)
- [ ] **INTG-02**: Follow-up emails sent from Firestore email-queue via Gmail
- [ ] **INTG-03**: Ops dashboard shows call stats, outcomes, lead scores, and system health

## v2 Requirements (Deferred)

- Conversational intelligence scoring (sentiment, talk ratio, objection handling)
- Voice cloning / custom TTS voice
- Hot transfer to live agent mid-call
- Searchable call transcripts
- LinkedIn/social integration for prospect research
- A/B testing of prompts and greetings
- Multi-territory support (beyond AZ SLED)

## Out of Scope

- Multi-tenant SaaS platform — single-user tool first
- Mobile app or web UI for call control — CLI/script-based is fine
- Inbound call handling — outbound only
- Creating new Salesforce records — sync to existing accounts only
- Real-time call monitoring/coaching — post-call analysis only
- Predictive/power dialing — sequential only
- IVR menus or phone trees
- Payment processing

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CALL-01 | Phase 1 | Pending |
| CALL-02 | Phase 1 | Pending |
| CALL-03 | Phase 2 | Pending |
| CALL-04 | Phase 2 | Pending |
| CALL-05 | Phase 2 | Pending |
| DATA-01 | Phase 3 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 3 | Pending |
| DATA-04 | Phase 3 | Pending |
| CAMP-01 | Phase 3 | Pending |
| CAMP-02 | Phase 3 | Pending |
| CAMP-03 | Phase 2 | Pending |
| CAMP-04 | Phase 3 | Pending |
| INTG-01 | Phase 4 | Pending |
| INTG-02 | Phase 4 | Pending |
| INTG-03 | Phase 4 | Pending |

---
*Generated: 2026-02-17*
*Updated: 2026-02-17 (traceability section)*
