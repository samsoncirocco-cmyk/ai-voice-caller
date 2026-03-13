# SFDC Push Debugger Report
**Generated:** 2026-03-13  
**Agent:** audit-agent-2-sfdc  
**Status:** Root cause identified — Pushed: 0 since inception

---

## TL;DR

`sfdc_push.py` has **never successfully pushed** because:
1. Call log entries don't carry `sfdc_id` — the account linkage is lost the moment a call is dispatched
2. The fallback phone lookup (`_query_account_by_phone`) queries Salesforce SOQL but returns 0 results for **every phone number** tested — including real campaign accounts
3. Most archived calls were to test phone numbers (`+16022950104` = Samson's personal phone) that don't exist in SFDC or accounts.db

---

## SF CLI Auth Status

✅ **Working.** Verified with:
```
sf data query --query "SELECT Id, Name FROM Account LIMIT 3" --target-org fortinet --json
```
Returns 3 accounts, `status: 0`. Alias `fortinet` resolves correctly via `sfdc_guardrails.resolve_target_org()`.

---

## Root Cause Analysis

### Root Cause 1 (Primary): `sfdc_id` Never Written to Call Log

The call lifecycle has **two** write points to `call_summaries.jsonl`, and neither includes `sfdc_id`:

**Write point A — `campaign_runner_v2.py:append_pending_summary_stub()`:**
```python
stub = {
    "call_id": call_id,
    "phone": phone,
    "account": account,       # ← just the name string, not account_id or sfdc_id
    "timestamp": ...,
    "status": "pending",
    # sfdc_id NOT included even though accounts.db has it for all 703 accounts
}
```

**Write point B — `webhook_server.py` post-call log:**
```python
log_entry = {
    "timestamp": ...,
    "call_id": call_id,
    "to": swml_call.get("to_number", ...),
    "from": swml_call.get("from_number", ...),
    "summary": summary,
    "raw": data
    # sfdc_id NOT included — webhook has no way to look it up
}
```

Result: `sfdc_push.py` receives entries with no `sfdc_id`, falls through to phone lookup, which fails.

---

### Root Cause 2 (Secondary): Phone Lookup Returns 0 Results — Always

`_query_account_by_phone()` runs:
```sql
SELECT Id, Name FROM Account WHERE Phone LIKE '%{last10}%' LIMIT 1
```

Tested every phone number seen in the call archive against SFDC:

| Phone | In accounts.db? | In SFDC (LIKE query)? |
|-------|----------------|----------------------|
| +16022950104 | No | No — test number (Samson's phone) |
| +14803870992 | No | No — test number |
| +18303582245 | No | No — test number |
| +14802997325 | No | No — test number |
| +16414562731 (real account) | Yes — `0012H00001cFKW9QAO` | **No** — SFDC Account.Phone format mismatch |

Even for real campaign accounts, the SOQL LIKE query returns 0 results. SFDC stores phone numbers in a different format than E.164 (`+1XXXXXXXXXX`). The `accounts.db` phone column uses E.164; SFDC Accounts may use `(641) 456-2731` or `641-456-2731` — the last10 digits are the same but the LIKE match on account records doesn't find them.

---

### Root Cause 3 (Contributing): Live `call_summaries.jsonl` Was Empty

At the time of the last run (`2026-03-12T18:47:16Z`), `call_summaries.jsonl` had exactly **1 entry** (already pushed, `sf_task_id` set), giving `skipped: 1, processed: 0`. The archive of 31 entries was the test archive, not being read by the live script.

---

## Dry-Run Results (Archive — 31 entries)

```
Total entries: 31
  [0]  NO PHONE — skip
  [1]  NO PHONE — skip
  [2-12] phone=+16022950104 | sfdc_id=MISSING → SOQL returns 0 → skip (all 11)
  [13]  ALREADY PUSHED sf_task_id=00THr00009kyOntMAE → skip
  [14-22] phone=+16022950104 | sfdc_id=MISSING → SOQL returns 0 → skip (all 9)
  [23-25] phone=+14803870992 | sfdc_id=MISSING → SOQL returns 0 → skip (3)
  [26-27] phone=+18303582245 | sfdc_id=MISSING → SOQL returns 0 → skip (2)
  [28-30] phone=+14802997325 | sfdc_id=MISSING → SOQL returns 0 → skip (3)

Processed: 0 | Created: 0 | Skipped: 30 | Errors: 0
```

Every entry is skipped. Exactly mirrors production behavior.

---

## Other Bugs Found in sfdc_push.py

### Bug 1: `args.dry_run` should be `args.dry_run` — actually OK (argparse sets it correctly)

### Bug 2: State file path is relative — breaks when run from any other directory
```python
STATE_PATH = "logs/sfdc-push-state.json"
SUMMARIES_PATH = "logs/call_summaries.jsonl"
```
These are relative paths. If the script is run from anywhere other than the project root, it fails silently or creates files in the wrong place. Should use `Path(__file__).parent`.

### Bug 3: `_parse_disposition` defaults to "Connected"
If the summary has no `- Call outcome:` line, returns `"Connected"` as default. This would tag no-answer / voicemail calls as "Connected" in SFDC. Should default to `"No Answer"` or infer from context.

### Bug 4: Shell injection risk in task values
The `values` string built for `sf data create record` escapes single quotes but passes the entire summary as a shell-interpolated string. Long summaries with backticks or special chars could cause issues. Should use `--json` and pass a JSON body instead.

---

## The Fix

### Step 1: Pass `sfdc_id` and `account_id` through `append_pending_summary_stub()`

**File:** `campaign_runner_v2.py`

```python
# BEFORE:
def append_pending_summary_stub(call_id, phone, account):
    stub = {
        "call_id": call_id,
        "phone": phone,
        "account": account,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }

# AFTER:
def append_pending_summary_stub(call_id, phone, account_name, sfdc_id=None, account_id=None):
    stub = {
        "call_id": call_id,
        "phone": phone,
        "account": account_name,
        "sfdc_id": sfdc_id,          # ← Salesforce Account ID (e.g. 0012H00001cFKW9QAO)
        "account_id": account_id,    # ← campaigns.db UUID
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
```

**Call site update** (campaign_runner_v2.py ~line 605):
```python
# BEFORE:
append_pending_summary_stub(result["call_id"], account["phone"], account["account_name"])

# AFTER:
append_pending_summary_stub(
    result["call_id"],
    account["phone"],
    account["account_name"],
    sfdc_id=account.get("sfdc_id"),
    account_id=account.get("account_id"),
)
```

### Step 2: `sfdc_push.py` — Use `sfdc_id` Directly (Fast Path)

**File:** `sfdc_push.py` — replace the account lookup block in `main()`:

```python
# BEFORE:
phone_last10 = _last10(item.get("to") or item.get("from"))
if not phone_last10:
    skipped += 1
    continue

account = _query_account_by_phone(phone_last10)
if not account or not account.get("Id"):
    skipped += 1
    continue

# AFTER:
# Fast path: use sfdc_id if present (set by caller at dispatch time)
sfdc_id_direct = item.get("sfdc_id") or item.get("sf_account_id")
account_name_direct = item.get("account") or item.get("sf_account_name", "")

if sfdc_id_direct:
    account = {"Id": sfdc_id_direct, "Name": account_name_direct}
    print(f"  Direct sfdc_id={sfdc_id_direct} for call_id={call_id}")
else:
    # Fallback: phone lookup (only if sfdc_id not available)
    phone_last10 = _last10(item.get("to") or item.get("from") or item.get("phone", ""))
    if not phone_last10:
        print(f"  SKIP call_id={call_id}: no phone or sfdc_id")
        skipped += 1
        continue
    account = _query_account_by_phone(phone_last10)
    if not account or not account.get("Id"):
        print(f"  SKIP call_id={call_id}: account not found (phone={phone_last10})")
        skipped += 1
        continue
```

### Step 3: Fix Relative Paths

**File:** `sfdc_push.py`

```python
# BEFORE:
SUMMARIES_PATH = "logs/call_summaries.jsonl"
STATE_PATH = "logs/sfdc-push-state.json"

# AFTER:
_HERE = Path(__file__).resolve().parent
SUMMARIES_PATH = str(_HERE / "logs" / "call_summaries.jsonl")
STATE_PATH = str(_HERE / "logs" / "sfdc-push-state.json")
```

### Step 4: Fix Default Disposition

```python
# BEFORE:
return "Connected"  # default

# AFTER:
return "No Answer"  # safe default — don't claim Connected when unknown
```

---

## Backfill Note

The 30 non-pushed entries in the archive and any pending real calls cannot be auto-backfilled because:
- The `sfdc_id` was never written to those logs
- Phone numbers don't resolve in SFDC

For any real production calls (non-test), Samson would need to manually match call logs to accounts and either:
1. Add `sfdc_id` manually to those JSONL entries and re-run `sfdc_push.py --all`
2. Or write a one-time backfill script that queries accounts.db by phone, gets `sfdc_id`, and patches the JSONL

---

## Summary

| Issue | Impact | Fix Location |
|-------|--------|-------------|
| `sfdc_id` not written to call log | **All pushes fail** | `campaign_runner_v2.py:append_pending_summary_stub()` |
| SFDC phone LIKE query returns 0 results | **Fallback also fails** | `sfdc_push.py:_query_account_by_phone()` (replace with direct ID use) |
| Test calls dominate the log | **Nothing to push anyway** | Campaign hygiene — use real account phones |
| Relative paths | Silent failure if run from wrong dir | `sfdc_push.py` path constants |
| Wrong default disposition | SFDC data quality | `sfdc_push.py:_parse_disposition()` |
