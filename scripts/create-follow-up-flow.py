#!/usr/bin/env python3
"""
Create Follow-Up Flow for Dialogflow CX Agent
Flow: Context Reminder → Progress Check → Question Handling → Next Steps
"""
import os
import sys
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.protobuf import field_mask_pb2

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
FLOW_DISPLAY_NAME = "follow-up"
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
            description="Follow-up flow - Re-engage prospects after initial contact"
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

def create_follow_up_flow():
    """Create Follow-Up conversation flow."""
    
    agent_name = load_agent_name()
    print(f"Creating Follow-Up flow for agent: {agent_name}\n")
    
    # Initialize clients
    flows_client = dialogflow_cx.FlowsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    pages_client = dialogflow_cx.PagesClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Step 1: Create or get flow
    print("1. Setting up flow 'follow-up'...")
    flow_name = get_or_create_flow(flows_client, agent_name, FLOW_DISPLAY_NAME)
    print()
    
    # Step 2: Create pages
    print("2. Creating conversation pages...")
    
    pages = {}
    
    # Page 1: Context Reminder
    pages['context-reminder'] = create_page(
        pages_client, flow_name, "context-reminder",
        entry_message="Hi, this is Paul from Fortinet. We spoke last week about your voice and network needs at $session.params.account_name. Do you remember our conversation?"
    )
    
    # Page 2: Re-explain Context (if they don't remember)
    pages['re-explain'] = create_page(
        pages_client, flow_name, "re-explain",
        entry_message="No problem! We discussed improving your phone system and network infrastructure. I was calling to see if you had any questions or if you'd reviewed the information I sent over."
    )
    
    # Page 3: Progress Check
    pages['progress-check'] = create_page(
        pages_client, flow_name, "progress-check",
        entry_message="Great! Have you had a chance to review the materials I sent, or do you have any questions I can answer?"
    )
    
    # Page 4: Question Handling
    pages['question-handling'] = create_page(
        pages_client, flow_name, "question-handling",
        entry_message="That's a great question. Let me address that..."
    )
    
    # Page 5: Next Steps
    pages['next-steps'] = create_page(
        pages_client, flow_name, "next-steps",
        entry_message="Based on our conversation, would you like to schedule a quick 15-minute call with one of our engineers, or should I send additional information?"
    )
    
    # Page 6: End Call
    pages['end-call'] = create_page(
        pages_client, flow_name, "end-call",
        entry_message="Perfect! I'll follow up as we discussed. Thanks for your time and have a great day!"
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
        "tts_voice": TTS_VOICE
    }
    
    config_file = os.path.join(config_dir, "follow-up-flow.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    # Save flow name for other scripts
    flow_name_file = os.path.join(config_dir, "follow-up-flow-name.txt")
    with open(flow_name_file, "w") as f:
        f.write(flow_name)
    
    print(f"   ✓ Config saved: follow-up-flow.json")
    print(f"   ✓ Flow name saved: follow-up-flow-name.txt")
    print()
    
    # Success message
    print("=" * 70)
    print("✅ FOLLOW-UP FLOW READY!")
    print("=" * 70)
    print()
    print("Conversation Structure:")
    print("  1. Context Reminder → 'We spoke last week...'")
    print("  2. Re-explain (if needed) → Brief recap")
    print("  3. Progress Check → 'Have you reviewed the materials?'")
    print("  4. Question Handling → Answer their questions")
    print("  5. Next Steps → Schedule call or send more info")
    print("  6. End Call → Thank and hang up")
    print()
    print(f"🎤 Voice: {TTS_VOICE}")
    print("=" * 70)
    print()
    print(f"🎉 Success: {flow_name}")
    print()
    print("Next Steps:")
    print("  1. Configure webhook to load previous call context from Firestore")
    print("  2. Add intents for routing (context_confirmed, progress.reviewed, etc.)")
    print("  3. Test with: python3 scripts/make-test-call.py --flow follow-up")
    print()

if __name__ == "__main__":
    try:
        create_follow_up_flow()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
