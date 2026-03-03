#!/usr/bin/env python3
"""
Test script for Follow-Up Agent
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.followup_agent import FollowUpAgent

def test_agent_creation():
    """Test that agent can be created with context"""
    print("Testing agent creation...")
    
    context = {
        "account_name": "Test School District",
        "contact_name": "John Doe",
        "previous_contact": "email",
        "email_topic": "voice modernization",
        "email_sent_date": "last week",
        "previous_pain_points": ["aging system", "no failover"]
    }
    
    agent = FollowUpAgent(context=context)
    
    assert agent.name == "follow-up-agent", "Agent name mismatch"
    assert agent.context["account_name"] == "Test School District", "Context not stored"
    
    print("✅ Agent creation test passed")
    return agent

def test_swaig_functions(agent):
    """Test SWAIG function definitions"""
    print("\nTesting SWAIG functions...")
    
    # Test get_product_info
    result = agent.get_product_info({"topic": "pricing"}, None)
    assert "pricing varies" in result.response.lower(), "Product info function failed"
    print("✅ get_product_info works")
    
    # Test schedule_meeting
    result = agent.schedule_meeting({
        "meeting_type": "technical_call",
        "time_preference": "morning",
        "urgency": "this_week"
    }, None)
    assert "technical call" in result.response.lower(), "Schedule meeting function failed"
    print("✅ schedule_meeting works")
    
    # Test save_follow_up_result
    result = agent.save_follow_up_result({
        "outcome": "interested_meeting_booked",
        "interest_level": 8,
        "next_action": "Technical call scheduled for Tuesday",
        "notes": "Very interested in local survivability"
    }, None)
    print(f"   Result: {result.response}")
    print("✅ save_follow_up_result works")
    
    print("\n✅ All SWAIG function tests passed")

def test_prompt_sections(agent):
    """Test that prompt sections are configured"""
    print("\nTesting prompt configuration...")
    
    # Check that agent has necessary attributes
    assert hasattr(agent, 'context'), "Agent missing context"
    assert hasattr(agent, 'db'), "Agent missing Firestore client"
    assert agent.name == "follow-up-agent", "Agent name incorrect"
    
    print("✅ Prompt configuration test passed")
    print(f"   Agent name: {agent.name}")
    print(f"   Context keys: {list(agent.context.keys())}")

def main():
    print("="*70)
    print("🧪 Follow-Up Agent Test Suite")
    print("="*70)
    
    try:
        # Run tests
        agent = test_agent_creation()
        test_swaig_functions(agent)
        test_prompt_sections(agent)
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
