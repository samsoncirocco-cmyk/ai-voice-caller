#!/usr/bin/env python3
"""
Comprehensive Dialogflow CX Agent Testing - FIXED VERSION
All bugs from initial run resolved
"""

import os
import json
from google.cloud import dialogflowcx_v3 as dialogflow
from google.api_core.client_options import ClientOptions

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
AGENT_NAME_FILE = "config/agent-name.txt"
API_ENDPOINT = f"{LOCATION}-dialogflow.googleapis.com"

def load_agent_name():
    with open(AGENT_NAME_FILE, 'r') as f:
        return f.read().strip()

def get_client_options():
    return ClientOptions(api_endpoint=API_ENDPOINT)

def test_agent_exists():
    """Test 1: Verify agent exists and is accessible"""
    print("\n" + "="*60)
    print("TEST 1: Agent Existence & Configuration")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        print(f"✓ Agent name loaded")
        print(f"✓ Using endpoint: {API_ENDPOINT}")
        
        client = dialogflow.AgentsClient(client_options=get_client_options())
        agent = client.get_agent(name=agent_name)
        
        print(f"✓ Agent accessible via API")
        print(f"  Display Name: {agent.display_name}")
        print(f"  Default Language: {agent.default_language_code}")
        print(f"  Time Zone: {agent.time_zone}")
        
        # Check TTS configuration
        if agent.text_to_speech_settings:
            print(f"  ✓ TTS configured")
        else:
            print(f"  ⚠ TTS using defaults")
        
        return True, agent
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False, None

def test_flows_exist():
    """Test 2: Verify flows are created"""
    print("\n" + "="*60)
    print("TEST 2: Flow Existence")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        client = dialogflow.FlowsClient(client_options=get_client_options())
        
        request = dialogflow.ListFlowsRequest(parent=agent_name)
        flows = client.list_flows(request=request)
        
        flow_list = list(flows)
        print(f"✓ Found {len(flow_list)} flows")
        
        for flow in flow_list:
            print(f"  - {flow.display_name}")
        
        # Check for test-call flow
        test_flow = None
        for flow in flow_list:
            if flow.display_name == "test-call":
                test_flow = flow
                break
        
        if test_flow:
            print(f"✓ Test flow 'test-call' exists")
            return True, test_flow
        else:
            print(f"✗ Test flow not found")
            return False, None
            
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False, None

def test_pages_structure():
    """Test 3: Verify page structure in test flow"""
    print("\n" + "="*60)
    print("TEST 3: Page Structure")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        
        # Get test-call flow
        flows_client = dialogflow.FlowsClient(client_options=get_client_options())
        request = dialogflow.ListFlowsRequest(parent=agent_name)
        flows = list(flows_client.list_flows(request=request))
        
        test_flow = None
        for flow in flows:
            if flow.display_name == "test-call":
                test_flow = flow
                break
        
        if not test_flow:
            print("✗ test-call flow not found")
            return False, None
        
        # List pages
        pages_client = dialogflow.PagesClient(client_options=get_client_options())
        request = dialogflow.ListPagesRequest(parent=test_flow.name)
        pages = list(pages_client.list_pages(request=request))
        
        print(f"✓ Found {len(pages)} pages in test-call flow")
        
        # FIXED: Use correct lowercase names
        expected_pages = ["greeting", "confirmation", "end-call"]
        found_pages = [p.display_name for p in pages]
        
        for expected in expected_pages:
            if expected in found_pages:
                print(f"  ✓ '{expected}' page exists")
            else:
                print(f"  ✗ '{expected}' page MISSING")
        
        all_found = all(p in found_pages for p in expected_pages)
        return all_found, pages
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False, None

def test_start_page_entry():
    """Test 4: Verify start page has entry fulfillment"""
    print("\n" + "="*60)
    print("TEST 4: Start Page Entry Fulfillment")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        
        # Get test-call flow
        flows_client = dialogflow.FlowsClient(client_options=get_client_options())
        request = dialogflow.ListFlowsRequest(parent=agent_name)
        flows = list(flows_client.list_flows(request=request))
        
        test_flow = None
        for flow in flows:
            if flow.display_name == "test-call":
                test_flow = flow
                break
        
        # Check if flow has entry fulfillment (start page message)
        if hasattr(test_flow, 'entry_fulfillment') and test_flow.entry_fulfillment:
            print(f"✓ Entry fulfillment configured on flow")
            return True, test_flow.entry_fulfillment
        
        # Otherwise check the START_PAGE
        pages_client = dialogflow.PagesClient(client_options=get_client_options())
        request = dialogflow.ListPagesRequest(parent=test_flow.name)
        pages = list(pages_client.list_pages(request=request))
        
        start_page = None
        for page in pages:
            if page.display_name == "START_PAGE" or page.display_name == "greeting":
                start_page = page
                break
        
        if start_page and start_page.entry_fulfillment:
            print(f"✓ Start page has entry fulfillment")
            return True, start_page.entry_fulfillment
        else:
            print(f"⚠ No entry fulfillment found")
            return False, None
            
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False, None

