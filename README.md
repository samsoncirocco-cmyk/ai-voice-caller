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
| AI agent speaks | ❌ BROKEN | **Calls connect but agent is silent** |
| SWML webhook | ⚠️ Unclear | Multiple approaches tested, none confirmed working |
| SWAIG functions | ❌ Not built | Planned for CRM/contact logging |

**Bottom line:** Infrastructure works, calls get through. The AI agent silently connects but won't speak. This is the active blocker.

---

## 🔍 Where We Left Off

Last active debugging: **Feb 17, 2026**

### What was tried:
- `make_call_v7.py` — 3 diagnostic approaches (A/B/C):
  - **Approach A** (cXML `<Say>` baseline) — tests if carrier/infra works at all
  - **Approach B** (Calling API + SignalWire relay-bin SWML) — tests native AI agent via hosted SWML
  - **Approach C** (Calling API + GCF webhook) — tests external SWML endpoint
- Results were logged but root cause of silence was not confirmed

### Leading hypothesis:
The SWML `ai_agent_id` reference is not triggering the agent correctly — either the relay-bin URL is stale/misconfigured, or the AI agent resource itself is not responding. The baseline test (Approach A) should confirm whether the issue is infrastructure or specifically the AI layer.

### Last confirmed working:
- `make_call_v2.py` — call connected, agent was created, but silence on v3+
- SignalWire AI Agent ID: `f2c41814-4a36-436b-b723-71d5cdffec60`

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

- [ ] **Run Approach A** — confirm baseline works (carrier not blocking)
- [ ] **Run Approach B** — confirm relay-bin SWML is valid
- [ ] **If both work** → problem is inside the AI agent config, not infra
- [ ] **If A works, B fails** → fix relay-bin SWML or replace with inline SWML
- [ ] **If A fails** → new SignalWire number may be needed (spam flagged)
- [ ] Once calls + AI work: build SWAIG function to log contacts to vault
- [ ] Once logging works: build campaign runner for batch calling

---

## 📚 Relevant Docs

- [SignalWire SWML Reference](https://developer.signalwire.com/sdks/reference/swml/)
- [SignalWire AI Agent API](https://developer.signalwire.com/rest/signalwire-rest/endpoints/fabric/ai-agents/)
- [SignalWire Calling API](https://developer.signalwire.com/rest/signalwire-rest/endpoints/calling/calls/)
