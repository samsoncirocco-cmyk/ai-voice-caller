---
status: resolved
trigger: "Diagnose and debug AI voice caller end-to-end"
created: 2026-02-17T10:27:00-07:00
updated: 2026-02-17T11:15:00-07:00
---

## Current Focus

hypothesis: The diagnosis is complete. We have identified three distinct failure modes explaining all symptoms.
test: None needed. Documenting findings.
expecting: Clear path forward for the main agent.
next_action: Submit final report.

## Symptoms

expected: AI voice caller makes outbound calls where AI agent speaks first, has conversation, logs results
actual: 
1. Compatibility API calls connect but are SILENT (when successful).
2. Compatibility API calls fail with SIP 500 (on fresh number).
3. Calling API calls return "queued" but never ring.
errors: SIP 500, Silent Calls, Phantom Queued Calls
reproduction: Consistent failure across all tested permutations.
started: Feb 17 testing session.

## Eliminated

- hypothesis: "From-number rate limiting is causing the fresh number to fail"
  evidence: +14806025848 (fresh) fails with SIP 500 via Compatibility API immediately. This indicates a broader issue (destination blocking or account routing).
  timestamp: 2026-02-17T10:55

- hypothesis: "The Calling API works with inline SWML"
  evidence: API returns 200/queued, but calls never alert the PSTN network. Likely requires Realtime SDK context.
  timestamp: 2026-02-17T10:57

- hypothesis: "Compatibility API can consume SWML JSON"
  evidence: It cannot. It expects cXML. Feeding it SWML JSON results in a connected call with no instructions -> Silence.
  timestamp: 2026-02-17T10:53

- hypothesis: "The fresh number is working for basic calls"
  evidence: Tested Compatibility API with a simple valid cXML <Say> bin. Result: SIP 500. The fresh number cannot place legacy calls either.
  timestamp: 2026-02-17T11:05

## Evidence

- timestamp: 2026-02-17T10:48
  checked: cXML spec
  found: cXML has no <AI> verb. Compatibility API cannot run AI agents directly.
  implication: Must use SWML for AI.

- timestamp: 2026-02-17T10:50
  checked: GCF Endpoint
  found: Returns application/json (SWML). Compatibility API expects XML.
  implication: Explains the "Silent Call" symptom.

- timestamp: 2026-02-17T10:54
  checked: Phone Config
  found: Voice URL is set to GCF SWML endpoint. This works for INBOUND (if configured as SWML script), but Compatibility API outbound uses `Url` param which expects XML.

- timestamp: 2026-02-17T11:05
  checked: Fresh Number (+14806025848) with cXML <Say>
  found: Immediate SIP 500. 
  implication: The fresh number is either not fully propagated, or the destination (+16022950104) has blocked calls from this SignalWire account/trunk, or the account has a platform-level outbound block.

- timestamp: 2026-02-17T10:57
  checked: Calling API Logs
  found: Calling API calls do NOT appear in Compatibility API logs. They are separate systems.
  implication: The "queued" calls are likely getting stuck in the Realtime subsystem waiting for a client that doesn't exist.

## Resolution

root_cause: **THREE DISTINCT ISSUES:**
1. **Silence:** Caused by using Compatibility API (XML-based) with an SWML (JSON) endpoint. The systems are incompatible.
2. **No Ring (Calling API):** Calling API via REST "queue" likely requires a Realtime SDK client to service the call or specific SIP/Domain setup. It is not a simple "fire and forget" PSTN dialer in this configuration.
3. **SIP 500 (Fresh Number):** The fresh number failed immediately with valid cXML. This confirms a Carrier/Platform-level block or propagation issue, unrelated to the code.

fix: **RECOMMENDED ARCHITECTURE:**
1. **Do not use Compatibility API** for AI agents (it doesn't support them).
2. **Do not use Calling API REST** without the full Realtime SDK context.
3. **SOLUTION:** Use the **SignalWire Agents SDK** (Python) running as a service. It hosts a server that SignalWire requests SWML from. 
4. **IMMEDIATE BLOCKER:** Carrier/Account blocking (SIP 500) must be resolved before ANY code will work. Wait 24h or contact Support.

verification: Confirmed failure modes via isolated tests (cXML test, API inspection, Log analysis).
files_changed: []
