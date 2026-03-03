#!/usr/bin/env python3
"""
Stress Testing v2 - WITH CRITICAL BUG FIX
Tests agent with correct flow specification
"""

import os
import sys
import time
import concurrent.futures
from datetime import datetime
from google.cloud import dialogflowcx_v3 as dialogflow
from google.api_core.client_options import ClientOptions

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
AGENT_NAME_FILE = "../config/agent-name.txt"
FLOW_NAME_FILE = "../config/test-flow-name.txt"
API_ENDPOINT = f"{LOCATION}-dialogflow.googleapis.com"

def load_agent_name():
    with open(AGENT_NAME_FILE, 'r') as f:
        return f.read().strip()

def load_flow_name():
    with open(FLOW_NAME_FILE, 'r') as f:
        return f.read().strip()

def get_client_options():
    return ClientOptions(api_endpoint=API_ENDPOINT)

def make_query(session_path, text, flow_name):
    """Make a query with correct flow specification"""
    client = dialogflow.SessionsClient(client_options=get_client_options())
    
    text_input = dialogflow.TextInput(text=text)
    query_input = dialogflow.QueryInput(
        text=text_input,
        language_code="en"
    )
    
    # CRITICAL FIX: Specify the flow
    query_params = dialogflow.QueryParameters(
        current_page=f"{flow_name}/pages/START_PAGE"
    )
    
    request = dialogflow.DetectIntentRequest(
        session=session_path,
        query_input=query_input,
        query_params=query_params
    )
    
    return client.detect_intent(request=request)

def stress_test_concurrent_sessions(num_sessions=10):
    """Stress Test 1: Concurrent Sessions"""
    print("\n" + "="*60)
    print(f"STRESS TEST 1: {num_sessions} Concurrent Sessions")
    print("="*60)
    
    agent_name = load_agent_name()
    flow_name = load_flow_name()
    
    def make_concurrent_query(session_id):
        try:
            session_path = f"{agent_name}/sessions/{session_id}"
            start_time = time.time()
            response = make_query(session_path, "Hello", flow_name)
            latency = (time.time() - start_time) * 1000
            
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
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_sessions) as executor:
        session_ids = [f"stress-concurrent-{i}" for i in range(num_sessions)]
        futures = [executor.submit(make_concurrent_query, sid) for sid in session_ids]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"\n✓ Completed: {len(successful)}/{num_sessions} sessions")
    print(f"✗ Failed: {len(failed)}/{num_sessions} sessions")
    
    if successful:
        latencies = [r['latency_ms'] for r in successful]
        print(f"\nLatency: Avg {sum(latencies)/len(latencies):.1f}ms | Min {min(latencies):.1f}ms | Max {max(latencies):.1f}ms")
    
    return len(successful) == num_sessions

def stress_test_rapid_fire(num_queries=50):
    """Stress Test 2: Rapid-Fire Queries"""
    print("\n" + "="*60)
    print(f"STRESS TEST 2: {num_queries} Rapid-Fire Queries")
    print("="*60)
    
    agent_name = load_agent_name()
    flow_name = load_flow_name()
    session_path = f"{agent_name}/sessions/rapid-fire"
    
    queries = ["Hello", "Yes", "No", "Help", "Goodbye"] * (num_queries // 5)
    
    start_time = time.time()
    successful = 0
    failed = 0
    
    for text in queries:
        try:
            make_query(session_path, text, flow_name)
            successful += 1
        except:
            failed += 1
    
    total_time = time.time() - start_time
    
    print(f"\n✓ Completed: {successful}/{num_queries} queries")
    print(f"  Time: {total_time:.1f}s | Rate: {num_queries/total_time:.1f} queries/sec")
    
    return failed == 0

def stress_test_long_conversation(num_turns=100):
    """Stress Test 3: Long Conversation"""
    print("\n" + "="*60)
    print(f"STRESS TEST 3: {num_turns}-Turn Conversation")
    print("="*60)
    
    agent_name = load_agent_name()
    flow_name = load_flow_name()
    session_path = f"{agent_name}/sessions/long-conversation"
    
    conversation = ["Hello", "Can you hear me?", "Yes", "Great", "Thank you", "Goodbye"]
    turns = (conversation * (num_turns // len(conversation) + 1))[:num_turns]
    
    successful = 0
    failed = 0
    
    for i, text in enumerate(turns):
        try:
            make_query(session_path, text, flow_name)
            successful += 1
            if i % 20 == 0:
                print(f"  Turn {i+1}/{num_turns}...", end='\r')
        except:
            failed += 1
    
    print(f"\n✓ Completed: {successful}/{num_turns} turns")
    return failed == 0

def run_all_stress_tests():
    """Run all stress tests"""
    print("\n" + "="*70)
    print(" AI VOICE CALLER - STRESS TEST SUITE V2 (FIXED)")
    print("="*70)
    print(f" Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    results = {}
    results['concurrent_sessions'] = stress_test_concurrent_sessions(10)
    results['rapid_fire'] = stress_test_rapid_fire(50)
    results['long_conversation'] = stress_test_long_conversation(100)
    
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
    
    return results

if __name__ == "__main__":
    results = run_all_stress_tests()
    exit(0 if all(results.values()) else 1)
