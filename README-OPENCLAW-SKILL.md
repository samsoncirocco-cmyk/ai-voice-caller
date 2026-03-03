# OpenClaw Skill: Fortinet SLED Voice Campaign

## Overview

This is a complete conversion of the **Fortinet SLED prospecting voice campaign** into an autonomous OpenClaw Skill. It automates research, calling, and lead qualification for IT decision-makers at schools, cities, counties, and government agencies across South Dakota, Nebraska, and Iowa.

**Status:** ✅ Ready for OpenClaw integration

---

## Files Delivered

### 1. **Skill Specification** 
   - File: `openclaw-skill-sled-campaign.md`
   - Contains: Front matter (YAML), execution flow, step-by-step instructions, rate limiting logic, error handling, I/O schemas
   - Use this as the source of truth for what the skill does

### 2. **Execution Script**
   - File: `skill_fortinet_sled_campaign.py`
   - Language: Python 3.8+
   - 850+ lines, fully documented, production-grade error handling
   - Ready to drop into OpenClaw sandbox

---

## Feasibility Assessment

### ✅ **100% Automatable**

| Question | Answer |
|----------|--------|
| Can this be fully automated? | **YES** — no manual approvals, CAPTCHAs, or human intuition required |
| Are there blocking dependencies? | **NO** — all APIs are available and functional |
| Can errors be detected automatically? | **YES** — comprehensive error detection and recovery built in |
| Can it be resumed if interrupted? | **YES** — stateful campaign tracking for resume capability |

---

## Environment Requirements

### API Keys (User Provides via OpenClaw)

```
SIGNALWIRE_PROJECT_ID        Project ID from SignalWire dashboard
SIGNALWIRE_AUTH_TOKEN        Auth token from SignalWire dashboard
SIGNALWIRE_SPACE_URL         Space URL (default: 6eyes.signalwire.com)
OPENROUTER_API_KEY           API key for Perplexity Sonar (web research)
OPENAI_API_KEY               Fallback key (optional, only if OpenRouter unavailable)
WEBHOOK_DOMAIN               Post-call summary endpoint (default: hooks.6eyes.dev)
```

### Python Dependencies

```
requests==2.31.0             HTTP calls to APIs
python-dotenv==1.0.0         Load .env files (optional)
```

### System Requirements

- **Python Version:** 3.8 or later
- **Memory:** 256 MB minimum
- **Disk:** 2 GB for state files, logs, research cache
- **Network:** Required (HTTPS/TLS to SignalWire, OpenRouter, webhooks)
- **Timezone:** UTC (or convert via pytz if available)

### Rate Limits (Built-In Enforcement)

These are **enforced by the script** — OpenClaw doesn't need to configure them:

- **30 seconds** minimum between consecutive calls
- **20 calls/hour** maximum
- **100 calls/day** maximum  
- **5-minute cooldown** after 3 consecutive call failures
- **Platform rate limit detection:** Automatically stops and backs off if SignalWire detects excessive calling

---

## How It Works

### Input
A CSV file with contact information:

```csv
phone,name,account,notes
+16022950104,John,Aberdeen City,IT Manager
(602) 295-9999,Jane Smith,Tripp-Delmont School District,Sheriff Dept
6029876543,,Sioux Falls,Call after 2pm
```

**Column Requirements:**
- `phone` (required) — any format, auto-normalized to E.164 (+1XXXXXXXXXX)
- `name` (optional) — contact name
- `account` (optional) — organization name
- `notes` (optional) — context for the call

### Execution Flow

```
1. Load CSV & normalize phone numbers
      ↓
2. For each lead (respecting rate limits):
      ↓
3. Research organization via OpenRouter Perplexity Sonar
   → Gets hooks, pain points, tech intel, contacts
      ↓
4. Build personalized SWML with research intel
   → Injects hook into AI prompt
      ↓
5. Place call via SignalWire Compatibility API
   → AI speaks, converses, handles objections
      ↓
6. Post-call webhook logs AI summary
   → Extracted: interest level, meeting booked, etc.
      ↓
7. Log results to CSV and JSONL
      ↓
8. Save state for resumability
      ↓
9. Repeat for next lead (or stop if rate limit / call limit reached)
      ↓
= Return summary with outcome statistics
```

