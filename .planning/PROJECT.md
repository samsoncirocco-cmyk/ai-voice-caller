# PROJECT.md — AI Voice Caller

## What This Is

An autonomous outbound calling platform for Samson's Fortinet SLED territory (SD/NE/IA). An AI agent named "Paul" cold-calls IT contacts at K-12 schools, municipalities, counties, utilities, and government agencies to qualify interest in Fortinet network security and book meetings.

## Tech Stack

| Layer | Tech | Notes |
|---|---|---|
| Call engine | SignalWire SWML | Inline SWML, no relay-bin needed |
| AI voice | OpenAI Onyx (Lane A) / GCloud Casual-K (Lane B) | A/B test two voices |
| Post-call hook | Flask webhook server on :18790 | PM2: `hooks-server`, public via `hooks.6eyes.dev` |
| Account DB | SQLite + CSV | 816 SLED accounts in `campaigns/sled-territory-832.csv` |
| Smart routing | `execution/smart_router.py` | Vertical-aware prompt + caller-ID selection |
| SFDC integration | `execution/call_outcome_sfdc.py`, `sfdc_live_sync.py` | Push outcomes → Salesforce tasks/opps |
| Call logging | `logs/call_summaries.jsonl` | Flat JSONL, one entry per call |
| Campaign runner | `campaign_runner_v2.py` | Research → batch call → log |

## Phone Numbers

| Lane | Number | Voice | Prompt |
|---|---|---|---|
| A (Municipal/K-12) | +16028985026 | `openai.onyx` | `prompts/paul.txt` |
| B (Cold List) | +14806024668 | `gcloud.en-US-Casual-K` | `prompts/cold_outreach.txt` |

## Current State (as of 2026-03-07)

- **Calls made:** ~28 (32 log entries including test/synthetic)
- **Meetings booked:** 2
- **Accounts available:** 816 in SLED CSV
- **Smart router:** Built (`execution/smart_router.py`) — vertical detection, time gating, performance tuning — not yet wired as default
- **SFDC scripts:** Exist but not automated (`execution/call_outcome_sfdc.py`, `execution/sfdc_live_sync.py`)
- **Directives written:** 10 (campaign-runner, dashboard, follow-up, salesforce-sync, territory-targeting, etc.)

## Key Files

```
make_call_v8.py              # Single call — loads voice+prompt from args
campaign_runner_v2.py        # Batch caller with research + spacing
run_k12_campaign.py          # K-12 specific runner
webhook_server.py            # Post-call logging webhook
execution/smart_router.py    # Intelligent routing (vertical + performance)
execution/account_db.py      # SQLite account state (checkout/checkin/outcome)
execution/call_outcome_sfdc.py  # Push call outcomes to Salesforce
execution/sfdc_live_sync.py  # Live sync from SFDC → local DB
logs/call_summaries.jsonl    # All call outcomes (JSONL)
campaigns/sled-territory-832.csv  # 816 SLED accounts
campaigns/accounts.db        # SQLite account state
```

## Business Context

- **Territory:** South Dakota, Nebraska, Iowa (SD/NE/IA)
- **Verticals:** K-12 schools, municipalities, counties, higher ed, state agencies
- **Goal:** Book discovery calls → Fortinet SD-WAN / SASE / FortiGate opportunities
- **Rep:** Samson Cirocco (Fortinet SLED AE, scirocco@fortinet.com)
- **SignalWire project:** `6b9a5a5f-7d10-436c-abf0-c623208d76cd` at `6eyes.signalwire.com`
