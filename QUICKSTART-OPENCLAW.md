# OpenClaw Skill: Quick Start Guide

## 5-Minute Setup

### 1. Prepare Your CSV File

Create or use an existing CSV with this format:

**Example: `campaigns/test-leads.csv`**
```csv
phone,name,account,notes
+16022950104,John Smith,Aberdeen City Government,IT Manager - call after 2pm
(602) 295-9999,Jane Doe,Tripp-Delmont School District,Sheriff IT contact
6025551234,,Pierre SD Education,"E-Rate eligible, budget cycle July"
+14066667777,Mike Johnson,Sioux Falls,Call Monday
```

**Columns:**
- `phone` — required (any format: +1XXXXXXXXXX, (XXX) XXX-XXXX, or XXXXXXXXXX)
- `name` — optional (contact name)
- `account` — optional (organization name)  
- `notes` — optional (context for the call)

### 2. Set Environment Variables

OpenClaw will prompt you for these. Have them ready:

```
SIGNALWIRE_PROJECT_ID=abc123def456...      [from SignalWire dashboard]
SIGNALWIRE_AUTH_TOKEN=pat_abcd1234...      [from SignalWire → Project → Settings]
OPENROUTER_API_KEY=sk-or-v1-abcd1234...    [from OpenRouter → Account]
OPENAI_API_KEY=sk-...                      [optional — fallback only]
```

### 3. Run Your First Test (Dry Run — No Calls)

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/test-leads.csv \
  --campaign-name test-dry-run \
  --dry-run
```

**What happens:**
- ✅ Loads CSV (4 leads)
- ✅ Researches each organization (via OpenRouter)
- ❌ **Does NOT place calls**
- ✅ Logs research results
- ✅ Shows what would be called

**Output:**
```
[2026-03-03T10:05:00Z] INFO     Campaign started
[2026-03-03T10:05:01Z] DEBUG    Loaded leads from CSV             total_leads=4
[2026-03-03T10:05:10Z] INFO     Researching account via OpenRouter account=Aberdeen City Government
[2026-03-03T10:05:15Z] INFO     Research completed                 account=Aberdeen City Government contacts_found=2
[2026-03-03T10:05:15Z] INFO     DRY RUN: Would place call          phone=+16022950104 account=Aberdeen City Government
[2026-03-03T10:06:00Z] INFO     Campaign completed ================...
  status: success
  campaign_name: test-dry-run
  calls_attempted: 4
  calls_placed: 0
  calls_failed: 0
  results_csv: campaigns/.results/test-dry-run_results.csv
  ...
```

### 4. Run a Limited Live Test (5 Calls)

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/test-leads.csv \
  --campaign-name test-5-calls \
  --limit 5 \
  --voice-lane A
```

**What happens:**
- ✅ Loads CSV
- ✅ Researches each organization
- ✅ Places call #1 via SignalWire → AI speaks
- ✅ Waits 30 seconds (rate limit)
- ✅ Places call #2
- ... continues until 5 calls placed or leads exhausted
- ✅ Saves results to CSV and JSONL log

**Output (example):**
```
[2026-03-03T10:10:00Z] INFO     Processing lead                    phone=+16022950104 account=Aberdeen City
[2026-03-03T10:10:05Z] INFO     Researching account via OpenRouter account=Aberdeen City
[2026-03-03T10:10:10Z] INFO     Research completed                 account=Aberdeen City contacts_found=1
[2026-03-03T10:10:10Z] INFO     Placing call                       to=+16022950104 from_number=+16028985026 voice=openai.onyx
[2026-03-03T10:10:12Z] INFO     SignalWire API response            status_code=200
[2026-03-03T10:10:12Z] INFO     Call initiated successfully        call_id=abc123def456 to=+16022950104

[WAITING 30 SECONDS...]

[2026-03-03T10:10:42Z] INFO     Processing lead                    phone=(602) 295-9999 account=Tripp-Delmont School
...
```

### 5. Check Results

After the campaign runs, check the outputs:

**Campaign Results CSV:**
```bash
cat campaigns/.results/test-5-calls_results.csv
```

```csv
phone,name,account,call_status,call_id,duration_seconds,outcome,timestamp
+16022950104,John Smith,Aberdeen City Government,initiated,abc123def456,,Connected,2026-03-03T10:10:12Z
(602) 295-9999,Jane Doe,Tripp-Delmont School District,initiated,def456ghi789,,Connected,2026-03-03T10:10:42Z
6025551234,,Pierre SD Education,initiated,ghi789jkl012,,No Answer,2026-03-03T10:11:12Z
+14066667777,Mike Johnson,Sioux Falls,initiated,jkl012mno345,,Connected,2026-03-03T10:11:42Z
```

**Call Summaries (JSONL):**
```bash
cat logs/call_summaries.jsonl | tail -5
```

```json
{"timestamp":"2026-03-03T10:10:15Z","call_id":"abc123def456","summary":"- Call outcome: Connected\n- Spoke with: John Smith\n- Role: IT Manager\n- Organization: Aberdeen City Government\n- Current vendor: Cisco\n- Interest level: 4\n- Follow-up: Will send email with Fortinet options"}
{"timestamp":"2026-03-03T10:10:45Z","call_id":"def456ghi789","summary":"- Call outcome: Connected\n- Spoke with: Jane Doe\n- Role: Technology Coordinator\n- Organization: Tripp-Delmont School\n- Current vendor: Meraki\n- Interest level: 3\n- Follow-up: Call back next month"}
```

**Campaign Log:**
```bash
tail -20 logs/campaign_test-5-calls.log
```

Shows every step: API calls, research, rate limiting, errors, etc.

---

## Common Scenarios

### Scenario 1: Run Campaign in Business Hours Only

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/sled-territory.csv \
  --campaign-name daily-run \
  --limit 20 \
  --voice-lane A \
  --business-hours-only
```

**Behavior:**
- If it's 8am-5pm Central: start calling immediately
- If it's outside business hours: wait until 8am next morning
- Once 5pm hits: pause and resume at 8am

### Scenario 2: Resume a Paused Campaign

You started a campaign but it hit the rate limit or you stopped it manually:

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/sled-territory.csv \
  --campaign-name daily-run \
  --resume
```

**Behavior:**
- Loads campaign state from `.state/daily-run_campaign.json`
- Skips leads already called
- Resumes from where it left off
- Continues until limit or end of CSV

### Scenario 3: Use Lane B (Cold List Voice)

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/cold-list.csv \
  --campaign-name cold-calls \
  --limit 10 \
  --voice-lane B
```

**Changes from Lane A:**
- Voice: `gcloud.en-US-Casual-K` (Google casual male)
- From Number: `+14806024668`
- Script: `prompts/cold_outreach.txt` (generic, works for any industry)
- Persona: Professional but adaptable

### Scenario 4: Extended Run (100+ Calls)

For a full territory run:

```bash
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file campaigns/full-territory-sled.csv \
  --campaign-name full-territory-march \
  --limit 75 \
  --interval-seconds 30 \
  --voice-lane A \
  --business-hours-only
```

**Rate Limits Applied:**
- 30 seconds between each call (automatic)
- 20 calls/hour maximum (script waits when hitting this)
- 100 calls/day maximum (script honors this; you'd need to resume tomorrow if you hit it)
- 5-minute cooldown after 3 consecutive failures

**Timeline for 75 calls:**
- First 20 calls → 1 hour (30s interval)
- Hour window resets
- Next 20 calls → 1 hour
- ... continues
- Total: ~3.75 hours of actual calling time

### Scenario 5: Test a Single Contact

```bash
# Create a 1-row CSV
echo "phone,name,account,notes
+16025551234,Test User,Test Organization,Testing the skill" > test-single.csv

# Run test
openclaw skill run fortinet-sled-voice-campaign \
  --csv-file test-single.csv \
  --campaign-name test-single \
  --limit 1