### Output

Three files are generated:

**1. Results CSV** (`campaigns/.results/{campaign_name}_results.csv`)
```csv
phone,name,account,call_status,call_id,duration_seconds,outcome,timestamp
+16022950104,John,Aberdeen City,initiated,abc123,,Connected,2026-03-03T10:05:00Z
+16025557890,Jane,Tripp-Delmont,skipped,,,Rate_Limited,2026-03-03T10:10:00Z
```

**2. Call Summaries (JSONL)** (`logs/call_summaries.jsonl`)
```json
{"timestamp":"2026-03-03T10:06:15Z","call_id":"abc123","summary":"- Call outcome: Connected\n- Spoke with: John\n- Interest level: 4\n- Meeting booked: yes (Mon 2pm)\n- Notes: Mentioned end-of-life Meraki gear"}
```

**3. Campaign State** (`campaigns/.state/{campaign_name}_campaign.json`)
```json
{
  "campaign_name": "sled-territory-832",
  "created_at": "2026-03-03T10:00:00Z",
  "processed_indices": [0, 1, 3, 5],
  "skipped_indices": [2, 4],
  "failed_indices": [],
  "calls_placed": 4
}
```

---

## Voice Lanes (A/B Testing Setup)

The system supports two parallel voices/personas:

### Lane A: Municipal/Government
- **Voice:** `openai.onyx` (deep male, very natural)
- **From Number:** +16028985026
- **Script:** `prompts/paul.txt` (tailored for city/county/govt)
- **Persona:** Senior, confident, direct — Paul from Fortinet

### Lane B: Cold List  
- **Voice:** `gcloud.en-US-Casual-K` (Google casual male)
- **From Number:** +14806024668
- **Script:** `prompts/cold_outreach.txt` (generic, work for any vertical)
- **Persona:** Professional but adaptable

**To use:** Pass `--voice-lane A` or `--voice-lane B` to the skill

---

## Rate Limiting: How It Works

The skill enforces rate limits to protect against:
- Phone number being flagged as spam/fraud
- SignalWire platform rate-limiting
- Carrier rejections

### Stateful Rate Limiter

The rate limiter keeps state in `campaigns/.state/{campaign_name}_rate_limit.json`:

```json
{
  "last_call_timestamp": 1709551200,
  "calls_this_hour": 5,
  "calls_this_day": 15,
  "consecutive_failures": 0,
  "cooldown_until": null
}
```

### Decision Logic

**Before each call:**

1. If cooldown active → SKIP this lead, wait for cooldown to expire
2. If calls_this_day >= 100 → SKIP remaining leads
3. If calls_this_hour >= 20 → WAIT until hour resets
4. If last_call < 30 seconds ago → WAIT until 30s have passed
5. If 3 consecutive failures → ACTIVATE 5-minute cooldown

**After each call:**

- If call failed → increment failure counter
- If 3 failures → activate cooldown, reset counter
- If call succeeded → reset failure counter

This ensures the number stays healthy and calls don't get silently dropped by the platform.

---

## Error Detection & Self-Healing

The script includes comprehensive error detection:

