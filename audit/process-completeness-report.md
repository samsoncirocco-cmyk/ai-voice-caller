# Process Completeness Report — AI Voice Caller
**Date:** 2026-03-13
**Agent:** audit-agent-4-process
**Scope:** Root + execution/ Python scripts not obviously running

---

## Executive Summary

Of the 7 scripts audited, **1 is fully wired**, **1 doesn't exist**, **4 are orphaned but functional**, and **1 has a missing dependency**. The biggest gap is that post-call email sending (`send_emails.py`) has zero automation — emails queued during live calls are never actually sent. Two analytics scripts (`k12_campaign_monitor.py`, `post_campaign_results.py`) also produce zero output unless run manually.

---

## Script-by-Script Audit

### 1. `process_callbacks.py` — ❌ MISSING (Does Not Exist)
| Field | Value |
|-------|-------|
| Status | **MISSING** |
| Location | Not found anywhere in project |
| Called from | Nowhere |
| Cron | None |

**What it should do:** Unknown — name suggests it would process SignalWire/webhook callbacks, possibly as a background processor for call outcome data.

**Recommended action:** CLARIFY what this was supposed to do. If it was meant to process call outcome webhooks, that logic already lives in `webhook_server.py` (specifically the `/call-summary` and `/sfdc-update` handlers). Either document that it was merged into webhook_server, or build it as a standalone offline processor.

---

### 2. `execution/send_emails.py` — 🔴 ORPHANED (High Priority)
| Field | Value |
|-------|-------|
| Status | **ORPHANED** |
| Location | `execution/send_emails.py` |
| Called from | Nowhere |
| Cron | None |
| Imports | ✅ OK (via `venv` python) |

**What it does:** Reads the Firestore `email-queue` collection — populated when the AI agent says "I'll send you that info" during a call — renders templates (case study, overview, pricing, demo request), and sends via SMTP. Has `--list`, `--dry-run`, `--send` modes.

**Why it matters:** Every time Paul/Alex says "I'll email you a case study," that email is queued in Firestore. Without this script running on a schedule, **no emails are ever sent**. This is the biggest operational gap.

**Recommended action:** Add cron job:
```bash
*/30 * * * * cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && venv/bin/python3 execution/send_emails.py --send >> logs/send-emails.log 2>&1
```
Or trigger from `webhook_server.py` after each `send_info` outcome.

---

### 3. `k12_campaign_monitor.py` — 🟡 ORPHANED (Medium Priority)
| Field | Value |
|-------|-------|
| Status | **ORPHANED** |
| Location | `k12_campaign_monitor.py` (project root) |
| Called from | Nowhere (should be called by `run_k12_campaign.py`) |
| Cron | None |
| Imports | ✅ OK (stdlib + requests only) |

**What it does:** Background monitor that polls `campaigns/.state/k12-accounts.json` every 60s, waits until 20 calls have been processed, then reads `logs/call_summaries.jsonl`, posts a Slack summary to `#call-blitz` (`C0AFQ0FPYGM`), and creates SFDC Tasks for "Meeting Booked" outcomes.

**Why it's orphaned:** `run_k12_campaign.py` does NOT spawn it as a subprocess or background process. It's designed to be started alongside the campaign but there's no wiring.

**Recommended action:** Add to `run_k12_campaign.py` (after line 266 where campaign subprocess is spawned):
```python
# Start monitor in background
monitor_proc = subprocess.Popen([sys.executable, str(ROOT / "k12_campaign_monitor.py")])
```
Or run manually: `venv/bin/python3 k12_campaign_monitor.py &`

---

### 4. `post_campaign_results.py` — 🟡 ORPHANED (Medium Priority)
| Field | Value |
|-------|-------|
| Status | **ORPHANED** |
| Location | `post_campaign_results.py` (project root) |
| Called from | Nowhere |
| Cron | None |
| Imports | ✅ OK (stdlib + requests) |

**What it does:** End-of-campaign analytics script. Reads `logs/campaign_log.jsonl` and `logs/call_summaries.jsonl`, computes stats (connection rate, voicemails, meetings booked, hot leads), posts a formatted summary to Slack `#call-blitz`, and creates SFDC Tasks via `sfdc_push.py` subprocess.

