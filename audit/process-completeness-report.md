# Process Completeness Report — AI Voice Caller
*Audit Date: 2026-03-13 | Agent: audit-agent-4-process*

---

## 1. Script Inventory

| Script | What It Does | Status | Recommended Action |
|---|---|---|---|
| `webhook_server.py` | Flask server on port 18790 (hooks.6eyes.dev). Receives SignalWire post-call callbacks, SFDC live-sync events, Outlook sync. Logs call_summaries.jsonl. | ✅ **WIRED** (PM2: hooks-server) | None — correctly managed by PM2 |
| `execution/orchestrator.py` | Multi-agent call orchestrator. Spins up N agents (max 4), routes via SmartRouter, places calls via make_call_v8, waits for webhooks. Business hours enforcement. Smart vertical routing. | ✅ **WIRED** (manually triggered) | Correct — should remain manual per CARDINAL RULES |
| `campaign_runner_v2.py` | Batch caller. Research → SWML → SignalWire → webhook wait. Handles resume, dry-run, business hours. Used by run_k12_campaign.py. | ✅ **WIRED** (called by run_k12_campaign.py) | None — correct as-is |
| `run_k12_campaign.py` | Dedicated K-12 campaign runner. Filters accounts.db for Education:Lower-Education verticals in IA/NE/SD, exports CSV, drives campaign_runner_v2.py with k12.txt prompt. Posts Slack summary. | ✅ **WIRED** (manually triggered) | None — should remain manual |
| `research_agent.py` | Pre-call research via OpenRouter → Perplexity Sonar (or OpenAI fallback). Generates personalized context, opening hooks, objection handlers, contact discovery. Module imported by campaign_runner_v2. | ✅ **WIRED** (imported as module) | Consider adding OPENROUTER_API_KEY health check to pre-campaign check |
| `execution/send_emails.py` | Reads Firestore `email-queue` collection. Renders email templates (case study, overview, pricing inquiry), sends via SMTP. Supports --list/--dry-run/--send. | ⚠️ **ORPHANED** (no cron, never scheduled) | **ADD CRON**: Every 30 min during business hours |
| `k12_campaign_monitor.py` | Polls campaign_log.jsonl + call_summaries.jsonl until target call count is reached. Posts results to Slack #call-blitz. Creates SFDC Tasks for "Meeting Booked" outcomes. Hardcoded target=20 calls, max wait=120 min. | ⚠️ **ORPHANED** (manually started after campaigns, often forgotten) | Add to run_k12_campaign.py as subprocess, or add nightly reconciliation cron |
| `post_campaign_results.py` | Analyzes today's campaign results from campaign_log.jsonl + call_summaries.jsonl. Posts formatted stats to Slack #call-blitz. Dry-run capable. | ⚠️ **ORPHANED** (no cron, no caller) | **ADD CRON**: Nightly 6pm MST on campaign days |
| `call_monitor.py` | Checks SignalWire health by analyzing recent calls. Detects BLOCKED / DEGRADED / CARRIER_ISSUES / HEALTHY state. Supports --watch (5min polling) and --probe (test call). | ⚠️ **ORPHANED** (no cron, run ad hoc) | **ADD CRON**: Every 15 min, alert if BLOCKED or DEGRADED |
| **`process_callbacks.py`** | **SOURCE FILE DOES NOT EXIST.** Only a compiled .pyc exists at `execution/__pycache__/process_callbacks.cpython-312.pyc`, indicating the source was present in git history (commit `ae7c974`) then stripped. This was the SignalWire callback processor. | ❌ **BROKEN / DELETED** | **MUST REBUILD**: Source missing. Pyc confirms it existed and was wired to execution/. Rebuild from pyc or reconstruct from webhook_server.py callback logic. |
| `execution/sfdc_live_sync.py` | Pulls SFDC Accounts + Opportunities modified in last N hours → upserts to accounts.db → updates caller state machine for Closed Won/Lost. | ✅ **WIRED** (cron: midnight MST daily) | None |
| `execution/performance_tracker.py` | Tracks call outcomes (answered/voicemail/interested etc.) by prompt, voice, time-of-day, state. Feeds smart_router.py best-variant selection. Slack digest Mondays. | ✅ **WIRED** (cron: Monday 8am MST) | Ensure `backfill` sub-command is run once to catch historical summaries |
| `execution/smart_router.py` | Routes calls by vertical (K-12/Gov/Higher Ed), time windows, state load-balancing, performance-based prompt selection. Used by orchestrator.py. | ✅ **WIRED** (imported as module) | None |
| `execution/sync_salesforce.py` | Pushes call_summaries.jsonl to SFDC as completed Tasks. Resolves AccountId from CSV or name lookup. Optional contact creation with confidence gates. | ⚠️ **SEMI-WIRED** (no cron, manual post-campaign) | **ADD CRON**: Daily 7pm MST (after sfdc_live_sync) |
| `sfdc_pull.py` | Pulls SFDC Accounts → CSV (legacy) or accounts.db sync. Territory filter IA/NE/SD. | ⚠️ **ORPHANED** (replaced by sfdc_live_sync.py for most use cases) | Deprecate or document as "manual bootstrap" tool |
| `sfdc_push.py` | Pushes call results to SFDC using sfdc_guardrails. Wrapper around sync_salesforce.py pattern. | ⚠️ **ORPHANED** (overlaps sync_salesforce.py) | Consolidate into sync_salesforce.py |
| `execution/pre_campaign_check.py` | Pre-flight health checks before campaign runs. | ⚠️ **ORPHANED** (not called by run_k12_campaign.py) | Wire into run_k12_campaign.py as first step |
| `execution/account_db.py` | AccountDB class — SQLite CRUD wrapper for campaigns/accounts.db. Used by orchestrator, smart_router, sfdc_live_sync. | ✅ **WIRED** (imported as module) | None |
| `execution/referral_processor.py` | Processes referral contacts extracted from AI call summaries. | ⚠️ **ORPHANED** (no caller/cron found) | Review + wire to post_campaign_results.py or add cron |