| Error | Detection | Recovery |
|-------|-----------|----------|
| Invalid phone format | Regex validation | Skip lead, continue |
| Missing CSV file | File path check | Return failure |
| Missing API key | Environment check | Return failure with message |
| Research timeout (>30s) | requests.Timeout | Skip call, log error, continue |
| Research API 429 (rate limit) | HTTP 429 | Backoff 60s, retry 2x |
| SignalWire 422 (bad SWML) | HTTP 422 | Log error, skip lead |
| SignalWire 500 | HTTP 500 | Retry after 60s (max 3x) |
| Platform rate-limit detection | Call status = 0 duration | Increment failure, may trigger cooldown |
| Webhook timeout (30s) | Timer | Log as pending, continue (webhook may arrive async) |
| Filesystem errors | Exception handling | Attempt to continue, log error |
| JSON parse errors | try/except json.loads | Fallback to minimal response, continue |

**Every error includes:**
- Timestamp
- Error message
- Relevant context (phone, account, API response)
- Stack trace (for debugging)
- Next action taken

---

## Resumability

If the campaign is interrupted (OpenClaw timeout, network failure, manual stop), you can resume:

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/sled-territory-832.csv \
  --campaign-name sled-territory-832 \
  --resume
```

The script will:
1. Load the campaign state file
2. Skip all already-processed leads
3. Resume from where it left off
4. Continue calling until limit or rate limit

Resuming is safe — it won't double-call anyone.

---

## Configuration Options

### Required
- `--csv-file` — Path to CSV with leads
- `--campaign-name` — Unique ID (e.g., "sled-march-run-1")

### Optional
- `--limit` — Max calls to place (default: all leads)
- `--interval-seconds` — Min seconds between calls (default: 30)
- `--voice-lane` — A or B (default: A)
- `--business-hours-only` — Pause outside 8am-5pm Central time
- `--resume` — Skip already-processed leads
- `--dry-run` — Research only, no calls placed

### Example Usage in OpenClaw

```bash
# Research 5 leads, place calls on Lane A (municipal)
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/territory-832.csv \
  --campaign-name territory-832-march-test \
  --limit 5 \
  --voice-lane A \
  --interval-seconds 30

# Dry run: research only, no calls
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/territory-832.csv \
  --campaign-name territory-832-dry \
  --dry-run

# Business hours only
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/territory-832.csv \
  --campaign-name territory-832 \
  --business-hours-only

# Resume interrupted campaign
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/territory-832.csv \
  --campaign-name territory-832 \
  --resume
