# AI Voice Caller — Fortinet SLED

## What This Is

An AI outbound calling system for Fortinet SLED territory in Arizona. An AI agent ("Matt") cold-calls state, local, and education IT leaders, has real conversations about cybersecurity solutions, logs outcomes to Firestore, syncs to Salesforce, and triggers follow-up emails. Built as a daily prospecting tool that could scale to other reps or become a product.

## Core Value

Matt speaks on outbound calls and has real, natural conversations with prospects. Everything else (logging, scoring, Salesforce sync, campaigns) is downstream of this one thing working.

## Requirements

### Validated

(None yet — the AI has never successfully spoken on a production outbound call via the correct API path)

### Active

- [ ] AI agent speaks on outbound calls using SignalWire Agents SDK
- [ ] SWAIG functions fire during live conversations (save_contact, log_call, score_lead, schedule_callback, send_info_email)
- [ ] Campaign runner batch-dials targets from CSV with rate limiting
- [ ] Call outcomes sync to Salesforce (existing accounts only, never creates)
- [ ] Follow-up emails sent from Firestore queue
- [ ] Callback queue auto-dials due callbacks
- [ ] Ops dashboard shows call stats, outcomes, and system health
- [ ] System runs reliably on macpro with persistent tunnel

### Out of Scope

- Building a multi-tenant SaaS platform — this is a single-user tool first
- Mobile app or web UI for call control — CLI/script-based is fine
- Inbound call handling — outbound only
- Creating new Salesforce records — sync to existing accounts only
- Real-time call monitoring/coaching — post-call analysis only

## Context

### Architecture (Corrected 2026-02-17)

Three SignalWire APIs exist. Only ONE supports AI agents:

| API | Supports AI? | Notes |
|-----|-------------|-------|
| **Compatibility API** (`/api/laml/.../Calls.json`) | NO | cXML/LaML only. No `<AI>` verb exists. SWML JSON is silently ignored. |
| **Calling API** (`/api/calling/calls`) | NO (standalone) | Requires Realtime SDK on WebSocket to service calls. Fire-and-forget doesn't work — calls queue forever. |
| **Agents SDK** (Python, local server + tunnel) | YES | Runs a local server that SignalWire calls for SWML. This is the only path that works. Proven on Feb 11 (18s call with dialogue). |

### What Exists (on macpro at ~/.openclaw/workspace/projects/ai-voice-caller/)

**Core scripts (all built, untested end-to-end):**
- `make_call_v3.py`, `make_call_v4.py`, `make_call_v5.py` — Various call scripts using wrong APIs
- `execution/swaig_server.py` — SWAIG webhook on GCF (6 handlers, tested via curl)
- `execution/campaign_runner.py` — CSV batch dialer with rate limits + resume
- `execution/sync_salesforce.py` — Firestore to SF sync
- `execution/process_callbacks.py` — Auto-dial due callbacks
- `execution/send_emails.py` — Templated follow-up emails
- `execution/dashboard.py` — Flask ops dashboard
- `execution/auto_recovery_call.py` — Cron health check + auto-call
- `campaigns/sled-territory-832.csv` — Real AZ SLED targets

**SWAIG Functions (6 total, all deployed on GCF, tested via curl):**
1. save_contact → Firestore contacts
2. log_call → Firestore call_logs
3. score_lead → Firestore lead_scores
4. save_lead → Firestore cold-call-leads
5. schedule_callback → Firestore callbacks
6. send_info_email → Firestore email-queue

**Webhook:** https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook

**Feb 11 working setup (Agents SDK + ngrok):**
- Agents SDK server ran on macpro
- ngrok tunnel exposed it to SignalWire
- Call connected, AI spoke for 18 seconds
- This setup should still exist on macpro

### SignalWire Account

- Space: 6eyes.signalwire.com
- Project ID: 6b9a5a5f-7d10-436c-abf0-c623208d76cd
- Phone: +14806024668 (480) — currently SIP 500 blocked (carrier-level, needs 24hr cooldown or support contact)
- Phone: +16028985026 (602) — DEAD, 10/10 platform blocks

### Infrastructure

- Server: macpro (192.168.0.39, SSH can be flaky)
- GCP project: tatt-pro (samson.cirocco@gmail.com)
- Firestore: contacts, call_logs, lead_scores, cold-call-leads, callbacks, email-queue, call_rate
- Tunnel: ngrok (for Agents SDK server)

## Constraints

- **Platform**: SignalWire Agents SDK is the only viable path for AI outbound calls
- **Server**: macpro (Ubuntu, intermittent SSH). Agents SDK server must run persistently there.
- **Phone number**: 480 number currently blocked. Need 24hr cooldown or SignalWire support.
- **Tunnel**: ngrok required to expose local Agents SDK server. Must be persistent (not session-based).
- **Rate limiting**: Rapid test calls trigger carrier blocks. Max 2-3 calls per test burst, then wait.
- **Salesforce**: Needs secrets in GCP Secret Manager (sf-username, sf-password, sf-security-token) — not yet configured.
- **Email**: Needs Gmail app password in .env (GMAIL_USER, GMAIL_APP_PASSWORD) — not yet configured.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use Agents SDK (not Compatibility or Calling API) | Only API that supports AI agents for outbound calls | — Pending (proven Feb 11, needs stable deployment) |
| Keep SWAIG on GCF | Already deployed and working, no reason to move | ✓ Good |
| Simplify where needed, with approval | Lots of scripts built for wrong APIs — may need pruning | — Pending |
| macpro as server | Already set up, has all deps, on local network | ⚠️ Revisit (SSH flaky, consider cloud deployment later) |

---
*Last updated: 2026-02-17 after full debug session and API diagnosis*
