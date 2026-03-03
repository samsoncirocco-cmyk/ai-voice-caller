# AI Voice Caller — Fortinet SLED Outreach

Autonomous outbound calling agent for Samson's SD/NE/IA territory. Paul calls IT contacts at schools, cities, counties, utilities, and government orgs, qualifies them, and logs structured summaries.

## Status

| Component | Status | Notes |
|---|---|---|
| Outbound calls | ✅ WORKING | `make_call_v8.py` — inline SWML, no relay-bin |
| Agent dialogue | ✅ WORKING | `openai.onyx` confirmed Mar 3 |
| Post-call logging | ✅ WORKING | `webhook_server.py` on :18790, JSONL log |
| Two-voice A/B | ✅ WORKING | 602 = `openai.onyx`, 480 = `gcloud.en-US-Casual-K` |
| Campaign runner | ✅ READY | `campaign_runner_v2.py` — research + batch calling |
| Pre-call research | ✅ READY | `research_agent.py` — Perplexity Sonar via OpenRouter |
| Webhook server | ✅ PM2 | `hooks-server` on PM2, public at `hooks.6eyes.dev` |

## Voice A/B Test Setup

Two numbers, two voices, two scripts — running in parallel to see which performs better:

| Lane | Number | Voice | Script |
|---|---|---|---|
| A (Municipal) | +16028985026 | `openai.onyx` | `prompts/paul.txt` |
| B (Cold List) | +14806024668 | `gcloud.en-US-Casual-K` | `prompts/cold_outreach.txt` |

## Quick Start

```bash
# Single test call
python3 make_call_v8.py +16022950104

# Specify voice + prompt explicitly
python3 make_call_v8.py +16025551234 --voice openai.onyx --prompt prompts/paul.txt --from +16028985026
python3 make_call_v8.py +16025551234 --voice gcloud.en-US-Casual-K --prompt prompts/cold_outreach.txt --from +14806024668

# Dry run campaign (research only, no calls)
python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --dry-run

# Run campaign (10 calls, 4-min spacing, business hours only)
python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --limit 10 --interval 240 --business-hours
```

## File Structure

```
make_call_v8.py          # Main call script — inline SWML, loads voice+prompt from args
call.py                  # Legacy — uses server.py / caller.6eyes.dev (old approach)
server.py                # Legacy — Feb SWML server, agent named "Matt" (do not use)
campaign_runner_v2.py    # Batch caller — research → personalized SWML → call → log
research_agent.py        # Pre-call research via Perplexity Sonar (OpenRouter)
webhook_server.py        # Flask server on :18790 — receives post-call summaries

prompts/
  paul.txt               # Municipal/government script (city, county, sheriff, tribal)
  cold_outreach.txt      # Cold list script (all verticals — qualify or disqualify fast)

config/
  signalwire.json        # Credentials — GITIGNORED, never commit

logs/
  call_summaries.jsonl   # Flat log of all post-call summaries
  auto_recovery.log      # Legacy worker log

campaigns/               # CSV lead lists go here
```

## Editing Paul's Script

Go to **[prompts/paul.txt](prompts/paul.txt)** or **[prompts/cold_outreach.txt](prompts/cold_outreach.txt)** and edit directly in GitHub. No code changes needed — `make_call_v8.py` loads the file on every call.

## Credentials

All credentials live in `config/signalwire.json` (gitignored):
```json
{
  "project_id": "...",
  "auth_token": "...",   ← rotate at 6eyes.signalwire.com if exposed
  "space_url": "6eyes.signalwire.com",
  "phone_number": "+14806024668"
}
```

Never hardcode credentials. The old token `PT4f6bab11...` was exposed in commit history Mar 3 — rotated same day.

## Post-Call Log Format

`logs/call_summaries.jsonl` — one JSON object per line:
```json
{
  "timestamp": "2026-03-03T17:08:36Z",
  "call_id": "...",
  "from": "+14806024668",
  "to": "+16025551234",
  "summary": "- Spoke with: Mike\n- Role: IT Manager\n- Organization: ..."
}
```

## Infrastructure

- **Webhook server**: PM2 name `hooks-server`, port 18790, public at `https://hooks.6eyes.dev/voice-caller/post-call`
- **Legacy SWML server**: PM2 name `caller-server`, port 3001, public at `https://caller.6eyes.dev` (used by old `call.py` only)
- **SignalWire space**: `6eyes.signalwire.com`
- **Phone numbers**: +16028985026 (Lane A) | +14806024668 (Lane B)

## Campaign Rules

- Max 10–15 calls/hour with randomized spacing
- Call window: 8am–4pm Central (SD/NE/IA)
- Log every outcome: reached / voicemail / wrong number / not interested / meeting booked
- A clean "not interested" is a win — it clears the list

## Next Steps

- [ ] Export SD/NE/IA district + municipal leads to `campaigns/` CSV
- [ ] Run first live campaign batch (5–10 calls) and review summary quality
- [ ] Review A/B voice data after 20+ calls — pick winner or keep both
- [ ] Build Salesforce writeback from `logs/call_summaries.jsonl`
- [ ] Add voicemail detection to skip/leave message automatically
