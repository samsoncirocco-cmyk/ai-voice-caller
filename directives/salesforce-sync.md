# Directive: Salesforce Sync

## Purpose
Push AI voice caller data from Firestore to Salesforce CRM so sales reps have
full visibility into AI-generated leads, call activities, and follow-ups.

## Authentication
- Salesforce credentials stored in **GCP Secret Manager** (project: tatt-pro)
  - `sf-username` - Salesforce username (email)
  - `sf-password` - Salesforce password
  - `sf-security-token` - Salesforce security token
- Uses `simple-salesforce` Python library
- Script: `execution/sync_salesforce.py`

## Firestore -> Salesforce Field Mapping

### contacts (status: new) -> Account + Contact + Task
| Firestore Field | SF Object | SF Field |
|---|---|---|
| account | Account | Name |
| name | Contact | FirstName / LastName |
| phone | Contact | Phone |
| (auto) | Contact | LeadSource = 'AI Outbound Call' |
| call_sid | Task | Description (reference) |
| (auto) | Task | Subject = 'AI Discovery Call - Contact Captured' |

- If Account exists (name match): reuse it
- If Contact exists (under Account, name match): update phone
- Otherwise: create new Account + Contact
- Always create completed Task linking Contact to Account
- After sync: Firestore status -> 'synced_to_sf', sf_account_id, sf_contact_id added

### call_logs -> Event (Type: Call)
| Firestore Field | SF Object | SF Field |
|---|---|---|
| call_sid | Event | Description (reference) |
| outcome | Event | Subject = 'AI Call - {outcome}' |
| duration | Event | DurationInMinutes |
| transcript | Event | Description (truncated 500 chars) |
| to (phone) | Event | WhatId (Account via Contact phone lookup) |

### lead_scores -> Task (score-based priority)
| Score Range | Priority | Task Subject |
|---|---|---|
| >= 70 (hot) | High | Schedule demo - {name} (score: N) |
| 40-69 (warm) | Normal | Send info - {name} (score: N) |
| < 40 (cold) | Skipped | No SF task created |

### cold-call-leads -> Lead
| Firestore Field | SF Object | SF Field |
|---|---|---|
| name | Lead | FirstName / LastName |
| company/account | Lead | Company |
| phone | Lead | Phone |
| email | Lead | Email |
| (auto) | Lead | LeadSource = 'AI Cold Call' |

### callbacks -> Task (follow-up)
| Firestore Field | SF Object | SF Field |
|---|---|---|
| name | Task | Subject = 'Callback - {name}' |
| reason/notes | Task | Description |
| callback_time | Task | ActivityDate |
| phone | Task | WhoId (Contact via phone lookup) |
| (auto) | Task | Priority = High |

## CLI Usage
```bash
# Full sync (all collections)
python3 execution/sync_salesforce.py

# Preview only (no SF writes, no SF creds needed)
python3 execution/sync_salesforce.py --dry-run

# Filter by date
python3 execution/sync_salesforce.py --since 2026-02-10

# Single collection
python3 execution/sync_salesforce.py --collection contacts

# Verbose
python3 execution/sync_salesforce.py --dry-run -v
```

## Dry-Run Behavior
- Connects to Firestore and reads all docs normally
- Logs what *would* be synced but makes no SF API calls
- Does NOT require SF credentials
- Use for testing Firestore reads and verifying data shape

## Error Handling
- SF connection failure: exits with error, suggests --dry-run
- Per-doc errors: logged and counted, does not stop other docs
- Exit code 1 if any errors occurred
- Idempotent: already-synced docs (status: synced_to_sf / synced_to_sf: true) are skipped

## Setup Requirements
1. GCP Secret Manager secrets must exist:
   - `sf-username`: your.email@company.com
   - `sf-password`: your Salesforce password
   - `sf-security-token`: from SF Settings > Reset Security Token
2. Python deps: `pip install simple-salesforce google-cloud-secret-manager google-cloud-firestore`
3. GCP auth: `gcloud auth application-default login` on the machine running the script

## Self-Anneal Loop
1. Run `--dry-run` to verify Firestore reads
2. Set up SF secrets with real credentials
3. Run live sync on a single collection: `--collection contacts`
4. Verify in Salesforce UI
5. Scale to full sync
