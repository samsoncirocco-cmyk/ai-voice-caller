# Config & Numbers Audit Report
**Agent 3 — Config & Numbers Auditor**  
**Date:** 2026-03-13  
**Audited by:** audit-agent-3-config

---

## 1. Phone Numbers — Full Inventory

> Note: Task specified 7 numbers; SignalWire API returned **5 active numbers**. No additional numbers found. Config `local_numbers` entries match API records (SIDs verified).

| # | Label / Friendly Name | Number | State / Purpose | In STATE_FROM_NUMBERS? | In DEFAULT_FROM_NUMBER? | Voice URL Set? | Recommendation |
|---|---|---|---|---|---|---|---|
| 1 | SD-605 | +16053035984 | South Dakota — K-12 + municipal local presence | ✅ YES (`SD`) | No | No (inbound unrouted) | **KEEP** — active territory |
| 2 | NE-402 | +14022755273 | Nebraska — K-12 + municipal local presence | ✅ YES (`NE`) | No | No (inbound unrouted) | **KEEP** — active territory |
| 3 | IA-515 | +15152987809 | Iowa — K-12 + municipal local presence | ✅ YES (`IA`) | No | No (inbound unrouted) | **KEEP** — active territory |
| 4 | `+1 (480) 602-4668` | +14806024668 | Primary outbound / cold outreach (AZ 480) | No — outbound only | Used as `config["phone_number"]` (CSV mode default) | ✅ `dialogflowwebhook-xeq7wg2zxq-uc.a.run.app` | **KEEP** — primary outbound + wired to Dialogflow |
| 5 | *(no friendly name)* | +16028985026 | Fallback / K-12+Gov outbound (AZ 602); original number | No | ✅ `DEFAULT_FROM_NUMBER` in SmartRouter | ✅ `dialogflowwebhook-xeq7wg2zxq-uc.a.run.app` | **KEEP** — fallback routing + inbound webhook live |

### Key Observations
- **3 local-presence numbers** (SD/NE/IA) are correctly wired into `STATE_FROM_NUMBERS` in `campaign_runner_v2.py` and will be used as outbound caller IDs when calling those states.
- **Both AZ numbers** (+480, +602) are active with a Dialogflow voice webhook on inbound — this webhook (`dialogflowwebhook-xeq7wg2zxq-uc.a.run.app`) is a legacy Cloud Run endpoint and its current status is unverified. Inbound routing for all 5 numbers is otherwise unset (no SWML or SWML app assigned for the 3 local-presence numbers).
- **No number gap** — all 5 numbers in config match the API response exactly.

---

## 2. SmartRouter Status

### File Location
- ✅ `execution/smart_router.py` — **EXISTS and is substantial** (678+ lines)
- ❌ `smart_router.py` (root) — **DOES NOT EXIST** — this is a non-issue; `campaign_runner_v2.py` adds `execution/` to `sys.path` before importing, so the import succeeds.

### What It Does
`SmartRouter` is a full intelligent routing engine that:
1. **Time-of-day gate** — Schools only callable 8–10am or 1–3pm; Government 9–11am; nobody called 12–1pm (lunch block).
2. **State load-balancer** — If ≥3 calls in-flight for a state, prefers other states.
3. **Vertical matcher** — Maps account type/name → `prompt_file` + `voice` (persona-aware).
4. **Performance tuner** — Reads `campaigns/performance_stats.json` and, when enough data exists, selects the highest-answer-rate prompt variant per vertical.
5. **AccountDB integration** — Uses `execution/account_db.py` + `campaigns/accounts.db` to track call state, outcomes, and retry eligibility.

### How campaign_runner_v2.py Handles SmartRouter=None
```python
try:
    from smart_router import SmartRouter
except ImportError:
    SmartRouter = None  # Fallback: use legacy CSV mode
```
- If `SmartRouter is None` AND `--db` mode is used → **hard exit** (`sys.exit(1)`) with message: `"Error: SmartRouter not available. Install execution/smart_router.py"`
- If `SmartRouter is None` but `csv_file` mode is used → **graceful fallback** — campaign runs normally using legacy CSV routing (no SmartRouter needed).
- **Current status:** SmartRouter IS importable (file exists in `execution/`), so `--db` mode should work correctly. The `None` fallback is defensive coding; it does not represent a live gap.

### What Still Needs To Be Built (if anything)
SmartRouter appears complete. Potential gaps:
- `campaigns/performance_stats.json` may not exist yet → performance tuning falls back to static routing (graceful).
- `campaigns/accounts.db` must be populated via `sfdc_pull.py` / `build_campaign_from_salesforce.py` before SmartRouter can do anything.
- Inbound webhook for local-presence numbers (SD/NE/IA) — if a prospect calls back on a local number, there is no inbound routing set up.

---

## 3. Prompt Inventory