**Overlap with k12_campaign_monitor.py:** Both post to #call-blitz and create SFDC tasks. `k12_campaign_monitor` is live/real-time during the run; `post_campaign_results` is a post-mortem analysis. Both should run — monitor during, post-results after.

**Recommended action:** Wire into `run_k12_campaign.py` to run after campaign subprocess completes:
```python
subprocess.run([sys.executable, str(ROOT / "post_campaign_results.py")], cwd=str(ROOT))
```
Or add EOD cron: `0 20 * * 1-5 cd /project && venv/bin/python3 post_campaign_results.py`

---

### 5. `run_k12_campaign.py` — 🟡 ORPHANED (Manual Trigger — OK)
| Field | Value |
|-------|-------|
| Status | **ORPHANED (by design — manual)** |
| Location | `run_k12_campaign.py` (project root) |
| Called from | Nowhere automated |
| Cron | None (correct — has business hours gate) |
| Imports | ✅ OK (stdlib + requests + sqlite3) |

**What it does:** The dedicated K-12 campaign runner. Queries `campaigns/accounts.db` for `vertical IN ('Education: Lower Education', 'K-12', 'K12')`, exports to `campaigns/k12-accounts.csv`, then spawns `campaign_runner_v2.py` with `prompts/k12.txt`. Posts a Slack summary after. Has `--dry-run`, `--limit`, `--force-hours`, `--status` modes. **Business hours gate enforced via campaign_runner_v2.**

**Assessment:** Intentionally manual — should be triggered by Samson saying "run the K-12 caller." No cron needed (would violate CARDINAL RULE re: no calls without approval). But it should wire up `k12_campaign_monitor.py` and `post_campaign_results.py` automatically.

**Recommended action:** Wire child scripts (monitor + post-results) inside `run_k12_campaign.py` so they auto-fire when Samson kicks off a run. No cron.

---

### 6. `call_monitor.py` — 🟡 ORPHANED (Low Priority)
| Field | Value |
|-------|-------|
| Status | **ORPHANED** |
| Location | `call_monitor.py` (project root) |
| Called from | Nowhere |
| Cron | None |
| Imports | ✅ OK (stdlib + requests) |

**What it does:** SignalWire number health checker. Fetches recent 15 calls from the SignalWire API, classifies them as HEALTHY / DEGRADED / BLOCKED / CARRIER_ISSUES based on failure patterns. Has `--watch` mode (polls every 5 min), `--probe` mode (makes a test call). Uses hardcoded API token.

**Recommended action:** Add as pre-campaign check in `run_k12_campaign.py`:
```python
result = subprocess.run([sys.executable, "call_monitor.py"], capture_output=True, text=True, cwd=str(ROOT))
if "BLOCKED" in result.stdout:
    print("[ABORT] SignalWire number is blocked — not starting campaign")
    sys.exit(1)
```
OR add a cron for ongoing monitoring:
```bash
0 */4 * * * cd /project && venv/bin/python3 call_monitor.py >> logs/call-monitor.log 2>&1
```

---

### 7. `research_agent.py` — ✅ WIRED
| Field | Value |
|-------|-------|
| Status | **WIRED** |
| Location | `research_agent.py` (project root) |
| Called from | `campaign_runner_v2.py` (line 56: `from research_agent import research_account, build_dynamic_swml`) |
| Cron | N/A (called inline) |
| Imports | ✅ OK |

**What it does:** Pre-call research engine using OpenRouter → Perplexity Sonar (web-grounded). For each account, generates: summary, contacts with source URLs, two opening hooks, pain points, tech intel, budget cycle, conversation starters. Falls back to OpenAI/xAI grok if OpenRouter unavailable. Used by campaign_runner_v2 to personalize every call.

**No action needed.** Works correctly.

---

## Dependency & Environment Issues

### Two Venvs — Only One Has Full Dependencies
| Venv | Python | Key Packages | Used By |
|------|--------|--------------|---------|
| `venv/` (Feb 11) | 3.12 | SQLAlchemy, simple-salesforce, signalwire, flask-cors | **PM2 (webhook_server)**, should be used by all scripts |
| `.venv/` (Feb 17) | 3.12 | Flask, requests, google-cloud-firestore | Missing sqlalchemy, openai, simple-salesforce |

