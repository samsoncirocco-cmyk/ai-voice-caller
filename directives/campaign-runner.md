# Campaign Runner Directive

## Purpose
Batch outbound calling from CSV contact lists with rate-limit protection, resume support, and Firestore logging.

## Execution Script
`execution/campaign_runner.py`

## CSV Format
| Column  | Required | Description                    |
|---------|----------|--------------------------------|
| phone   | Yes      | Phone number (any US format)   |
| name    | Yes      | Contact name                   |
| account | No       | Company/account name           |
| notes   | No       | Context for the call           |

Place CSV files in `campaigns/` directory.

## Usage

### Dry Run (validate CSV, no calls)
```bash
python3 execution/campaign_runner.py campaigns/sample.csv --campaign-name test --dry-run
```

### Live Run
```bash
python3 execution/campaign_runner.py campaigns/sample.csv --campaign-name outreach-feb
```

### Resume Interrupted Campaign
```bash
python3 execution/campaign_runner.py campaigns/sample.csv --campaign-name outreach-feb --resume
```

## Rate Limits (from config/signalwire.json)
- **30s** minimum between calls
- **20 calls/hour** maximum
- **100 calls/day** maximum
- **5-minute cooldown** after 3 consecutive failures

The runner automatically waits when hitting interval or hourly limits. Daily limits and cooldowns cause contacts to be skipped.

Rate state is shared with make_call_v4.py via Firestore `call_rate` collection.

## Resume Behavior
- State tracked in `campaigns/.state/{campaign-name}.json`
- Records which CSV row indices have been processed
- Use `--resume` flag to skip already-completed contacts
- Safe to interrupt with Ctrl+C and resume later

## Output
- Results CSV: `campaigns/sample_results.csv` (adds result_status, call_sid, duration columns)
- Firestore: `campaign_runs` collection (summary per run)
- Firestore: `campaign_calls` collection (per-call detail)

## Call Flow
1. Read CSV, normalize phone numbers
2. Check rate limits (wait or skip if blocked)
3. POST to Compatibility API: `/api/laml/2010-04-01/Accounts/{project_id}/Calls.json`
4. Wait 20s, check call status via GET
5. Detect platform rate-limiting (0 duration, no SIP code)
6. Record success/failure for rate limiter
7. Save state after each call (for resume)
8. Write results CSV and log to Firestore when done

## Known Issues
- Platform-level rate limiting can silently fail calls (0 duration, no SIP code)
- Compatibility API only - never use Calling API (`/api/calling/calls`)
- Rapid sequential calls trigger carrier blocks; the 30s interval protects against this
