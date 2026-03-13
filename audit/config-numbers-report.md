# Config & Numbers Audit Report
**Agent:** Config & Numbers Auditor (Agent 3)  
**Date:** 2026-03-13  
**Project:** /home/samson/.openclaw/workspace/projects/ai-voice-caller/

---

## TL;DR

- **5 numbers in account, not 7.** The two numbers called out in the task (+14808227861 "Matt Test Fresh" and +14806025848) **do not exist** in this SignalWire account — never purchased or already released.
- **smart_router.py is NOT empty** — it's a 700+ line fully implemented router living at `execution/smart_router.py`. The import at the project root *does work* because `execution/` is injected into sys.path before the import.
- **jackson.txt and mary.txt are orphaned** — complete, production-quality prompts that are not wired into any routing table.
- **DEFAULT_FROM_NUMBER is stale** — campaign_runner_v2.py uses `+16028985026` as the fallback, but config.json marks that as `phone_number_old`. The active main number is `+14806024668`.
- **Fabric AI agent is LIVE** — resource 52f7afac / "Fortinet SLED Cold Caller v1" responds correctly via API.

---

## 1. Full Phone Number Inventory

### Numbers Actually in the SignalWire Account (API-verified, 2026-03-13)

| # | Number | Friendly Name | Created | Voice URL | In STATE_FROM_NUMBERS? | In Config? |
|---|--------|---------------|---------|-----------|------------------------|------------|
| 1 | +15152987809 | IA-515 | 2026-03-06 | ❌ None | ✅ Iowa | ✅ local_numbers.IA_515 |
| 2 | +14022755273 | NE-402 | 2026-03-06 | ❌ None | ✅ Nebraska | ✅ local_numbers.NE_402 |
| 3 | +16053035984 | SD-605 | 2026-03-06 | ❌ None | ✅ South Dakota | ✅ local_numbers.SD_605 |
| 4 | +14806024668 | (unnamed) | 2026-02-12 | ⚠️ Dialogflow legacy | ❌ Not in state table | ✅ phone_number (current) |
| 5 | +16028985026 | (unnamed) | 2026-02-11 | ⚠️ Dialogflow legacy | ❌ Not in state table | ✅ phone_number_old |

**Total: 5 numbers. No "Matt Test Fresh" (+14808227861). No +14806025848.**

### The Two "Missing" Numbers

| Number | Status | Assessment |
|--------|--------|------------|
| +14808227861 ("Matt Test Fresh") | **NOT IN ACCOUNT** | Never purchased in this project, or released before this audit |
| +14806025848 | **NOT IN ACCOUNT** | Never purchased in this project, or released before this audit |

> **These numbers are not costing money.** They don't exist in the account. The task brief may have included numbers from a different project or test environment. No action needed.

---

## 2. Number-by-Number Usage Assessment

### +15152987809 — IA-515 (Iowa local presence)
- **Purpose:** Outbound caller ID for Iowa leads — local 515 area code increases answer rate
- **Wired outbound:** ✅ Yes — `STATE_FROM_NUMBERS["IA"]` in campaign_runner_v2.py
- **Inbound behavior:** No voice_url set — if someone calls back, it rings to dead air (no handler)
- **Earning its keep:** ✅ Yes — actively used for Iowa K-12 and municipal outreach
- **Monthly cost:** ~$1/month

### +14022755273 — NE-402 (Nebraska local presence)
- **Purpose:** Outbound caller ID for Nebraska leads — local 402 area code
- **Wired outbound:** ✅ Yes — `STATE_FROM_NUMBERS["NE"]`
- **Inbound behavior:** No voice_url — dead air on callbacks
- **Earning its keep:** ✅ Yes — actively used for Nebraska territory
- **Monthly cost:** ~$1/month

### +16053035984 — SD-605 (South Dakota local presence)
- **Purpose:** Outbound caller ID for South Dakota leads — local 605 area code
- **Wired outbound:** ✅ Yes — `STATE_FROM_NUMBERS["SD"]`
- **Inbound behavior:** No voice_url — dead air on callbacks
- **Earning its keep:** ✅ Yes — primary territory (most leads are SD)
- **Monthly cost:** ~$1/month

### +14806024668 — Main/Cold Outreach number (480 AZ)
- **Purpose:** Primary outbound for non-territory states + cold outreach vertical
- **Wired outbound:** ✅ Yes — `config.phone_number`, used as `FROM_NUMBER` in code, also `DEFAULT_FROM_NUMBER` for the `other` and `higher_ed` verticals
- **Wired inbound:** ⚠️ `voice_url` = `https://dialogflowwebhook-xeq7wg2zxq-uc.a.run.app` — legacy Dialogflow webhook; if someone calls back, they hit an old bot
- **Earning its keep:** ✅ Yes
- **Config note:** This is the ACTIVE current number. Should be `DEFAULT_FROM_NUMBER` in campaign_runner_v2.py