| File | Agent Name | Vertical / Target | Wired in VERTICAL_PROMPTS? | Notes |
|---|---|---|---|---|
| `paul.txt` | Paul | Municipal government, counties, sheriff depts, tribal, utilities | ✅ `"government": "prompts/paul.txt"` | Also used as `DEFAULT_PROMPT` in CSV mode. Authority/compliance angle. No E-Rate. |
| `k12.txt` | Paul | K-12 school districts — E-Rate, CIPA compliance, district IT | ✅ `"k12": "prompts/k12.txt"` | E-Rate-focused variant of Paul. Fully wired. |
| `cold_outreach.txt` | Alex | Unknown/cold/other verticals + higher_ed | ✅ `"higher_ed": "prompts/cold_outreach.txt"` + `"other": "prompts/cold_outreach.txt"` | Fast qualification, no assumed relationship. Fully wired. |
| `jackson.txt` | Jackson | Cold outreach — same structure as cold_outreach.txt/Alex, different persona | ❌ **NOT in VERTICAL_PROMPTS — ORPHANED** | Structurally identical to cold_outreach.txt but persona name is "Jackson". No routing path triggers it. |
| `mary.txt` | Mary | Municipal government — same structure as paul.txt, different persona | ❌ **NOT in VERTICAL_PROMPTS — ORPHANED** | Structurally identical to paul.txt but persona name is "Mary". No routing path triggers it. |

### Orphaned Prompts: jackson.txt and mary.txt
Neither file is referenced anywhere in `campaign_runner_v2.py`, SmartRouter, or any execution script found during this audit. They appear to be **A/B test persona variants** — Jackson as a second male cold-outreach voice and Mary as a female government persona — built but never wired into the routing layer.

**Recommendations:**
- **mary.txt** → Wire into `VERTICAL_PROMPTS` as a rotatable government variant alongside `paul.txt` (e.g., SmartRouter can A/B between them by gender to test answer rates).
- **jackson.txt** → Wire as a rotatable cold/other variant alongside `cold_outreach.txt` (Alex).
- Both already have complete, production-quality scripts. The only work needed is adding them to SmartRouter's `PROMPT_VARIANTS` table and `VERTICAL_PROMPTS` dict, then tagging calls by which variant was used so performance tuning can differentiate.

---

## 4. Fabric AI Agent Status

**API Response:** ✅ Fabric API is **live and responding** — returned 12 resources.

| Resource Type | Count | Notes |
|---|---|---|
| `ai_agent` | 6 | Multiple agents, including legacy ones |
| `cxml_webhook` | 3 | Legacy Dialogflow/webhook bridges |
| `swml_script` | 1 | SWML script resource |
| `cxml_script` | 1 | LaML/CXML script |
| `call_flow` | 1 | Call flow resource |

### Primary Agent (Cold Caller)
- **Resource ID:** `52f7afac-2f34-4f2c-8fb9-0e92149b4e43` ✅ Confirmed live
- **Display Name:** `Fortinet SLED Cold Caller v1`
- **Agent ID:** `a774d2ee-dac8-4eb2-9832-845536168e52`
- **Type:** `ai_agent`
- **Created:** 2026-02-11 | **Last Updated:** 2026-02-11
- **Model:** `gpt-4.1-nano`
- **Status:** ✅ EXISTS and queryable on Fabric API

**Important Note:** The Fabric agent's stored prompt is the **v1 generic Paul prompt** (from initial setup, Feb 2026). In practice, `campaign_runner_v2.py` builds inline SWML at call time with dynamic prompts from `prompts/` — so the Fabric agent's internal prompt is a fallback/legacy artifact. The production path uses Calling API + inline SWML, not the Fabric `/execute` endpoint (per known issue in config notes: `/execute` URLs return 404 externally).

### Other 5 AI Agents
These have no `display_name` in the API list endpoint (names appear in detail endpoint only). IDs: `18cb1539`, `067f48d2`, `f5050766`, `5e2c7990`, `58264ddd`. These are likely legacy/test agents and should be audited separately to confirm which can be deleted.

---

## 5. Action Items Summary

| Priority | Item | Owner |
|---|---|---|
| HIGH | Wire `mary.txt` into VERTICAL_PROMPTS + SmartRouter as government A/B variant | Dev |
| HIGH | Wire `jackson.txt` into VERTICAL_PROMPTS + SmartRouter as cold/other A/B variant | Dev |
| MEDIUM | Set inbound voice webhook on SD/NE/IA local-presence numbers (so callback calls are handled) | Config |
| MEDIUM | Audit 5 unnamed ai_agents in Fabric — delete stale/legacy ones | Config |
| LOW | Verify legacy Dialogflow webhook on +14806024668 and +16028985026 is still live or replace with SWML | Dev |
| LOW | Add `mary.txt` and `jackson.txt` to `VERTICAL_PROMPTS` dict in campaign_runner_v2.py header comment | Dev |

---

*Generated by audit-agent-3-config | 2026-03-13*
