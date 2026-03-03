#!/usr/bin/env python3
"""
Create Lead Qualification Flow for Dialogflow CX Agent
Flow: BANT Qualification (Budget, Authority, Need, Timeline) → Score → Route
"""
import os
import sys
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.protobuf import field_mask_pb2

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
FLOW_DISPLAY_NAME = "lead-qualification"
TTS_VOICE = "en-US-Neural2-J"  # Male voice

def load_agent_name():
    """Load agent name from config file."""
    config_file = os.path.join(os.path.dirname(__file__), "..", "config", "agent-name.txt")
    if not os.path.exists(config_file):
        raise FileNotFoundError(
            f"Agent name file not found: {config_file}\n"
            "Run create-agent.py first to create the agent."
        )
    with open(config_file, "r") as f:
        return f.read().strip()

def get_or_create_flow(flows_client, agent_name, display_name):
    """Get existing flow or create new one."""
    try:
        # List existing flows
        request = dialogflow_cx.ListFlowsRequest(parent=agent_name)
        flows = flows_client.list_flows(request=request)
        
        for flow in flows:
            if flow.display_name == display_name:
                print(f"   ✓ Found existing flow: {display_name}")
                return flow.name
        
        # Create new flow
        flow = dialogflow_cx.Flow(
            display_name=display_name,
            description="Lead qualification flow - BANT assessment and lead scoring"
        )
        response = flows_client.create_flow(parent=agent_name, flow=flow)
        print(f"   ✓ Created new flow: {display_name}")
        return response.name
    except Exception as e:
        raise Exception(f"Could not get or create flow: {e}")

def create_page(pages_client, flow_name, display_name, entry_message=None):
    """Create a page with entry fulfillment."""
    try:
        # Check if page exists
        request = dialogflow_cx.ListPagesRequest(parent=flow_name)
        pages = pages_client.list_pages(request=request)
        
        for p in pages:
            if p.display_name == display_name:
                print(f"   ✓ Using existing: {display_name}")
                return p.name
        
        # Create new page
        page_def = dialogflow_cx.Page(display_name=display_name)
        
        # Add entry fulfillment if provided
        if entry_message:
            page_def.entry_fulfillment = dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(text=[entry_message])
                    )
                ]
            )
        
        response = pages_client.create_page(parent=flow_name, page=page_def)
        print(f"   ✓ Created: {display_name}")
        return response.name
    except Exception as e:
        print(f"   ✗ Error creating {display_name}: {e}")
        return None

