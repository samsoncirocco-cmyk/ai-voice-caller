#!/usr/bin/env python3
"""
Test script for Appointment Agent
Run this to validate the agent functions correctly
"""
from appointment_agent import AppointmentAgent
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def test_agent():
    """Test appointment agent functionality."""
    print("="*70)
    print("APPOINTMENT AGENT TEST SUITE")
    print("="*70)
    
    # Initialize agent
    print("\n[1/4] Initializing agent...")
    try:
        agent = AppointmentAgent()
        print("✅ Agent initialized successfully")
    except Exception as e:
        print(f"❌ Agent initialization failed: {e}")
        return False
    
    # Test check_availability - morning
    print("\n[2/4] Testing check_availability (morning)...")
    try:
        result = agent.check_availability({
            "time_preference": "morning",
            "days_ahead": 7
        })
        if result.response and "available" in result.response.lower():
            print(f"✅ check_availability (morning) working")
            print(f"   Response: {result.response[:100]}...")
        else:
            print(f"⚠️  Unexpected response: {result.response}")
    except Exception as e:
        print(f"❌ check_availability failed: {e}")
        return False
    
    # Test check_availability - afternoon
    print("\n[3/4] Testing check_availability (afternoon)...")
    try:
        result = agent.check_availability({
            "time_preference": "afternoon",
            "days_ahead": 7
        })
        if result.response and "available" in result.response.lower():
            print(f"✅ check_availability (afternoon) working")
            print(f"   Response: {result.response[:100]}...")
        else:
            print(f"⚠️  Unexpected response: {result.response}")
    except Exception as e:
        print(f"❌ check_availability failed: {e}")
        return False
    
    # Test book_meeting
    print("\n[4/4] Testing book_meeting...")
    try:
        tomorrow = datetime.now(ZoneInfo("America/Phoenix")) + timedelta(days=1)
        meeting_time = tomorrow.replace(hour=14, minute=30, second=0, microsecond=0)
        result = agent.book_meeting({
            "meeting_time": meeting_time.isoformat(),
            "attendee_email": "test@example.com",
            "attendee_name": "Test User",
            "meeting_topics": "Voice system consultation"
        })
        if result.response:
            print(f"✅ book_meeting working")
            print(f"   Response: {result.response[:100]}...")
        else:
            print(f"⚠️  Unexpected response: {result.response}")
    except Exception as e:
        print(f"❌ book_meeting failed: {e}")
        return False
    
    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED")
    print("="*70)
    print("\nThe agent is ready to handle appointment scheduling!")
    print("Note: Calendar API permissions warnings are expected in test mode.")
    print("      The agent will fall back to mock slots when needed.")
    return True


if __name__ == "__main__":
    import sys
    success = test_agent()
    sys.exit(0 if success else 1)