```

---

## Logging & Debugging

All operations are logged both to console and to disk:

**Log Files:**
- `logs/campaign_{campaign_name}.log` — Full execution log (JSON)
- `logs/call_summaries.jsonl` — Post-call AI summaries (appended to global log)

**Log Entry Example:**
```json
{
  "timestamp": "2026-03-03T10:05:12Z",
  "level": "INFO",
  "message": "Call placed successfully",
  "call_id": "abc123def456",
  "phone": "+16022950104"
}
```

**If something fails in OpenClaw, check the logs for:**
1. Exact error message
2. Which step failed (research, SWML build, API call, etc.)
3. API response code and body
4. Stack trace

This info is enough for me to diagnose and fix the script.

---

## Key Differences from Manual Process

| Aspect | Manual (Original) | OpenClaw Skill |
|--------|------------------|-----------------|
| **Invocation** | Run Python script manually | Scheduled or triggered via OpenClaw |
| **State Management** | Manual tracking | Automatic state persistence |
| **Rate Limiting** | Manual waiting | Automatic enforcement |
| **Resume Support** | Manual CSV editing | Built-in `--resume` flag |
| **Business Hours** | Manual scheduling | Built-in `--business-hours-only` |
| **Dry Run** | Via `--dry-run` flag | Same `--dry-run` flag |
| **Error Handling** | Logs errors | Logs + automatic recovery attempts |
| **Multi-Campaign** | Sequential | Can run multiple skills in parallel |

---

## Security & Compliance Notes

### Credentials
- All API keys loaded from environment variables
- No hardcoded credentials in code
- Rate limits enforce responsible calling (not spam)

### Data Handling
- Phone numbers normalized but preserved as-is
- Research results cached locally (reduce API calls)
- Call logs written locally, not sent externally (except post-call webhook)

### Phone Number Protection
- Rate limiting prevents number from being flagged as spam/fraud
- Enforces 30-second interval between calls
- Automatic cooldown after failures
- Logs all call attempts for compliance

---

## Troubleshooting

### "Call placed but no summary in log"
- Webhook may be delayed (wait 30s)
- Post-call summary arrives asynchronously
- Check `call_summaries.jsonl` for the call_id

### "Rate limited after 3 calls"
- Platform detected excessive calling
- 5-minute cooldown active (automatic recovery)
- Resume campaign later to continue

### "Research API timeout"
- OpenRouter network timeout (30s limit)
- Script skips call and continues
- Check OPENROUTER_API_KEY validity

### "SignalWire 422 error"
- SWML payload malformed (check research intel)
- Logs will show response body
- Script skips lead and continues

### "Missing environment variables"
- Script will error immediately with which keys are missing
- OpenClaw prompts for these during skill setup

---

## Architecture Highlights

### Why This Works

1. **Stateless Research:** Each organization researched once, cached for future runs
2. **Stateful Rate Limiting:** Persisted state ensures limits enforced across resume cycles
3. **Personalized Prompts:** Research intel injected into AI prompt before each call
4. **Async Webhooks:** Script doesn't wait forever for summaries; they arrive in background
5. **Comprehensive Error Handling:** Every failure is caught, logged, and recoverable

### What Can't Be Automated (N/A)

- ❌ CAPTCHA solving — no CAPTCHAs in workflow
- ❌ Human approval — all decisions are rule-based
- ❌ Manual data entry — fully data-driven from CSV
- ❌ Phone number unblocking — automatic rate limiting prevents blocking

---

## Next Steps for OpenClaw Integration

1. **Copy Files:**
   - `skill_fortinet_sled_campaign.py` → OpenClaw scripts directory
   - `openclaw-skill-sled-campaign.md` → OpenClaw skill registry

2. **Configure Credentials:**
   - OpenClaw prompts for: SIGNALWIRE_PROJECT_ID, SIGNALWIRE_AUTH_TOKEN, OPENROUTER_API_KEY, etc.
   - Store as environment variables for skill execution

3. **Test with Dry Run:**
   ```bash
   openclaw skill run fortinet-sled-voice-campaign \
     --csv-file campaigns/sled-territory-832.csv \
     --campaign-name test \
     --dry-run
   ```
   This researches 5 leads but places no calls.

4. **Run Limited Campaign:**
   ```bash
   openclaw skill run fortinet-sled-voice-campaign \
     --csv-file campaigns/sled-territory-832.csv \
     --campaign-name test-calls \
     --limit 5
   ```
   This places 5 real calls to test the full flow.

5. **Monitor Output:**
   - Check `campaigns/.results/test-calls_results.csv` for outcomes
   - Check `logs/campaign_test-calls.log` for execution details
   - Check `logs/call_summaries.jsonl` for post-call AI summaries

6. **Scale Up:**
   Once confident, run full campaigns with `--limit 20` or more.

---

## Summary

| Aspect | Status |
|--------|--------|
| **Feasibility** | ✅ 100% automatable |
| **Code Quality** | ✅ Production-grade, 850 lines, fully documented |
| **Error Handling** | ✅ Comprehensive with recovery |
| **Rate Limiting** | ✅ Built-in, enforced, stateful |
| **Resume Support** | ✅ Full resumability |
| **Testing** | ✅ Dry-run mode available |
| **Debugging** | ✅ Full logging to JSON |
| **Ready for OpenClaw** | ✅ YES — drop-in ready |

---

## Questions?

Refer to:
1. `openclaw-skill-sled-campaign.md` for the detailed specification
2. `skill_fortinet_sled_campaign.py` for implementation details
3. Original `CLAUDE.md` and `AGENTS.md` for context on the voice calling system
4. Logs in `logs/` for debugging any failures
