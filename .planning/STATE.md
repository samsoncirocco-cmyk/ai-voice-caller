# STATE.md — Current State

_Last updated: 2026-03-07_

---

## Platform Health

| Component | Status | Notes |
|---|---|---|
| Outbound calls | ✅ Working | `make_call_v8.py` — inline SWML |
| AI dialogue | ✅ Working | `openai.onyx` confirmed Mar 3 |
| Webhook server | ✅ Live (PM2) | `hooks-server` on :18790, public at `hooks.6eyes.dev` |
| Post-call logging | ✅ Working | `logs/call_summaries.jsonl` (32 entries incl. test) |
| Campaign runner | ✅ Ready | `campaign_runner_v2.py` + `run_k12_campaign.py` |
| K-12 runner | ✅ Ready | `run_k12_campaign.py` with monitor |
| Smart router | 🟡 Built, not wired | `execution/smart_router.py` exists, not default yet |
| SFDC writeback | 🟡 Scripts exist | `execution/call_outcome_sfdc.py` — manual only |
| Daily report | 🔲 Not built | Phase 1 target |
| Callback tracker | 🔲 Not built | Phase 2 target |
| Dashboard | 🔲 Not built | Phase 4 target |

---

## Metrics (as of 2026-03-07)

- **Total calls made:** ~28 (32 JSONL entries; some are test/synthetic)
- **Meetings booked:** 2
- **Accounts in pipeline:** 816 (SLED territory CSV)
- **K-12 accounts:** ~500+ (k12-accounts.csv)
- **Answer rate:** Unknown — need Phase 1 report to calculate
- **Avg interest score:** Unknown — need Phase 1 report to calculate

---

## Active Blockers

| Blocker | Impact | Resolution |
|---|---|---|
| Smart router not wired as default | Manual `--vertical` flag required for every run | Phase 3 fix this weekend |
| No daily reporting | Can't see what's working, can't iterate | Phase 1 fix this weekend |
| Interesting calls not flowing to SFDC | Follow-ups get missed | Phase 2 fix this weekend |
| `campaigns/accounts.db` is empty (0 bytes) | Smart router and account_db.py can't track state | Need to seed from CSV — pre-req for Phase 3 |

---

## Decisions Made

### 2026-03-07 — GSD Planning Session
- **Phone numbers:** Stay with +602 (Lane A, paul.txt) and +480 (Lane B, cold_outreach.txt). No new numbers.
- **Scripts:** Do NOT change `prompts/paul.txt` or `prompts/cold_outreach.txt` this weekend.
- **Dashboard:** Single HTML file, Chart.js CDN, no build step. Served from webhook_server.py.
- **SFDC task threshold:** interest ≥ 3 OR explicit "follow-up" / "meeting" language in summary.
- **Routing defaults:** K-12 → +602 + paul.txt; Municipal/Gov → +602 + paul.txt; Unknown/Cold → +480 + cold_outreach.txt.

### 2026-03-03 — SignalWire credentials rotated
- Old token `PT4f6bab11...` was exposed in commit history. Rotated same day at 6eyes.signalwire.com.

### 2026-03-03 — Inline SWML adopted
- Moved from relay-bin approach to inline SWML in `make_call_v8.py`. Simpler, no server dependency for calls.

---

## Known Issues

1. **accounts.db is empty** — `campaigns/accounts.db` is 0 bytes. The account_db.py script needs to seed it from the CSV before smart_router checkout/checkin can work. Fix: `python3 execution/account_db.py --seed campaigns/sled-territory-832.csv` (or equivalent).

2. **performance_stats.json has zero counts** — All call/answer counts are 0. Smart router's performance-tuner layer has no data to act on yet. It will self-populate after calls run through the new routing layer.

3. **call_summaries.jsonl timestamps** — Some entries have microsecond-precision timestamps (`1772550...`) in call_log entries (SignalWire epoch) and ISO timestamps in the outer wrapper. Parser must handle both.

4. **K-12 campaign running since 09:16** — `k12-campaign-20260307-091649.log` exists, campaign may be in-flight. Check `pm2 list` before starting new runs to avoid duplicate calls.

---

## What's Working Well

- **SWML inline approach** is rock solid — no relay-bin, no extra server needed for calls
- **Research agent** (`research_agent.py`) does pre-call context lookup via Perplexity — useful for personalization
- **Webhook server** is stable on PM2 — hasn't missed a post-call summary
- **Two-voice A/B** (602 = Onyx, 480 = Casual-K) is structurally clean — just needs perf data to pick a winner

---

## Next Actions (Ordered)

1. [ ] Seed `campaigns/accounts.db` from CSV (blocker for Phase 3)
2. [ ] Build `execution/daily_call_report.py` (Phase 1)
3. [ ] Set up cron/PM2 for 5pm daily report to Slack
4. [ ] Build `execution/callback_tracker.py` (Phase 2)
5. [ ] Wire `smart_router.py` into campaign runners (Phase 3)
6. [ ] Build `dashboard.html` + `/dashboard` Flask route (Phase 4)