```

---

## What to Expect During Execution

### Timeline for a 5-Call Campaign

```
[10:10:00] Load CSV → 4 leads loaded
[10:10:01] Load config → SignalWire ready
[10:10:02] Initialize rate limiter
[10:10:05] Processing lead 1: +16022950104
[10:10:06] Researching Aberdeen City via OpenRouter...
[10:10:12] Research complete (2 contacts found)
[10:10:12] Building SWML with personalized hooks
[10:10:13] Placing call via SignalWire...
[10:10:15] ✅ Call 1 initiated (call_id: abc123)

[10:10:15 - 10:10:45] RATE LIMIT: Waiting 30 seconds...

[10:10:45] Processing lead 2: (602) 295-9999
[10:10:46] Researching Tripp-Delmont School...
[10:10:52] Research complete
[10:10:52] Placing call...
[10:10:54] ✅ Call 2 initiated (call_id: def456)

[10:10:54 - 10:11:24] RATE LIMIT: Waiting 30 seconds...

[10:11:24] Processing lead 3: 6025551234
...
[10:12:00] Campaign reached limit (5 calls) — stopping
[10:12:00] Saving campaign state...
[10:12:01] Exporting results CSV...
[10:12:02] ✅ Campaign completed
   - Total leads: 4
   - Calls attempted: 5 (includes rate-limited skips)
   - Calls placed: 5
   - Results: campaigns/.results/test-5-calls_results.csv
