#!/usr/bin/env python3
"""
test_inbound_simulation.py — Simulate inbound calls on all 5 SignalWire numbers.

Tests:
  1. Live webhook endpoint responds with valid SWML
  2. SWML includes correct AI agent, transfer function, and post-prompt callback
  3. Inbound call logging works
  4. Caller context lookup works (known vs unknown callers)
  5. All 5 numbers handled correctly (correct state in prompt)

Usage:
  python3 tests/test_inbound_simulation.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Use localhost for simulation (Cloudflare WAF blocks unauthenticated external POSTs)
# SignalWire itself has a bypass token so real inbound calls work fine via tunnel
WEBHOOK_BASE = "http://localhost:18790"

# The 5 active SignalWire numbers (those actually registered in SW project)
ACTIVE_NUMBERS = {
    "+16053035984": "South Dakota",
    "+14022755273": "Nebraska",
    "+15152987809": "Iowa",
    "+16028985026": "Arizona",
    "+14806024668": "Arizona",
}

SIMULATED_CALLERS = [
    "+16055551001",  # SD prospect calling back
    "+14025551002",  # NE prospect calling back
    "+15155551003",  # IA prospect calling back
    "+16025551004",  # AZ prospect (unknown)
    "+14805551005",  # AZ prospect (unknown)
]

RESULTS = []


def post_json(url: str, payload: dict) -> tuple:
    """HTTP POST JSON, return (status_code, response_body)."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def validate_swml(swml: dict, to_number: str, expected_state: str) -> list:
    """Validate SWML structure. Returns list of errors (empty = pass)."""
    errors = []

    if swml.get("version") != "1.0.0":
        errors.append(f"Wrong SWML version: {swml.get('version')}")

    sections = swml.get("sections", {})
    main = sections.get("main", [])
    if not main:
        errors.append("No 'main' section in SWML")
        return errors

    # Should start with answer
    if main[0] != {"answer": {}}:
        errors.append(f"First step should be 'answer', got: {main[0]}")

    # Should have AI agent
    ai_step = next((s for s in main if "ai" in s), None)
    if not ai_step:
        errors.append("No AI agent in SWML")
        return errors

    ai = ai_step["ai"]

    # Check prompt mentions state
    prompt_text = ai.get("prompt", {}).get("text", "")
    if expected_state not in prompt_text:
        errors.append(f"Prompt missing state '{expected_state}': ...{prompt_text[:100]}...")

    # Check post-prompt callback
    ppu = ai.get("post_prompt_url", "")
    if "hooks.6eyes.dev/voice-caller/inbound-callback" not in ppu:
        errors.append(f"Missing post_prompt_url, got: {ppu}")

    # Check SWAIG functions
    functions = ai.get("SWAIG", {}).get("functions", [])
    func_names = [f["function"] for f in functions]
    if "transfer_to_samson" not in func_names:
        errors.append(f"Missing transfer_to_samson SWAIG function. Got: {func_names}")
    if "end_call" not in func_names:
        errors.append(f"Missing end_call SWAIG function. Got: {func_names}")

    # Check transfer function points to Samson's cell
    transfer_fn = next((f for f in functions if f["function"] == "transfer_to_samson"), None)
    if transfer_fn:
        expressions = transfer_fn.get("data_map", {}).get("expressions", [])
        if expressions:
            swml_action = expressions[0].get("output", {}).get("action", [{}])[0].get("SWML", {})
            connect = swml_action.get("sections", {}).get("main", [{}])[0].get("connect", {})
            if connect.get("to") != "+16022950104":
                errors.append(f"Transfer target wrong: {connect.get('to')} (expected +16022950104)")

    return errors