---

## 2. Cron Audit

### Currently Active Crons (ai-voice-caller related)

```
# SFDC nightly sync — midnight MST
0 7 * * * cd .../ai-voice-caller && python3 execution/sfdc_live_sync.py >> logs/sfdc-sync.log

# Performance digest — Monday 8am MST
0 15 * * 1 cd .../ai-voice-caller && python3 execution/performance_tracker.py slack-digest >> logs/performance_tracker.log
```

### 🚨 Missing Crons That Should Exist

| Script | Suggested Schedule | Rationale |
|---|---|---|
| `execution/send_emails.py` | `*/30 8-17 * * 1-5` | Process email queue every 30 min business hours. Currently emails queued by AI calls are NEVER SENT. |
| `call_monitor.py` | `*/15 * * * *` | Every 15 min to detect BLOCKED status early. Currently discovered only when campaigns fail. |
| `post_campaign_results.py` | `0 18 * * 1-5` | Nightly 6pm MST summary. Currently only run manually (often forgotten). |
| `execution/sync_salesforce.py` | `0 19 * * 1-5` | Daily 7pm push after sfdc_live_sync runs. Currently SFDC tasks are never logged automatically. |
| **`process_callbacks.py`** | **`*/15 * * * *`** | **SOURCE MISSING — rebuild required first. This was meant to be the 15-min callback processor.** |

---

## 3. Dependency Issues

### Venv Status: `venv/` (active) and `.venv/` (secondary) both present

#### ✅ Installed and working
- `flask`, `fastapi`, `uvicorn` — webhook_server OK
- `google-cloud-firestore` — send_emails.py OK
- `signalwire`, `signalwire_agents` — call placement OK
- `simple-salesforce`, `SQLAlchemy` — SFDC sync OK
- `requests`, `beautifulsoup4` — research_agent OK