def create_lead_qualification_flow():
    """Create Lead Qualification conversation flow."""
    
    agent_name = load_agent_name()
    print(f"Creating Lead Qualification flow for agent: {agent_name}\n")
    
    # Initialize clients
    flows_client = dialogflow_cx.FlowsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    pages_client = dialogflow_cx.PagesClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Step 1: Create or get flow
    print("1. Setting up flow 'lead-qualification'...")
    flow_name = get_or_create_flow(flows_client, agent_name, FLOW_DISPLAY_NAME)
    print()
    
    # Step 2: Create pages
    print("2. Creating conversation pages (BANT qualification)...")
    
    pages = {}
    
    # Page 1: Needs Assessment
    pages['needs-assessment'] = create_page(
        pages_client, flow_name, "needs-assessment",
        entry_message="Hi, this is Paul from Fortinet. I wanted to ask you a few quick questions about your current voice and network setup to see if we might be a good fit. What's your biggest challenge right now with your phone system or network?"
    )
    
    # Page 2: Budget Inquiry
    pages['budget-inquiry'] = create_page(
        pages_client, flow_name, "budget-inquiry",
        entry_message="That makes sense. Do you currently have budget allocated for improving or upgrading your voice and network infrastructure this year?"
    )
    
    # Page 3: Authority Check
    pages['authority-check'] = create_page(
        pages_client, flow_name, "authority-check",
        entry_message="Got it. Are you the primary decision maker for voice and network purchases, or would someone else be involved in that decision?"
    )
    
    # Page 4: Timeline Discussion
    pages['timeline-discussion'] = create_page(
        pages_client, flow_name, "timeline-discussion",
        entry_message="Thanks for clarifying. When are you looking to make a decision or implement a new solution? Is this something you need in the next few months, or are you planning for later this year?"
    )
    
    # Page 5: Current System Discovery
    pages['current-system'] = create_page(
        pages_client, flow_name, "current-system",
        entry_message="That's helpful. What are you currently using for your phone system? For example, Cisco, Microsoft Teams, or something else?"
    )
    
    # Page 6: User Count
    pages['user-count'] = create_page(
        pages_client, flow_name, "user-count",
        entry_message="And roughly how many users or phones do you support across your organization?"
    )
    
    # Page 7: Lead Score Calculation (webhook)
    pages['score-calculation'] = create_page(
        pages_client, flow_name, "score-calculation",
        entry_message="Thanks for answering those questions. Let me see how we can best help you..."
    )
    
    # Page 8: High Score Route (Qualified - Propose Meeting)
    pages['qualified-route'] = create_page(
        pages_client, flow_name, "qualified-route",
        entry_message="Based on what you've shared, it sounds like we could definitely help. I'd love to set up a quick 15-minute call with one of our engineers to discuss your specific needs. Would that work for you?"
    )
    
    # Page 9: Medium Score Route (Nurture - Send Info)
    pages['nurture-route'] = create_page(
        pages_client, flow_name, "nurture-route",
        entry_message="Thank you for your time. It sounds like you're still exploring options. I'll send you some information about Fortinet's solutions, and we can reconnect when the timing is better. Does that work?"
    )
    
    # Page 10: Low Score Route (Disqualified - Polite Exit)
    pages['disqualified-route'] = create_page(
        pages_client, flow_name, "disqualified-route",
        entry_message="I appreciate you taking the time to chat with me. It sounds like you're all set for now. If anything changes down the road, feel free to reach out. Have a great day!"
    )
    
    print()
    
    # Step 3: Save configuration
    print("3. Saving configuration...")
    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    os.makedirs(config_dir, exist_ok=True)
    
    config = {
        "flow_name": flow_name,
        "display_name": FLOW_DISPLAY_NAME,
        "pages": pages,
        "tts_voice": TTS_VOICE,
        "scoring_criteria": {
            "needs": {"weight": 25, "has_pain_point": 25, "no_pain_point": 0},
            "budget": {"weight": 25, "allocated": 25, "not_allocated": 5, "unknown": 15},
            "authority": {"weight": 25, "decision_maker": 25, "influencer": 15, "gatekeeper": 5},
            "timeline": {"weight": 25, "immediate": 25, "short_term": 15, "long_term": 5, "none": 0}
        },
        "routing": {
            "qualified": {"min_score": 70, "action": "propose_meeting"},
            "nurture": {"min_score": 40, "max_score": 69, "action": "send_info"},
            "disqualified": {"max_score": 39, "action": "polite_exit"}
        }
    }
    
    config_file = os.path.join(config_dir, "lead-qualification-flow.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    # Save flow name for other scripts
    flow_name_file = os.path.join(config_dir, "lead-qualification-flow-name.txt")
    with open(flow_name_file, "w") as f:
        f.write(flow_name)
    
    print(f"   ✓ Config saved: lead-qualification-flow.json")
    print(f"   ✓ Flow name saved: lead-qualification-flow-name.txt")
    print()
    
    # Success message
    print("=" * 70)
    print("✅ LEAD QUALIFICATION FLOW READY!")
    print("=" * 70)
    print()
    print("Conversation Structure (BANT Qualification):")
    print("  1. Needs Assessment → 'What's your biggest challenge?'")
    print("  2. Budget Inquiry → 'Do you have budget allocated?'")
    print("  3. Authority Check → 'Are you the decision maker?'")
    print("  4. Timeline Discussion → 'When are you looking to decide?'")
    print("  5. Current System → 'What are you using now?'")
    print("  6. User Count → 'How many users?'")
    print("  7. Score Calculation → (Webhook calculates BANT score)")
    print("  8. Qualified Route (Score 70+) → Propose meeting")
    print("  9. Nurture Route (Score 40-69) → Send info, follow up later")
    print(" 10. Disqualified Route (Score <40) → Polite exit")
    print()
    print("Scoring Criteria:")
    print("  - Needs (25 points): Has pain point vs. no needs")
    print("  - Budget (25 points): Allocated vs. not allocated")
    print("  - Authority (25 points): Decision maker vs. influencer vs. gatekeeper")
    print("  - Timeline (25 points): Immediate vs. short-term vs. long-term")
    print("  - Total: 100 points")
    print()
    print(f"🎤 Voice: {TTS_VOICE}")
    print("=" * 70)
    print()
    print(f"🎉 Success: {flow_name}")
    print()
    print("Next Steps:")
    print("  1. Implement lead-scorer webhook (calculate BANT score)")
    print("  2. Add intents for routing (needs.express, budget.allocated, etc.)")
    print("  3. Configure conditional routing based on score")
    print("  4. Test with: python3 scripts/make-test-call.py --flow lead-qualification")
    print()

if __name__ == "__main__":
    try:
        create_lead_qualification_flow()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
