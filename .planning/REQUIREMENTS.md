# REQUIREMENTS.md — Weekend Build Scope

## V1 — This Weekend (2026-03-07/08)

These four features ship by Sunday night. They make the platform production-ready for daily use.

---

### 1. Daily Call Report Script

**What:** Script that reads `logs/call_summaries.jsonl` + `logs/campaign_log.jsonl`, generates a formatted daily summary, and posts it to Slack `#call-blitz`.

**Acceptance criteria:**
- Runs via cron at 5pm Central every weekday
- Output includes: calls made, answered, voicemail, not-interested, meetings booked, avg interest score
- Posts to Slack `#call-blitz` (C0AFQ0FPYGM) as a formatted message
- Groups by vertical (K-12 / Municipal / Other)
- Shows delta vs prior day

**Script location:** `execution/daily_call_report.py`
**Cron:** `0 23 * * 1-5 cd ~/... && python3 execution/daily_call_report.py` (5pm Central = 23:00 UTC)

---

### 2. Callback Tracker (Calls → SFDC Tasks)

**What:** Parse `call_summaries.jsonl` for any call with `interest >= 3` or `follow_up: yes` and create a Salesforce Task on the matching account/contact.

**Acceptance criteria:**
- Reads unprocessed call logs (tracks last-synced position)
- Matches `to_number` → Salesforce Account via phone lookup
- Creates Task: Subject = "AI Caller Follow-up", Due = +2 business days, Description = call summary
- Marks entry as synced in state file (idempotent — no duplicate tasks)
- Logs all SFDC write results to `logs/sfdc-push-state.json`

**Script location:** `execution/callback_tracker.py`
**Runs:** On-demand + via post-call webhook trigger

---

### 3. Auto Caller-ID Routing by Vertical

**What:** Wire `execution/smart_router.py` as the default entry point so the campaign runner auto-selects the right caller-ID (+602 vs +480) and prompt file based on account vertical. No more `--vertical` flag needed.

**Acceptance criteria:**
- `smart_router.py` is the default routing layer in `campaign_runner_v2.py` and `run_k12_campaign.py`
- K-12 → +16028985026 + `prompts/paul.txt` (or `prompts/k12.txt`)
- Municipal/County/Gov → +16028985026 + `prompts/paul.txt`
- Cold/Unknown → +14806024668 + `prompts/cold_outreach.txt`
- Respects time-of-day gates already in smart_router.py
- Fallback to manual override if `--from` and `--prompt` are explicitly passed

**No new SignalWire numbers.** Work with +602 and +480 only.

---

### 4. Campaign Dashboard HTML

**What:** Single-page HTML dashboard showing call activity, served from the project directory.

**Acceptance criteria:**
- Reads `logs/call_summaries.jsonl` and `logs/performance_stats.json` at page load (or via AJAX)
- Charts (Chart.js CDN):
  - Calls per day (bar)
  - Outcomes breakdown: answered / voicemail / not-interested / meeting (donut)
  - Interest score distribution (histogram)
  - Calls by vertical (horizontal bar)
- Summary stats: total calls, meetings booked, answer rate, avg interest score
- Served by `webhook_server.py` at `/dashboard` route (or standalone Python http.server)
- No build step — pure HTML/JS/CSS, single file

**File location:** `dashboard.html` in project root

---

## V2 — Next Week (2026-03-10+)

These are planned but not in scope this weekend.

| Feature | Description |
|---|---|
| Multi-vertical A/B testing | Track answer rate and meeting rate per vertical × prompt × voice, auto-promote winners |
| Voicemail drop | Detect VM in call log; trigger pre-recorded voicemail drop instead of live AI |
| SMS follow-up | After positive call (interest ≥ 3), send SMS via SignalWire with calendar link |

---

## Out of Scope (Do Not Build)

- ❌ New SignalWire phone numbers — work with +602 and +480 only
- ❌ Changes to existing call scripts (`prompts/paul.txt`, `prompts/cold_outreach.txt`)
- ❌ New AI voices or providers
- ❌ CRM migrations (stay on Salesforce, no HubSpot/Outreach)
- ❌ Inbound call handling