### +16028985026 — Old main number (602 AZ)
- **Purpose:** Originally the primary number; now marked `phone_number_old` in config
- **Wired outbound:** ⚠️ **YES — still hardcoded as `DEFAULT_FROM_NUMBER` in campaign_runner_v2.py** despite being the "old" number
- **Wired inbound:** ⚠️ Same Dialogflow legacy webhook as above
- **Earning its keep:** ⚠️ MAYBE — it's still used as the state-routing fallback, but unintentionally. Config says it's old but the code still prefers it.
- **Config mismatch:** `config.json` has `phone_number_old: "+16028985026"` but campaign_runner_v2.py uses `DEFAULT_FROM_NUMBER = "+16028985026"`. Should be `+14806024668`.

---

## 3. Routing Configuration Gaps

### Gap 1: DEFAULT_FROM_NUMBER Points to the Wrong Number

**File:** `campaign_runner_v2.py` line ~67

```python
DEFAULT_FROM_NUMBER = "+16028985026"  # ← This is phone_number_OLD in config!
```

The current active number is `+14806024668`. Any call to a non-SD/NE/IA state uses the stale 602 number as the outbound caller ID. This may cause confusion if the number is ever released.

**Fix:**
```python
DEFAULT_FROM_NUMBER = "+14806024668"  # Active main number
```

### Gap 2: Local Presence Numbers Have No Inbound Handler

All three local presence numbers (IA/NE/SD) have `voice_url: null`. If a prospect calls back on those numbers, they get dead air. This is a missed opportunity.

**Recommendation:** Wire a simple "This is an outbound-only number, please call Samson at X" LaML response, or forward to Samson's mobile.

### Gap 3: +14806024668 and +16028985026 Have a Legacy Dialogflow Inbound Handler

Both numbers point to `https://dialogflowwebhook-xeq7wg2zxq-uc.a.run.app` for inbound voice. This is an old Dialogflow webhook that almost certainly no longer aligns with the current SWML/SWAIG architecture. If prospects call back, they hit a deprecated bot.

**Recommendation:** Replace with a proper callback handler or a simple SWML greeting that collects their info.

---

## 4. smart_router.py Status

### Location: `execution/smart_router.py` — FULLY IMPLEMENTED (700+ lines)

**NOT empty.** The confusion: there is no `smart_router.py` at the project root. The module lives at `execution/smart_router.py`.

### Does the Import Work?

**Yes.** In `campaign_runner_v2.py`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent / "execution"))

try:
    from smart_router import SmartRouter
except ImportError:
    SmartRouter = None  # Fallback: use legacy CSV mode
