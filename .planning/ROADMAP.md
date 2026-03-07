# ROADMAP.md — AI Voice Caller

## Overview

4 phases to turn a working prototype into a daily sales machine. Each phase is independently shippable and adds measurable value.

---

## Phase 1 — Daily Call Report + Slack Cron

**Target:** This weekend | **Status:** 🔲 Not started

**Goal:** Know exactly what happened each day without manually reading JSONL.

**Deliverables:**
- `execution/daily_call_report.py` — parses JSONL logs, generates formatted summary
- Cron entry on paul-macpro (or PM2 scheduled task) at 5pm Central weekdays
- Posts to Slack `#call-blitz` (C0AFQ0FPYGM) with:
  - Total calls / answered / voicemail / not-interested / meetings
  - Avg interest score
  - Breakdown by vertical
  - Delta vs yesterday
- Sample output pinned in `#call-blitz` channel

**Why this first:** No other improvements matter if we can't see what's working. This is the feedback loop.

**Dependencies:** None (reads existing logs)

---

## Phase 2 — Callback Tracker (Meetings Booked → SFDC Tasks)

**Target:** This weekend | **Status:** 🔲 Not started

**Goal:** Every promising call automatically creates a follow-up Task in Salesforce. No manual data entry.

**Deliverables:**
- `execution/callback_tracker.py` — reads call logs, pushes Tasks to SFDC
- State file `logs/sfdc-push-state.json` (already exists, extend it)
- Task format: Subject = "AI Caller Follow-up | {account}", Due = +2 business days, Description = full call summary
- Run on-demand + triggered post-call from `webhook_server.py`
- Threshold: interest ≥ 3 OR summary contains "follow-up: yes" / "meeting agreed"

**Why second:** Meeting pipeline is the business metric. Once calls are logged, we need them to flow into SFDC automatically so Samson doesn't drop the ball.

**Dependencies:** Phase 1 (same log format knowledge). `execution/call_outcome_sfdc.py` exists — extend it.

---

## Phase 3 — Auto Caller-ID Routing

**Target:** This weekend | **Status:** 🔲 Not started

**Goal:** Campaign runner auto-picks the right number (+602 or +480) and script based on account vertical. Kill the `--vertical` flag.

**Deliverables:**
- `execution/smart_router.py` wired as default in `campaign_runner_v2.py` and `run_k12_campaign.py`
- Routing table (finalized):
  - K-12 / Education → +16028985026 + `prompts/paul.txt`
  - Municipal / County / Government → +16028985026 + `prompts/paul.txt`
  - Unknown / Cold → +14806024668 + `prompts/cold_outreach.txt`
- Manual `--from` and `--prompt` flags still work as explicit overrides
- `execution/smart_router.py` already has vertical detection logic — just needs wiring

**Why third:** Makes the campaign runner zero-config for Samson. Just run it, it figures out the rest.

**Dependencies:** None (smart_router.py is already built, just needs integration)

---

## Phase 4 — Campaign Dashboard HTML

**Target:** This weekend | **Status:** 🔲 Not started

**Goal:** Visual campaign overview — one page that tells the whole story at a glance.

**Deliverables:**
- `dashboard.html` — single-file, no build step, Chart.js from CDN
- Charts:
  - Calls per day (bar chart, last 14 days)
  - Outcome breakdown: answered / voicemail / not-interested / meeting booked (donut)
  - Interest score distribution 1–5 (histogram)
  - Calls by vertical: K-12 / Municipal / Higher Ed / Other (horizontal bar)
- KPI strip: Total Calls | Meetings Booked | Answer Rate | Avg Interest Score
- Data source: reads `logs/call_summaries.jsonl` via Python endpoint OR inline JSON generated at build time
- Served at `/dashboard` on `webhook_server.py` (Flask, already running on PM2)
- Mobile-readable (no horizontal scroll)

**Why last:** Nice to have but not blocking sales activity. Phases 1–3 are pure ROI. Phase 4 is visibility.

**Dependencies:** Phase 1 (same log parsing logic can be reused)

---

## Success Metrics

| Metric | Current | Target (end of weekend) |
|---|---|---|
| Calls per day (capacity) | Manual | Automated batch, 20–30/day |
| SFDC task creation | Manual | Automatic for interest ≥ 3 |
| Daily reporting | None | Slack post at 5pm Central |
| Routing config | Manual `--vertical` flag | Zero-config |
| Call visibility | Raw JSONL | Live dashboard |

---

## Future Phases (V2, Not This Weekend)

| Phase | Feature | ETA |
|---|---|---|
| 5 | Multi-vertical A/B testing with auto-promotion | Week of Mar 10 |
| 6 | Voicemail detection + pre-recorded drop | Week of Mar 10 |
| 7 | SMS follow-up after positive calls | Week of Mar 17 |
| 8 | Calendar integration (auto-book from call intent) | TBD |
