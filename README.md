# AI Voice Caller

Outbound AI voice call system for Fortinet SLED prospecting. Calls using SignalWire, AI agent identifies as "Paul from Fortinet" and collects IT contact info.

**Phone number:** +1 (602) 898-5026  
**SignalWire space:** 6eyes.signalwire.com  
**Dashboard:** https://6eyes.signalwire.com

---

## 🚦 Current Status (as of March 3, 2026)

| Component | Status | Notes |
|---|---|---|
| SignalWire account | ✅ Active | Project ID: `6b9a5a5f...` |
| Phone number | ✅ Owned | +16028985026 (and +14806025848) |
| Outbound calls connect | ✅ Working | Phone rings, call connects |
| AI agent speaks | ✅ FIXED | `make_call_v8.py` — inline SWML, confirmed working Mar 3 |
| Post-call logging | ✅ CONFIRMED | `webhook_server.py` on :18790, logs to `logs/call_summaries.jsonl` — real call verified Mar 3 |
| hooks.6eyes.dev tunnel | ✅ FIXED | Flask server replacing dead Dialogflow server, PM2-managed |
| SWAIG functions | ❌ Not built | Next: log contacts to Salesforce/vault after call |

**Bottom line:** Calls connect, Paul speaks, post-call summaries are captured. Next step is campaign runner + Salesforce writeback.

---

## 🔍 Where We Left Off

Last active session: **March 3, 2026** — silence bug diagnosed and fixed.

### Root causes found (both fixed):
1. **AI agent 404** — Referenced agent `f2c41814...` no longer existed on SignalWire. Every v2–v7 call was routing to a ghost.
2. **Dead SWAIG webhook** — v3–v7 pointed `web_hook_url` at a GCF function (`swaigWebhook`) that was never deployed. SignalWire silently kills AI init when a SWAIG endpoint is unreachable.
3. **Dead hooks server** — port 18790 was running an old Dialogflow `functions-framework` from an abandoned approach. Replaced with `webhook_server.py`.

### Fix applied:
- `make_call_v8.py` — inline SWML with prompt directly in call body, no `ai_agent_id`, no SWAIG, `post_prompt_url` pointing to `https://hooks.6eyes.dev/voice-caller/post-call`
- `webhook_server.py` — Flask server on :18790, catches post-call summaries, appends to `logs/call_summaries.jsonl`
- Confirmed working: call connected, Paul spoke, Mar 3 2026

### Current working script:
```bash
python3 make_call_v8.py                    # Call Samson's cell (test)
python3 make_call_v8.py +1XXXXXXXXXX       # Call any number
```

---

## 📁 Project Structure

```
ai-voice-caller/
├── README.md                  ← You are here
├── make_call_v7.py            ← Latest diagnostic call script (3 approaches)
├── make_call_v2.py            ← Last known working call (basic AI agent)
├── server.py                  ← Flask webhook server for SWML responses
├── call.py                    ← Simple outbound call trigger
├── config/
│   └── signalwire.json        ← Credentials (do not commit)
├── webhook/                   ← Node.js webhook server (alternative to server.py)
├── directives/
│   └── voice-caller-core.md  ← Full system directive
├── execution/
│   ├── log_call.py            ← Log call outcomes to vault
│   └── save_contact.py        ← Save collected contacts
└── logs/                      ← Call logs and debug output
```

---

## 🚀 Quick Start (once fixed)

```bash
# Test a call (baseline — cXML Say, no AI)
python3 make_call_v7.py +16022950104 --approach a

# Test AI agent via relay-bin
python3 make_call_v7.py +16022950104 --approach b

# Test AI agent via GCF webhook
python3 make_call_v7.py +16022950104 --approach c
```

---

## 🔧 Debugging the Silence Issue

Run in order to narrow down the cause:

**Step 1 — Test baseline (no AI):**
```bash
python3 make_call_v7.py +16022950104 --approach a
```
Expected: Phone rings, hears TTS "Hello! This is a test call from SignalWire."  
If this fails → carrier/infra issue. If it works → problem is AI layer specifically.

**Step 2 — Check relay-bin SWML:**
Open https://6eyes.signalwire.com/relay-bins in the dashboard.  
Verify `f2fad3f1-ec3d-4155-91d2-c7993f8c8d4e` exists and contains valid SWML with `ai_agent_id`.

**Step 3 — Check AI agent:**
Open https://6eyes.signalwire.com/neon/frames/auto_create/ai_agents  
Verify agent `f2c41814-4a36-436b-b723-71d5cdffec60` ("Discovery Mode") is active.

**Step 4 — Check call logs:**
```bash
tail -50 logs/auto_recovery.log
```

---

## 📞 Credentials

| Item | Value |
|---|---|
| Project ID | `6b9a5a5f-7d10-436c-abf0-c623208d76cd` |
| Space URL | `6eyes.signalwire.com` |
| Auth Token | In `config/signalwire.json` and `.env` |
| Primary number | `+16028985026` |
| Backup number | `+14806025848` |
| AI Agent ID | `f2c41814-4a36-436b-b723-71d5cdffec60` |
| Relay-bin SWML | `f2fad3f1-ec3d-4155-91d2-c7993f8c8d4e` |

---

## 📋 Next Steps (priority order)

- [x] ~~Fix AI silence bug~~ — done Mar 3, `make_call_v8.py`
- [x] ~~Fix hooks.6eyes.dev~~ — done Mar 3, `webhook_server.py`
- [x] ~~Wire post_prompt_url~~ — done Mar 3, summaries log to `logs/call_summaries.jsonl`
- [x] ~~Fix summary field mapping~~ — done Mar 3, SignalWire sends `post_prompt_data.raw` not `post_prompt_result`
- [ ] **Make 5 test calls** — verify summaries are useful before building storage
- [ ] **Export SD/NE district leads** — CSV from Salesforce or SLED toolkit
- [ ] **Build campaign runner** — batch caller with configurable delay, reads from CSV
- [ ] **Salesforce writeback** — push captured contacts into the right SF account record
- [ ] **Refine Paul's prompt** — tune based on real call outcomes

---

## 📚 Relevant Docs

- [SignalWire SWML Reference](https://developer.signalwire.com/sdks/reference/swml/)
- [SignalWire AI Agent API](https://developer.signalwire.com/rest/signalwire-rest/endpoints/fabric/ai-agents/)
- [SignalWire Calling API](https://developer.signalwire.com/rest/signalwire-rest/endpoints/calling/calls/)
