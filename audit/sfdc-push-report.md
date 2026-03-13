# SFDC Push Debugger Report

## Root Cause of Pushed: 0
The root cause of `Pushed: 0` is that the `sfdc_push.py` script relies entirely on matching the call's `to` or `from` phone numbers against Salesforce records, but the phone numbers in the call logs are test numbers that do not exist in the Salesforce org. 
Specifically, in `sfdc_push.py`:
- **Line 149-151**: It extracts the last 10 digits of the dialed number (`phone_last10`).
- **Line 153-155**: It calls `_query_account_by_phone(phone_last10)`. Because numbers like `+16022950104` or `+14802997325` are not in the SFDC Fortinet org, this returns `None`.
- **Line 155**: `skipped += 1` and `continue`. The script silently skips the record without creating a task.

## SF CLI Auth Status
**Working.** Running `sf data query` successfully returns Account records from the `fortinet` target org. The connection and permissions are fully functional.

## Availability of `sfdc_id`
The `sfdc_id` is **NOT available** in the call log entries (`logs/call_summaries.jsonl` or the archive). A review of the `raw` payload (including `SWMLCall` and `global_data` fields) in the 31 archived entries shows that `sfdc_id` is never passed through the pipeline. 
While `campaigns/accounts.db` correctly stores the `sfdc_id` (e.g., `0013400001XRl4yAAD` for County of Webster), this ID must be injected at call time.

## Code Fix: Pipeline Changes
To fix this permanently, `sfdc_id` needs to flow through the entire system:
1. **At Call Creation (`make_call_v8.py` / orchestrator)**: 
   When issuing the call via the SignalWire API, include the `sfdc_id` and `account_id` in the `global_data` block of the SWML payload:
   ```python
   "global_data": {
       "sfdc_id": account_record["sfdc_id"],
       "account_id": account_record["account_id"]
   }
   ```
2. **At Webhook Processing (`webhook_server.py`)**:
   Update lines ~87-95 where `log_entry` is built to extract `sfdc_id` from the raw data and save it top-level:
   ```python
   global_data = data.get("global_data", {})
   log_entry = {
       "timestamp": ...,
       "call_id": ...,
       "to": ...,
       "from": ...,
       "sfdc_id": global_data.get("sfdc_id"),
       "summary": ...,
       "raw": data
   }
   ```
3. **At Push Time (`sfdc_push.py`)**:
   Modify the account lookup (around line 153) to prioritize the stored `sfdc_id`:
   ```python
   sfdc_id = item.get("sfdc_id")
   if sfdc_id:
       account = {"Id": sfdc_id, "Name": "Unknown (from DB)"}
   else:
       account = _query_account_by_phone(phone_last10)
   ```

## Any Other Bugs
- **Empty Live Log**: The live `logs/call_summaries.jsonl` file currently has 0 lines, though the state file `sfdc-push-state.json` indicated a run on March 12th. The data was likely cleared or rotated without being successfully pushed to SFDC.
- **Empty `to` Fields**: Some of the earliest entries in the archive have empty `""` values for the `to` and `from` fields, which also causes immediate skipping on line 151.