def run_simulation():
    print("=" * 70)
    print("INBOUND CALL SIMULATION — All 5 Active SignalWire Numbers")
    print("=" * 70)

    all_passed = True

    for i, (to_number, state) in enumerate(ACTIVE_NUMBERS.items()):
        from_number = SIMULATED_CALLERS[i]
        print(f"\n{'─' * 60}")
        print(f"Test {i+1}: Inbound call to {to_number} ({state})")
        print(f"         From simulated caller: {from_number}")

        payload = {
            "call": {
                "from": from_number,
                "to": to_number,
                "call_id": f"sim-test-{i+1:02d}",
                "direction": "inbound",
            }
        }

        url = f"{WEBHOOK_BASE}/voice-caller/inbound"
        status, body = post_json(url, payload)

        if status != 200:
            print(f"  ❌ FAIL: HTTP {status} — {body}")
            RESULTS.append({"number": to_number, "state": state, "passed": False, "error": f"HTTP {status}"})
            all_passed = False
            continue

        # Validate SWML structure
        errors = validate_swml(body, to_number, state)
        if errors:
            print(f"  ❌ FAIL: SWML validation errors:")
            for err in errors:
                print(f"       • {err}")
            RESULTS.append({"number": to_number, "state": state, "passed": False, "errors": errors})
            all_passed = False
        else:
            print(f"  ✅ PASS: Valid SWML returned (HTTP 200)")
            print(f"       • AI agent: {body['sections']['main'][1]['ai']['languages'][0]['voice']}")
            prompt_snippet = body['sections']['main'][1]['ai']['prompt']['text'][:80].replace('\n', ' ')
            print(f"       • Prompt: {prompt_snippet}...")
            print(f"       • SWAIG: transfer_to_samson + end_call")
            RESULTS.append({"number": to_number, "state": state, "passed": True})

        time.sleep(0.3)  # small delay between requests

    # Test the post-callback endpoint
    print(f"\n{'─' * 60}")
    print("Test 6: Inbound callback (post-prompt logging)")
    callback_payload = {
        "call_id": "sim-callback-001",
        "post_prompt_data": {
            "raw": "- Caller name: John Smith\n- Caller organization: Sioux Falls School\n- Reason for calling: Returning your call\n- Message left: Interested in Fortinet demo\n- Transfer requested: no\n- Callback requested: yes (tomorrow morning)"
        }
    }
    url = f"{WEBHOOK_BASE}/voice-caller/inbound-callback?from=+16055551001&to=+16053035984"
    status, body = post_json(url, callback_payload)
    if status == 200 and body.get("status") == "logged":
        print(f"  ✅ PASS: Callback logged (call_id={body.get('call_id')})")
        RESULTS.append({"test": "callback_logging", "passed": True})
    else:
        print(f"  ❌ FAIL: HTTP {status} — {body}")
        RESULTS.append({"test": "callback_logging", "passed": False})
        all_passed = False

    # Summary
    print(f"\n{'=' * 70}")
    passed = sum(1 for r in RESULTS if r.get("passed"))
    total = len(RESULTS)
    print(f"RESULTS: {passed}/{total} passed")
    if all_passed:
        print("✅ ALL TESTS PASSED — Inbound handlers are live and working for all 5 numbers")
    else:
        print("⚠️  SOME TESTS FAILED — See details above")
    print("=" * 70)

    return all_passed


# Also run local unit tests
def run_local_tests():
    print("\n" + "=" * 70)
    print("LOCAL UNIT TESTS — inbound_handler module")
    print("=" * 70)

    from execution.inbound_handler import build_inbound_swml, log_inbound_call, lookup_caller

    tests_passed = 0
    tests_total = 0

    # Test 1: SWML generation for each number
    for number, state in ACTIVE_NUMBERS.items():
        tests_total += 1
        swml = build_inbound_swml("+15555551234", number)
        errors = validate_swml(swml, number, state)
        if not errors:
            print(f"  ✅ build_inbound_swml({number}) — {state} OK")
            tests_passed += 1
        else:
            print(f"  ❌ build_inbound_swml({number}) — ERRORS: {errors}")

    # Test 2: Caller context lookup (unknown caller)
    tests_total += 1
    ctx = lookup_caller("+15555559999")
    if ctx is None:
        print(f"  ✅ lookup_caller(unknown) → None (correct)")
        tests_passed += 1
    else:
        print(f"  ❌ lookup_caller(unknown) → {ctx} (expected None)")

    # Test 3: Log inbound call
    tests_total += 1
    try:
        log_inbound_call("+15555551234", "+16053035984", {"test": True})
        log_path = ROOT / "logs" / "inbound_calls.jsonl"
        if log_path.exists():
            last_line = log_path.read_text().strip().split("\n")[-1]
            entry = json.loads(last_line)
            if entry.get("from") == "+15555551234":
                print(f"  ✅ log_inbound_call() — logged successfully")
                tests_passed += 1
            else:
                print(f"  ❌ log_inbound_call() — wrong entry: {entry}")
        else:
            print(f"  ❌ log_inbound_call() — log file not created")
    except Exception as e:
        print(f"  ❌ log_inbound_call() — exception: {e}")

    print(f"\nLocal tests: {tests_passed}/{tests_total} passed")
    return tests_passed == tests_total


if __name__ == "__main__":
    os.chdir(ROOT)
    local_ok = run_local_tests()
    live_ok = run_simulation()
    sys.exit(0 if (local_ok and live_ok) else 1)
