# Directive: Salesforce Sync

## Purpose
Push AI voice caller data from `logs/call_summaries.jsonl` to Salesforce CRM.
Source of truth is the flat JSONL log (NOT Firestore — Firestore is legacy/unused).

## Authentication
- Uses `sf` CLI (already authenticated, alias: `production`)
- Script calls `sf data query` and `sf data create/upsert` via subprocess
- No GCP secrets or simple_salesforce passwords needed
- Script: `execution/sync_salesforce.py`

## Data Sources

### Primary: `logs/call_summaries.jsonl`
Each line is one post-call webhook payload:
```json
{
  "timestamp": "ISO8601",
  "call_id": "uuid",
  "to": "+16055551234",
  "from": "+16028985026",
  "summary": "Spoke with Jane Smith, IT Director, interest 3/5...",
  "raw": { ... full call log ... }
}
```

### Join: `campaigns/sled-territory-832.csv`
Maps phone → account_name. Fields: `phone, name, account, notes`.
Used to enrich call records with account_name when not embedded.

### Future: `sf_account_id` in CSV
`build_campaign_from_salesforce.py` should export AccountId alongside account name
so the sync can match by ID (not fuzzy name). Until then, falls back to name lookup.

## Research Cache: `campaigns/.research_cache/*.json`
Pre-call research files contain structured contact candidates per account.
Used to propose contacts to create in SFDC (confidence-gated).

## SFDC Object Mapping

### Call Log → Activity (Task)
| JSONL Field     | SF Object | SF Field               |
|-----------------|-----------|------------------------|
| call_id         | Task      | Description (ref)      |
| timestamp       | Task      | ActivityDate           |
| summary         | Task      | Description            |
| account_name    | Task      | WhatId (Account)       |
| (auto)          | Task      | Subject = 'AI Call - {outcome}' |
| (auto)          | Task      | Status = 'Completed'   |

### Research Contact Candidates → Contact (confidence-gated)
| Research Field  | SF Object | SF Field               |
|-----------------|-----------|------------------------|
| name            | Contact   | FirstName / LastName   |
| title           | Contact   | Title                  |
| email           | Contact   | Email                  |
| phone           | Contact   | Phone                  |
| source_url      | Contact   | Description (ref)      |
| (auto)          | Contact   | LeadSource = 'AI Research' |
| (auto)          | Contact   | AccountId (matched)    |

## Confidence Rules (CRITICAL — do not skip)

| Confidence | source_type               | Action                              |
|------------|---------------------------|-------------------------------------|
| high       | official_directory        | Create/upsert Contact on Account    |
| medium     | linkedin / news_mention   | Create Task: "Verify IT contact: [name]" |
| low        | web_mention / generic     | Skip — do not write to SFDC         |
| unknown    | any                       | Skip                                |

**Never auto-create contacts from unverified web mentions.**

## Account Matching (in order)
1. **sf_account_id in CSV** → use directly (most reliable)
2. **SFDC name query** → `SELECT Id FROM Account WHERE Name = '...'`
3. **No match** → skip this record, log warning, do NOT create Account

Do not create new Accounts from the sync script. Account creation is manual.

## CLI Usage
```bash
# Dry run — shows what would be synced, no SF writes
python3 execution/sync_salesforce.py --dry-run

# Sync all unprocessed call logs
python3 execution/sync_salesforce.py

# Sync with research contacts (confidence-gated)
python3 execution/sync_salesforce.py --with-contacts

# Limit to specific date
python3 execution/sync_salesforce.py --since 2026-03-01

# Single account (for testing)
python3 execution/sync_salesforce.py --account "Tripp-Delmont School District"

# Verbose
python3 execution/sync_salesforce.py --dry-run -v
```

## Sync State
Processed call_ids are tracked in `logs/sf_sync_state.json` to avoid duplicate writes.
Format: `{"synced_call_ids": ["uuid1", "uuid2", ...]}`

## Error Handling
- Account not found → skip + warn (never create account)
- SF API error → log error, continue with next record
- Duplicate detection → check sf_sync_state.json before writing
- Exit code 1 if any errors occurred

## Self-Anneal Loop
1. Run `--dry-run -v` to verify JSONL reads and account matching
2. Test on 2-3 known accounts: `--account "Aberdeen Catholic School System" --dry-run`
3. Run live on single account, verify in SF UI
4. Scale to full sync