```

Since `execution/` is injected into `sys.path` before the try/except, `from smart_router import SmartRouter` successfully finds `execution/smart_router.py`. The fallback to `None` only triggers if the file is missing or has a syntax error.

### What SmartRouter Does

A sophisticated 4-layer routing engine:

1. **Time-of-day gate** — Schools: call 8–10am or 1–3pm. Gov: 9–11am. No calls 12–1pm.
2. **State load-balancer** — If ≥3 calls in-flight for one state, prefer other states
3. **Vertical matcher** — Picks prompt_file + voice from account type (k12, government, other)
4. **Performance tuner** — If `performance_stats.json` has A/B data, picks the variant with the best answer rate per vertical

### Fallback Behavior

If SmartRouter fails to import (None), the runner falls back to the `--csv` legacy mode. The `--db` mode explicitly requires SmartRouter and exits with an error if unavailable. Both paths work.

---

## 5. Prompt File Inventory

| File | Agent Name | Vertical Target | Wired in VERTICAL_PROMPTS? | Notes |
|------|-----------|-----------------|---------------------------|-------|
| `paul.txt` | Paul | Government/Municipal | ✅ `government` key | Primary gov prompt |
| `cold_outreach.txt` | Alex | Cold/Unknown/Higher Ed | ✅ `other` + `higher_ed` keys | Catch-all cold prompt |
| `k12.txt` | Paul | K-12 districts | ✅ `k12` key | E-Rate focused; best for K-12 |
| `jackson.txt` | Jackson | Cold/Unknown | ❌ **NOT WIRED** | A/B alt for cold_outreach.txt |
| `mary.txt` | Mary | Government/Municipal | ❌ **NOT WIRED** | A/B alt for paul.txt |

### jackson.txt and mary.txt Status

Both prompts are complete, production-quality scripts. They follow the exact same structure as their counterparts (`cold_outreach.txt` and `paul.txt`) but with different agent personas:

- **jackson.txt** = "Jackson" persona — same cold outreach structure as Alex/cold_outreach.txt
- **mary.txt** = "Mary" persona — same gov/municipal structure as Paul/paul.txt

**These are clearly built for A/B testing** (does "Mary" get more callbacks than "Paul"? Does "Jackson" outperform "Alex"?). They're complete but never deployed.

**To wire them for A/B testing**, SmartRouter's performance tuner can handle this — it already supports variant selection via `performance_stats.json`. The missing piece is adding them to the routing table.

---

## 6. Fabric AI Agent Verification

**Resource ID:** `52f7afac-2f34-4f2c-8fb9-0e92149b4e43`  
**API Status:** ✅ **LIVE** — responding correctly as of 2026-03-13

```json
{
  "id": "52f7afac-2f34-4f2c-8fb9-0e92149b4e43",
  "display_name": "Fortinet SLED Cold Caller v1",
  "type": "ai_agent",
  "created_at": "2026-02-11T18:26:47Z",
  "updated_at": "2026-02-11T18:26:47Z"
}
```

**Important caveat:** The Fabric agent's hardcoded prompt (`ai_agent.prompt.text`) is the **old v1 "Paul" prompt** — the voice system / E-Rate focused script written in February 2026. The current campaign runner does NOT use this prompt — it builds inline SWML with the current `prompts/*.txt` files via `build_dynamic_swml()`. The Fabric agent is effectively decorative at this point; actual prompts are injected dynamically.

---

## 7. Recommendations

### Priority 1 — Fix DEFAULT_FROM_NUMBER (10 min)
Change `DEFAULT_FROM_NUMBER = "+16028985026"` → `"+14806024668"` in campaign_runner_v2.py. The old number is still active but the config marks it as deprecated.

### Priority 2 — Wire jackson.txt + mary.txt for A/B Testing
Add two new entries to `VERTICAL_PROMPTS`:
```python
VERTICAL_PROMPTS = {
    "k12":        "prompts/k12.txt",
    "government": "prompts/paul.txt",        # or mary.txt — A/B test!
    "higher_ed":  "prompts/cold_outreach.txt",
    "other":      "prompts/cold_outreach.txt",  # or jackson.txt — A/B test!
    # A/B variants (use performance_stats.json to pick winner):
    "government_b": "prompts/mary.txt",
    "other_b":      "prompts/jackson.txt",
}
```
SmartRouter already has the performance tuner to pick winners — it just needs the prompt variants exposed. Alternatively, hard-split by state: use Paul/gov for SD, Mary/gov for NE/IA to get natural A/B data.

### Priority 3 — Fix Inbound Handler for Local Presence Numbers
Wire a minimal inbound SWML on IA/NE/SD numbers so callbacks don't hit dead air. A 30-second fix: "Hi, you've reached an outbound Fortinet line. For Samson Cirocco, please call [mobile] or email scirocco@fortinet.com."

### Priority 4 — Update or Remove Dialogflow Inbound Handler
Both 480 and 602 numbers point to a deprecated Dialogflow webhook for inbound voice. Replace with either the AI agent endpoint or a simple callback collection SWML.

### Priority 5 — Consider Releasing +16028985026 (Low Priority)
If DEFAULT_FROM_NUMBER is fixed to 480, the 602 number serves no outbound purpose. It adds ~$1/month in cost. However: it's the oldest number (Feb 2026), has SMS/MMS capabilities that the 480 doesn't, and is marked `phone_number_old` suggesting intentional archiving. **Recommend keeping for now** — its SMS capability could be useful for follow-up texts. Reassess in 60 days if no SMS use case materializes.

### Don't Do — Release Local Presence Numbers
IA/NE/SD numbers (+515/+402/+605) are actively used for local presence and directly tied to answer rate improvements. Keep all three.

---

## 8. Summary Table

| Item | Status | Action |
|------|--------|--------|
| +14808227861 (Matt Test Fresh) | Not in account | No action — doesn't exist |
| +14806025848 | Not in account | No action — doesn't exist |
| +15152987809 IA-515 | ✅ Active, properly wired | Wire inbound handler |
| +14022755273 NE-402 | ✅ Active, properly wired | Wire inbound handler |
| +16053035984 SD-605 | ✅ Active, properly wired | Wire inbound handler |
| +14806024668 Main (480) | ✅ Active, wired | Fix as DEFAULT_FROM_NUMBER |
| +16028985026 Old main (602) | ⚠️ Active but stale | Fix routing reference; keep for SMS |
| smart_router.py | ✅ Fully implemented (execution/) | No action |
| jackson.txt | ⚠️ Orphaned — not wired | Wire for A/B testing |
| mary.txt | ⚠️ Orphaned — not wired | Wire for A/B testing |
| Fabric AI agent (52f7afac) | ✅ Live | Note: uses old v1 prompt |
| Dialogflow inbound on 480/602 | ⚠️ Legacy, deprecated | Replace with SWML handler |