def test_session_creation():
    """Test 5: Test session creation and text query"""
    print("\n" + "="*60)
    print("TEST 5: Session Creation & Query (test-call flow)")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        
        # Get test-call flow ID
        flows_client = dialogflow.FlowsClient(client_options=get_client_options())
        request = dialogflow.ListFlowsRequest(parent=agent_name)
        flows = list(flows_client.list_flows(request=request))
        
        test_flow = None
        for flow in flows:
            if flow.display_name == "test-call":
                test_flow = flow
                break
        
        if not test_flow:
            print("✗ test-call flow not found")
            return False, None
        
        # Create session using test-call flow
        session_id = "test-session-12345"
        session_path = f"{agent_name}/sessions/{session_id}"
        
        print(f"✓ Session path: {session_path}")
        print(f"✓ Flow: {test_flow.name}")
        
        # Send text query with flow specified
        client = dialogflow.SessionsClient(client_options=get_client_options())
        
        text_input = dialogflow.TextInput(text="Hello")
        query_input = dialogflow.QueryInput(
            text=text_input,
            language_code="en"
        )
        
        # Specify the flow in the query parameters
        query_params = dialogflow.QueryParameters(
            current_page=f"{test_flow.name}/pages/START_PAGE"
        )
        
        request = dialogflow.DetectIntentRequest(
            session=session_path,
            query_input=query_input,
            query_params=query_params
        )
        
        response = client.detect_intent(request=request)
        
        print(f"✓ Query successful")
        
        if response.query_result.response_messages:
            msg = response.query_result.response_messages[0]
            if hasattr(msg, 'text') and msg.text.text:
                print(f"  Response: {msg.text.text[0]}")
        
        print(f"  Current Page: {response.query_result.current_page.display_name}")
        
        return True, response
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def test_edge_cases():
    """Test 6: Edge cases and error handling"""
    print("\n" + "="*60)
    print("TEST 6: Edge Cases & Error Handling")
    print("="*60)
    
    try:
        agent_name = load_agent_name()
        client = dialogflow.SessionsClient(client_options=get_client_options())
        
        test_cases = [
            ("", "Empty input"),
            ("a" * 1000, "Very long input"),
            ("!@#$%^&*()", "Special characters"),
            ("こんにちは", "Non-English (Japanese)"),
        ]
        
        passed = 0
        for text, description in test_cases:
            try:
                session_path = f"{agent_name}/sessions/edge-test-{hash(text)}"
                
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
                print(f"  ✓ {description}: Handled gracefully")
                passed += 1
                
            except Exception as e:
                print(f"  ✗ {description}: {type(e).__name__}")
        
        print(f"\n✓ Edge case handling: {passed}/{len(test_cases)} passed")
        return passed == len(test_cases), None
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False, None

def run_all_tests():
    """Run all tests and report results"""
    print("\n" + "="*60)
    print("DIALOGFLOW CX AGENT - COMPREHENSIVE TEST SUITE v2")
    print("="*60)
    
    results = {}
    
    results['agent_exists'] = test_agent_exists()[0]
    results['flows_exist'] = test_flows_exist()[0]
    results['pages_structure'] = test_pages_structure()[0]
    results['start_page_entry'] = test_start_page_entry()[0]
    results['session_creation'] = test_session_creation()[0]
    results['edge_cases'] = test_edge_cases()[0]
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test}")
    
    print(f"\nResults: {passed}/{total} tests passed ({int(passed/total*100)}%)")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Agent ready for production!")
    elif passed >= total * 0.8:
        print(f"\n✓ Most tests passed - minor issues to fix")
    else:
        print(f"\n⚠ Significant issues found - review failures")
    
    return results

if __name__ == "__main__":
    results = run_all_tests()
    exit(0 if all(results.values()) else 1)