```

### What Happens During Each Call

1. **Research (5-10 seconds)**
   - OpenRouter API call with organization name + location
   - Returns: contacts, pain points, tech intel, hooks
   - Cached for future runs

2. **SWML Building (<1 second)**
   - Injects research intel into prompt
   - Creates personalized greeting with research hooks

3. **API Call (1-2 seconds)**
   - POST to SignalWire Compatibility API
   - Returns call_id if successful

4. **Call Progress (varies)**
   - Call ringing on the recipient's phone
   - AI agent begins speaking (static greeting)
   - Conversation happens in real-time

5. **Post-Prompt (after call hangs up)**
   - SignalWire asks the AI to summarize the call
   - AI responds with structured summary
   - Webhook receives and logs the summary
   - Summary appears in `call_summaries.jsonl`

---

## Error Scenarios & Recovery

### "Rate limited" (3 consecutive failures)

```
[10:20:00] ❌ Call failed (network error)
[10:20:01] ❌ Call failed (network error)
[10:20:02] ❌ Call failed (network error)
[10:20:03] 🛑 3 CONSECUTIVE FAILURES — entering 5-minute cooldown
[10:20:03] Program continues but SKIPS the next leads...
[10:25:03] ✅ Cooldown expired — resuming calls
```

**To recover:** Use `--resume` flag later to continue

### "Research timeout" (OpenRouter unavailable)

```
[10:15:30] 📚 Researching Aberdeen City...
[10:15:45] ⏱️  Request timeout (>30 seconds)
[10:15:45] ⚠️  Research failed, skipping call for this lead
[10:15:45] → Next lead...
```

**Behavior:** Skips that specific call, continues with next lead (no crash)

### "Invalid phone number"

```
[10:10:00] Loaded 5 leads from CSV
[10:10:01] ⚠️  Invalid phone: "555" (too short) → skipping
[10:10:01] ⚠️  Invalid phone: "abc-def" (not a number) → skipping
[10:10:01] 📊 4 valid leads ready to call
[10:10:02] Processing lead 1...
```

**Behavior:** Automatically normalizes and skips invalids; continues

### "Missing API key"

```
[10:10:00] ❌ OPENROUTER_API_KEY not set
[10:10:00] ❌ Campaign cannot start
Status: failed
Reason: Missing environment variables
```

**Recovery:** Set the API key and run again. OpenClaw setup prompts guide you.

---

## Viewing Logs & Debugging

### Campaign Log (JSON format)

```bash
cat logs/campaign_test-5-calls.log | jq '.'
```

Shows every action with timestamp:
```json
{
  "timestamp": "2026-03-03T10:10:00Z",
  "level": "INFO",
  "message": "Processing lead",
  "phone": "+16022950104",
  "account": "Aberdeen City"
}
```

### Call Summaries (JSONL, one per line)

```bash
cat logs/call_summaries.jsonl | jq '.'
```

Shows post-call AI summaries:
```json
{
  "timestamp": "2026-03-03T10:10:15Z",
  "call_id": "abc123",
  "summary": "- Call outcome: Connected\n- Spoke with: John\n- Interest level: 4\n..."
}
```

### Results CSV (spreadsheet-friendly)

```bash
cat campaigns/.results/test-5-calls_results.csv
```

```csv
phone,name,account,call_status,call_id,outcome,timestamp
+16022950104,John,Aberdeen City,initiated,abc123,Connected,2026-03-03T10:10:15Z
```

### Campaign State (for resuming)

```bash
cat campaigns/.state/test-5-calls_campaign.json
```

```json
{
  "campaign_name": "test-5-calls",
  "created_at": "2026-03-03T10:10:00Z",
  "processed_indices": [0, 2, 3, 5, 7],
  "calls_placed": 5
}
```

---

## Tips & Best Practices

### ✅ DO:

1. **Start with dry run**
   ```bash
   --dry-run  # Research only, no calls
   ```

2. **Test with small limit first**
   ```bash
   --limit 5  # Just 5 calls to verify everything works
   ```

3. **Use business hours**
   ```bash
   --business-hours-only  # Calls only 8am-5pm Central
   ```

4. **Monitor the first few calls**
   - Watch the console output
   - Check that webhooks are arriving
   - Verify summaries in `call_summaries.jsonl`

5. **Resume campaigns, don't re-run**
   ```bash
   --resume  # Skip already-called leads
   ```

6. **Separate campaigns by segment**
   - `campaign municipal-march`
   - `campaign cold-list-march`
   - `campaign follow-ups`

### ❌ DON'T:

1. **Don't call with interval < 30 seconds**
   - Rate limit will trigger
   - Number may get blocked

2. **Don't bypass the rate limiter**
   - It exists to protect the calling number
   - Platform will silently drop calls if you spam

3. **Don't use without API keys**
   - Script will fail immediately (safely)
   - Have creds ready before starting

4. **Don't interrupt mid-call**
   - OpenClaw timeout (default 1 hour) is plenty
   - Use `--resume` if you need to stop/start

5. **Don't modify the result CSV while campaign is running**
   - Creates race conditions
   - Wait until campaign completes

---

## Success Metrics

### Good Campaign Run

```
✅ Calls attempted: 20
✅ Calls placed: 18
⚠️  Calls failed: 2
✅ Failed count is low (< 3 consecutive)
✅ Results CSV has outcomes for each lead
✅ Call summaries are detailed and structured
✅ Campaign state saved for resuming
```

### Potential Issues

```
❌ Calls placed: 0 (investigate API keys, rate limits)
❌ Calls failed: > 5 (rate limit may be active, wait 5 min)
❌ Missing summaries for all calls (webhook not responding)
⚠️  Interest levels all "1" (script or persona may need tweaking)
```

---

## Next Actions

1. **Prepare your CSV** with a test list of 5 leads
2. **Get API credentials ready** (SignalWire, OpenRouter)
3. **Run a dry run** to validate setup
4. **Run 5 test calls** to verify the full flow
5. **Check results** in the CSV and JSONL logs
6. **Scale up** to production campaigns (20+ calls)

---

## Questions During Execution?

This guide covers the most common scenarios. For deeper details:

1. **Skill Specification:** `openclaw-skill-sled-campaign.md`
2. **Code & Logging:** `skill_fortinet_sled_campaign.py`
3. **Full README:** `README-OPENCLAW-SKILL.md`
4. **Original System:** `CLAUDE.md`, `directives/voice-caller-core.md`

Good luck! 🚀
