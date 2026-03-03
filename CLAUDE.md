# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

---

## Project Overview

Autonomous outbound AI calling system for Fortinet SLED prospecting. Paul calls IT contacts at city/county/municipal governments in SD, NE, IA — qualifies them, logs structured summaries. Two-lane A/B setup testing voices and scripts.

**SignalWire space:** 6eyes.signalwire.com | **GCP project:** tatt-pro
**Lane A:** +16028985026 · `openai.onyx` · `prompts/paul.txt` (municipal/government)
**Lane B:** +14806024668 · `gcloud.en-US-Casual-K` · `prompts/cold_outreach.txt` (cold list)

---

## Common Commands

```bash
# Single test call (defaults: Lane A, openai.onyx, paul.txt)
python3 make_call_v8.py
python3 make_call_v8.py +16025551234

# Call with explicit voice/prompt/from
python3 make_call_v8.py +16025551234 --voice openai.onyx --prompt prompts/paul.txt --from +16028985026
python3 make_call_v8.py +16025551234 --voice gcloud.en-US-Casual-K --prompt prompts/cold_outreach.txt --from +14806024668

# Dry run campaign (research only, no calls placed)
python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --dry-run

# Run live campaign
python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --limit 10 --interval 240 --business-hours
python3 campaign_runner_v2.py campaigns/sled-territory-832.csv --resume  # resume interrupted run

# Research a single account (standalone)
python3 research_agent.py "Aberdeen City" "South Dakota" "Municipal"

# Start/check webhook server
python3 webhook_server.py
# Production: PM2 name = hooks-server, port 18790

# View call summaries
tail -f logs/call_summaries.jsonl

# Deploy SWAIG webhook to Cloud Functions (if needed)
cd execution/
gcloud functions deploy swaigWebhook \
  --gen2 --runtime=python312 --region=us-central1 \
  --source=. --entry-point=swaig_handler \
  --trigger-http --allow-unauthenticated \
  --memory=256MB --project=tatt-pro
```

---

## Architecture

### Call Flow (production)

```
campaign_runner_v2.py
  └─ research_agent.py → Perplexity Sonar (OpenRouter) → account intel
       └─ build_dynamic_swml() → personalized SWML payload
            └─ POST /api/calling/calls → SignalWire
                 └─ AI speaks (openai.onyx or gcloud voice)
                      └─ post_prompt_url → https://hooks.6eyes.dev/voice-caller/post-call
                           └─ webhook_server.py (Flask, port 18790, PM2-managed)
                                └─ logs/call_summaries.jsonl
```

### Single test call flow
```
make_call_v8.py → inline SWML → same webhook path above
```

### Key Files

| File | Purpose |
|------|---------|
| `make_call_v8.py` | Single call script — `--voice`, `--prompt`, `--from` args |
| `campaign_runner_v2.py` | Batch caller — research → personalized SWML → call → log |
| `research_agent.py` | Pre-call research via Perplexity Sonar (OpenRouter); also exports `build_dynamic_swml()` |
| `webhook_server.py` | Flask server on :18790, receives post-call summaries |
| `prompts/paul.txt` | Paul's municipal/government script — **edit here, no code changes needed** |
| `prompts/cold_outreach.txt` | Cold list script — all verticals, qualify/disqualify fast |
| `config/signalwire.json` | All credentials (gitignored) |
| `logs/call_summaries.jsonl` | Post-call AI summaries, one JSON per line |
| `campaigns/` | Lead CSV files |
| `campaigns/.state/` | Resume state per campaign run |
| `campaigns/.research_cache/` | Cached Perplexity research per account |
| `directives/voice-caller-core.md` | Primary directive — read before any call-related work |
| `execution/swaig_server.py` | Cloud Function for SWAIG callbacks (save_contact, log_call, score_lead) |

### Infrastructure

- **Tunnel:** cloudflared → `hooks.6eyes.dev` → localhost:18790
- **Webhook server:** PM2 name `hooks-server`, confirmed live
- **SWAIG endpoint:** `https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook`
- **Legacy SWML server:** PM2 name `caller-server`, port 3001, `caller.6eyes.dev` (used only by old `call.py`)

### Available Voices (best → most robotic)

```
elevenlabs.thomas     — most human (needs ElevenLabs linked to SW account)
openai.onyx           — deep male, very natural ← Lane A default
openai.echo           — lighter male, natural
gcloud.en-US-Casual-K — Google casual male ← Lane B default
rime.marsh:arcana     — newer engine, natural
amazon.Matthew-Neural — avoid
```

---

## Critical SignalWire API Knowledge

### What WORKS for AI outbound calls

**Calling API + inline SWML** (used by both `make_call_v8.py` and `campaign_runner_v2.py`):
```
POST /api/calling/calls  with  "swml": { inline SWML with "ai" block }
```

The `ai` block must include a `languages` array with `voice` set — without it, falls back to amazon.Matthew.

### What DOES NOT work

| Attempt | Result |
|---------|--------|
| Calling API with `params.url` pointing to SWML host | 200 but call never connects |
| Compatibility API with `Swml` param | 422 error |
| Compatibility API with `Url` pointing to JSON SWML | Instant fail (expects LaML XML) |
| `PUT/PATCH /api/fabric/resources/{id}` to update agent | 404 — not supported |

**To update a SignalWire AI agent:** delete via `DELETE /api/fabric/resources/{resource_id}` then recreate.

### Rate Limits (config/signalwire.json)

- 30s minimum between calls
- 20 calls/hour, 100 calls/day
- Auto-cooldown (5 min) after 3 consecutive failures

### Failure pattern diagnosis

| Pattern | Meaning |
|---------|---------|
| `status=failed, duration=0, sip=None` | Platform rate-limited — stop, wait 5+ min |
| `status=failed, duration=0, sip=500` | Carrier rejection — wait 60s, retry once |
| `status=failed, duration=1-2s` | SWML/agent config error |

---

## Environment Variables (.env)

```
OPENROUTER_API_KEY=...   # Primary — Perplexity Sonar for pre-call research
OPENAI_API_KEY=...        # Fallback if OpenRouter unavailable
```

---

## Operating Principles

**Check for tools first.** Before writing a script, check `execution/` and consult the relevant directive in `directives/`. Only create new scripts if none exist.

**Self-anneal when things break:**
1. Read error + stack trace
2. Fix the script, test it (check with user first if it uses paid credits)
3. Update the directive with what you learned
4. System is now stronger

**Update directives as you learn.** Don't create or overwrite directives without asking unless explicitly told to.

**Model preference:** Use `claude-opus-4-6` for reasoning/generation tasks.

---

## File Organization

- `prompts/` — AI call scripts (edit these directly, no code changes needed)
- `campaigns/` — Lead CSVs; `.state/` = resume state; `.research_cache/` = Perplexity cache
- `logs/` — `call_summaries.jsonl` (primary), `auto_recovery.log` (legacy)
- `config/signalwire.json` — Credentials + rate limits (gitignored)
- `execution/` — Deterministic Python scripts (legacy + Cloud Functions)
- `directives/` — SOPs in Markdown (living documents)
- `.tmp/` — Intermediates (never commit)

**Legacy files (do not use for new work):** `call.py`, `server.py`, `execution/campaign_runner.py`, `make_call_v2.py` through `make_call_v7.py`
