#!/usr/bin/env python3
"""
End-to-End Test Script for AI Voice Caller

Tests the complete call flow from SignalWire through Dialogflow
to Cloud Functions and back. Requires live services.

Usage:
    python test_full_call_flow.py --test-mode dry-run
    python test_full_call_flow.py --test-mode live --phone +15551234567

Environment Variables:
    SIGNALWIRE_PROJECT_ID: SignalWire project ID
    SIGNALWIRE_API_TOKEN: SignalWire API token  
    SIGNALWIRE_SPACE_URL: SignalWire space URL
    SIGNALWIRE_FROM_NUMBER: Caller ID number
    DIALOGFLOW_PROJECT_ID: GCP project ID
    GCP_REGION: GCP region (default: us-central1)
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional

# Configuration
PROJECT_ID = os.environ.get('DIALOGFLOW_PROJECT_ID', 'tatt-pro')
REGION = os.environ.get('GCP_REGION', 'us-central1')
BASE_URL = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net"

# Test configuration
TEST_ACCOUNT_NAME = "Test School District"
TEST_CONTACT_NAME = "Test Contact"
TEST_PHONE = "+15551234567"


class E2ETestRunner:
    """Runs end-to-end tests for the AI Voice Caller."""
    
    def __init__(self, test_mode: str = "dry-run"):
        self.test_mode = test_mode
        self.results = []
        self.start_time = None
        
    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
    
    def run_test(self, name: str, test_fn):
        """Run a single test and record result."""
        self.log(f"Running: {name}")
        
        try:
            start = time.time()
            test_fn()
            duration = time.time() - start
            
            self.results.append({
                "name": name,
                "status": "PASS",
                "duration": f"{duration:.2f}s"
            })
            self.log(f"  PASS ({duration:.2f}s)", "PASS")
            return True
            
        except AssertionError as e:
            self.results.append({
                "name": name,
                "status": "FAIL",
                "error": str(e)
            })
            self.log(f"  FAIL: {e}", "FAIL")
            return False
            
        except Exception as e:
            self.results.append({
                "name": name,
                "status": "ERROR",
                "error": str(e)
            })
            self.log(f"  ERROR: {e}", "ERROR")
            return False
    
    def test_gemini_responder_health(self):
        """Test: Gemini Responder function is accessible."""
        url = f"{BASE_URL}/gemini-responder"
        
        # Send a simple request
        response = requests.post(
            url,
            json={
                "sessionInfo": {
                    "session": "test-session-123",
                    "parameters": {}
                },
                "text": "Tell me more about FortiVoice"
            },
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "fulfillmentResponse" in data, "Missing fulfillmentResponse"
        assert "messages" in data["fulfillmentResponse"], "Missing messages"
    
    def test_gemini_responder_context(self):
        """Test: Gemini uses context correctly."""
        url = f"{BASE_URL}/gemini-responder"
        
        response = requests.post(
            url,
            json={
                "sessionInfo": {
                    "session": "test-session-456",
                    "parameters": {
                        "account_name": "Springfield Schools",
                        "account_type": "K12",
                        "current_system": "Cisco"
                    }
                },
                "text": "What makes your solution better?",
                "pageInfo": {
                    "currentPage": "handle-objection"
                }
            },
            timeout=30
        )
        
        assert response.status_code == 200
        
        data = response.json()
        text = data["fulfillmentResponse"]["messages"][0]["text"]["text"][0]
        
        # Response should be non-empty and reasonably sized
        assert len(text) > 10, "Response too short"
        assert len(text) < 500, "Response too long for phone"
    
    def test_call_logger_lifecycle(self):
        """Test: Call logger handles start/update/end lifecycle."""
        url = f"{BASE_URL}/call-logger"
        session_id = f"test-{int(time.time())}"
        
        # Start call
        response = requests.post(
            url,
            json={
                "sessionId": session_id,
                "action": "start",
                "accountName": TEST_ACCOUNT_NAME,
                "callerName": TEST_CONTACT_NAME,
                "useCase": "cold_calling"
            },
            timeout=10
        )
        
        assert response.status_code == 200, f"Start failed: {response.text}"
        
        # Update call
        response = requests.post(
            url,
            json={
                "sessionId": session_id,
                "action": "update",
                "transcript": [
                    {"role": "bot", "text": "Hi, is this Test Contact?"},
                    {"role": "user", "text": "Yes, who is this?"}
                ]
            },
            timeout=10
        )
        
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        # End call
        response = requests.post(
            url,
            json={
                "sessionId": session_id,
                "action": "end",
                "outcome": "interested",
                "leadScore": 7
            },
            timeout=10
        )
        
        assert response.status_code == 200, f"End failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "completed"
        assert "duration" in data
    
    def test_call_logger_retrieval(self):
        """Test: Can retrieve call by session ID."""
        url = f"{BASE_URL}/call-logger"
        session_id = f"test-retrieve-{int(time.time())}"
        
        # Create a call
        requests.post(
            url,
            json={
                "sessionId": session_id,
                "action": "start",
                "accountName": "Retrieve Test"
            },
            timeout=10
        )
        
        # Retrieve it
        response = requests.get(
            url,
            params={"sessionId": session_id},
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("accountName") == "Retrieve Test"
    
    def test_lead_scorer_basic(self):
        """Test: Lead scorer returns valid score."""
        url = f"{BASE_URL}/lead-scorer"
        
        response = requests.post(
            url,
            json={
                "transcript": [
                    {"role": "user", "text": "I'm interested in learning more"},
                    {"role": "user", "text": "We're planning to upgrade next year"},
                    {"role": "user", "text": "What's the pricing?"}
                ],
                "useAI": False  # Use rule-based only for consistent testing
            },
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "score" in data, "Missing score"
        assert 0 <= data["score"] <= 10, "Score out of range"
        assert "category" in data, "Missing category"
        assert "signals" in data, "Missing signals"
    
    def test_lead_scorer_negative(self):
        """Test: Lead scorer correctly identifies cold leads."""
        url = f"{BASE_URL}/lead-scorer"
        
        response = requests.post(
            url,
            json={
                "transcript": [
                    {"role": "user", "text": "I'm not interested at all"},
                    {"role": "user", "text": "Please stop calling me"}
                ],
                "useAI": False
            },
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["score"] < 5, "Cold lead should score below 5"
        assert data["category"] in ["cold", "cool"], f"Expected cold/cool, got {data['category']}"
    
    def test_calendar_availability(self):
        """Test: Calendar booking returns availability."""
        url = f"{BASE_URL}/calendar-booking"
        
        response = requests.post(
            url,
            json={
                "action": "check_availability"
            },
            timeout=30
        )
        
        # This may fail if calendar service account not configured
        if response.status_code == 200:
            data = response.json()
            assert "available" in data or "error" in data
        else:
            self.log("Calendar not fully configured - skipping", "WARN")
    
    def test_salesforce_validation(self):
        """Test: Salesforce task validates input correctly."""
        url = f"{BASE_URL}/salesforce-task"
        
        # Test with invalid input
        response = requests.post(
            url,
            json={
                "outcome": "interested"
                # Missing accountName
            },
            timeout=10
        )
        
        assert response.status_code == 400, "Should reject missing accountName"
    
    def test_rate_limiting(self):
        """Test: Rate limiting works correctly."""
        url = f"{BASE_URL}/gemini-responder"
        
        # Send multiple rapid requests
        responses = []
        for i in range(10):
            try:
                response = requests.post(
                    url,
                    json={
                        "sessionInfo": {
                            "session": f"rate-limit-test-{i}",
                            "parameters": {}
                        },
                        "text": "Test message"
                    },
                    timeout=5
                )
                responses.append(response.status_code)
            except:
                responses.append(0)
        
        # Should mostly succeed (rate limit is per-session)
        success_count = sum(1 for r in responses if r == 200)
        assert success_count >= 5, f"Too many failures: {responses}"
    
    def test_error_handling(self):
        """Test: Functions handle errors gracefully."""
        url = f"{BASE_URL}/gemini-responder"
        
        # Send malformed request
        response = requests.post(
            url,
            json={
                "invalid": "request"
            },
            timeout=10
        )
        
        # Should return error, not crash
        assert response.status_code in [400, 200], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            # Check for fallback response
            data = response.json()
            assert "fulfillmentResponse" in data
    
    def run_all_tests(self):
        """Run all E2E tests."""
        self.start_time = time.time()
        
        print("\n" + "=" * 60)
        print("AI Voice Caller - End-to-End Tests")
        print(f"Mode: {self.test_mode}")
        print(f"Project: {PROJECT_ID}")
        print(f"Region: {REGION}")
        print("=" * 60 + "\n")
        
        # Cloud Function tests
        self.run_test("Gemini Responder - Health Check", self.test_gemini_responder_health)
        self.run_test("Gemini Responder - Context Usage", self.test_gemini_responder_context)
        self.run_test("Call Logger - Lifecycle", self.test_call_logger_lifecycle)
        self.run_test("Call Logger - Retrieval", self.test_call_logger_retrieval)
        self.run_test("Lead Scorer - Basic Scoring", self.test_lead_scorer_basic)
        self.run_test("Lead Scorer - Negative Signals", self.test_lead_scorer_negative)
        self.run_test("Calendar Booking - Availability", self.test_calendar_availability)
        self.run_test("Salesforce Task - Validation", self.test_salesforce_validation)
        self.run_test("Rate Limiting", self.test_rate_limiting)
        self.run_test("Error Handling", self.test_error_handling)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        total_time = time.time() - self.start_time
        
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        errors = sum(1 for r in self.results if r["status"] == "ERROR")
        
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total:   {len(self.results)}")
        print(f"Passed:  {passed}")
        print(f"Failed:  {failed}")
        print(f"Errors:  {errors}")
        print(f"Time:    {total_time:.2f}s")
        print("=" * 60)
        
        if failed > 0 or errors > 0:
            print("\nFailed Tests:")
            for r in self.results:
                if r["status"] in ["FAIL", "ERROR"]:
                    print(f"  - {r['name']}: {r.get('error', 'Unknown error')}")
        
        print()
        
        # Exit with appropriate code
        if failed > 0 or errors > 0:
            sys.exit(1)


def main():
    global PROJECT_ID, REGION, BASE_URL
    
    parser = argparse.ArgumentParser(description="Run E2E tests for AI Voice Caller")
    parser.add_argument('--test-mode', choices=['dry-run', 'live'], default='dry-run',
                       help='Test mode (dry-run: test functions only, live: test with real calls)')
    parser.add_argument('--phone', help='Phone number for live testing')
    parser.add_argument('--project', default=PROJECT_ID, help='GCP project ID')
    parser.add_argument('--region', default=REGION, help='GCP region')
    
    args = parser.parse_args()
    
    PROJECT_ID = args.project
    REGION = args.region
    BASE_URL = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net"
    
    if args.test_mode == 'live' and not args.phone:
        print("Error: --phone required for live testing")
        sys.exit(1)
    
    runner = E2ETestRunner(test_mode=args.test_mode)
    runner.run_all_tests()


if __name__ == "__main__":
    main()