**Problem:** All scripts use `#!/usr/bin/env python3` — they pick up system Python which may or may not have these packages. The correct venv is `venv/`, confirmed by PM2's interpreter config for hooks-server (`venv/bin/python3`).

**Fix:** When running scripts manually or via cron, always use `venv/bin/python3`, e.g.:
```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && venv/bin/python3 execution/send_emails.py --send
```

### Missing: `openai` module in both venvs
- `venv/`: No openai package installed
- `.venv/`: No openai package installed
- `research_agent.py` falls back to OpenAI/xAI API if OpenRouter fails — but it uses raw `requests`, not the openai SDK, so this is OK

### `send_emails.py` requires Firestore credentials
- Needs `GOOGLE_APPLICATION_CREDENTIALS` or ADC set up
- `.env` in project root has limited keys; Firestore likely uses ADC from gcloud
- **Test first:** `venv/bin/python3 execution/send_emails.py --list` to verify Firestore connection

---

## Missing Cron Jobs

| Priority | Script | Recommended Schedule | Command |
|----------|--------|---------------------|---------|
| 🔴 HIGH | `execution/send_emails.py` | Every 30 min | `*/30 * * * * cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && venv/bin/python3 execution/send_emails.py --send >> logs/send-emails.log 2>&1` |
| 🟡 MED | `call_monitor.py` | Every 4 hours | `0 */4 * * * cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && venv/bin/python3 call_monitor.py >> logs/call-monitor.log 2>&1` |
| 🟢 LOW | `post_campaign_results.py` | Weekday EOD 8pm | `0 20 * * 1-5 cd /home/samson/.openclaw/workspace/projects/ai-voice-caller && venv/bin/python3 post_campaign_results.py >> logs/post-campaign.log 2>&1` |

**Note:** `k12_campaign_monitor.py` should NOT be in cron — it should be spawned programmatically from `run_k12_campaign.py`.

---

## PM2 Assessment

| Process | Status | Notes |
|---------|--------|-------|
| `hooks-server` (webhook_server.py) | ✅ Running | Uses `venv/bin/python3`, correct |
| `brain-sync-daemon` | ✅ Running | Unrelated to voice caller |
| `second-brain` | ✅ Running (103 restarts 😬) | Unrelated to voice caller |
| `campaign_runner_v2.py` | Not in PM2 | **Correct** — runs in tmux via `start_campaign.sh` or `run_k12_campaign.py` |

**Assessment:** PM2 setup is correct. campaign_runner is a one-shot batch job, not a daemon — tmux is the right approach. No changes needed to PM2.

---

## Priority Order: What to Wire Up Next

1. **🔴 `send_emails.py` cron** — Emails queued by AI during calls are currently never sent. Add `*/30 * * * *` cron immediately. Test with `--list` first to see backlog.

2. **🟡 Wire `k12_campaign_monitor.py` into `run_k12_campaign.py`** — Monitor should auto-start as background subprocess when a K-12 campaign fires. One-line change to run_k12_campaign.py.

3. **🟡 Wire `post_campaign_results.py` into `run_k12_campaign.py`** — Should run automatically after campaign subprocess completes. One-line addition.

4. **🟡 `call_monitor.py` as pre-campaign gate** — Add to run_k12_campaign.py to abort if number is BLOCKED. Prevents burning accounts on a dead number.

5. **🟢 `call_monitor.py` cron** — Every 4h background health check. Nice to have, not urgent.

6. **❓ `process_callbacks.py`** — Clarify with Samson: was this planned, merged into webhook_server.py, or obsolete? If needed, build it.

---

## Currently Wired (for reference)

| Script | Trigger | Schedule |
|--------|---------|----------|
| `execution/sfdc_live_sync.py` | cron | Midnight MST daily |
| `execution/performance_tracker.py` | cron | Monday 8am MST |
| `webhook_server.py` | PM2 | Always-on daemon |
| `research_agent.py` | campaign_runner_v2.py | Per-call, inline import |
| `campaign_runner_v2.py` | tmux / run_k12_campaign.py | Manual / per campaign |

---

*Report generated: 2026-03-13 by audit-agent-4-process*