#### ⚠️ Potential Issues
| Issue | Detail |
|---|---|
| `openai` package not in venv pip list | research_agent.py uses `OPENAI_API_KEY` for fallback. If OPENROUTER fails, the fallback import may fail at runtime. Check: `pip show openai`. |
| Two venvs (`venv/` + `.venv/`) | Potential drift. Scripts use `venv/` shebang path via activation. Confirm hooks-server PM2 config uses correct venv. |
| `OPENROUTER_API_KEY` not in .env verification | research_agent.py fails silently (empty string check), which means calls get made with zero research context. No pre-flight validates this. |
| Cron scripts use `/usr/bin/python3` | System python3 ≠ venv python3. sfdc_live_sync cron should use `venv/bin/python3` or `source venv/bin/activate &&`. |

---

## 4. PM2 Audit

| Process | Status | Notes |
|---|---|---|
| `hooks-server` (webhook_server.py) | ✅ Online | Correct — webhook server should always be PM2-managed |
| `brain-sync-daemon` | ✅ Online | Unrelated to voice caller |
| `second-brain` | ✅ Online | Unrelated to voice caller |

**Q: Should `campaign_runner` or `orchestrator` ever be PM2-managed?**
**A: No.** Per CARDINAL RULES, calls may only fire when Samson explicitly starts them. PM2 would auto-restart crashed campaigns, potentially re-dialing contacts without authorization. Always run manually.

---

## 5. Priority Order — What to Wire Up First

| Priority | Action | Why |
|---|---|---|
| 🔴 **P0** | **Rebuild `process_callbacks.py`** | Source deleted. .pyc proves it existed. This is the callback processor and was meant to have a 15-min cron. Without it, in-flight callbacks may be unprocessed. |
| 🔴 **P0** | **Add cron for `send_emails.py`** | Emails offered during calls are queued in Firestore but NEVER SENT. Real contacts were promised follow-ups that never arrived. |
| 🟠 **P1** | **Add cron for `call_monitor.py`** | SignalWire blocking goes undetected until next manual campaign run. A 15-min health check would auto-alert on Slack. |
| 🟠 **P1** | **Add cron for `execution/sync_salesforce.py`** | Call activities not being written to SFDC daily = pipeline data is stale. sfdc_live_sync brings SFDC→local but sync_salesforce.py does local→SFDC (Tasks). |
| 🟡 **P2** | **Wire `pre_campaign_check.py` into `run_k12_campaign.py`** | Pre-flight isn't called before campaigns start. Saves failed runs. |
| 🟡 **P2** | **Add nightly cron for `post_campaign_results.py`** | Results are never automatically summarized. Samson has to remember to run it. |
| 🟢 **P3** | **Consolidate `sfdc_push.py` + `sfdc_pull.py`** | Overlapping functionality with sfdc_live_sync.py + sync_salesforce.py. Deprecate legacy scripts. |
| 🟢 **P3** | **Add `openai` package to venv** | Ensure research_agent.py fallback works if OpenRouter is down. |
| 🟢 **P3** | **Fix cron python path** | sfdc_live_sync cron uses `/usr/bin/python3` not `venv/bin/python3`. May miss venv packages. |

---

## 6. process_callbacks.py Investigation

- **Source file**: MISSING from all directories
- **Evidence of past existence**: `execution/__pycache__/process_callbacks.cpython-312.pyc` exists
- **Git history**: Script was present at initial commit `ae7c974` and stripped in `24b5f4c ("chore: strip old iterations, keep production scripts only")`
- **Test command result**: `[NOT FOUND] process_callbacks.py does not exist in root`
- **Conclusion**: The script was intentionally removed during a cleanup but the .pyc was left behind. The functionality it provided (processing SignalWire callbacks) is now partially handled by `webhook_server.py`'s `/voice-caller/post-call` endpoint. The question is whether the batch-processing version (processing queued callbacks offline) was a separate function that got lost.

---

*Report generated by audit-agent-4-process | 2026-03-13*
