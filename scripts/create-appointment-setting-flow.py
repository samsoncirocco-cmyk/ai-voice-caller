#!/usr/bin/env python3
"""
Create Appointment Setting Flow for Dialogflow CX Agent
Flow: Purpose Confirmation → Availability Check → Suggest Times → Book Meeting
"""
import os
import sys
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.protobuf import field_mask_pb2

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
FLOW_DISPLAY_NAME = "appointment-setting"
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
            description="Appointment setting flow - Schedule meetings with prospects"
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

def create_appointment_flow():
    """Create Appointment Setting conversation flow."""
    
    agent_name = load_agent_name()
    print(f"Creating Appointment Setting flow for agent: {agent_name}\n")
    
    # Initialize clients
    flows_client = dialogflow_cx.FlowsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    pages_client = dialogflow_cx.PagesClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Step 1: Create or get flow
    print("1. Setting up flow 'appointment-setting'...")
    flow_name = get_or_create_flow(flows_client, agent_name, FLOW_DISPLAY_NAME)
    print()
    
    # Step 2: Create pages
    print("2. Creating conversation pages...")
    
    pages = {}
    
    # Page 1: Purpose Confirmation
    pages['purpose-confirmation'] = create_page(
        pages_client, flow_name, "purpose-confirmation",
        entry_message="Hi, this is Paul from Fortinet. You mentioned wanting to discuss improving your voice and network infrastructure. Is that still something you'd like to explore?"
    )
    
    # Page 2: Availability Inquiry
    pages['availability-inquiry'] = create_page(
        pages_client, flow_name, "availability-inquiry",
        entry_message="Great! I'd love to set up a brief 15 to 30 minute call with one of our engineers. Are you generally more available mornings or afternoons?"
    )
    
    # Page 3: Suggest Times
    pages['suggest-times'] = create_page(
        pages_client, flow_name, "suggest-times",
        entry_message="Perfect. I have a few options available. Would Tuesday at 10am, Wednesday at 2pm, or Thursday at 11am work for you?"
    )
    
    # Page 4: Alternate Time Handling
    pages['alternate-time'] = create_page(
        pages_client, flow_name, "alternate-time",
        entry_message="No problem. What day and time would work best for you?"
    )
    
    # Page 5: Collect Email
    pages['collect-email'] = create_page(
        pages_client, flow_name, "collect-email",
        entry_message="Excellent! To send you the calendar invite, what's the best email address to use?"
    )
    
    # Page 6: Calendar Booking
    pages['calendar-booking'] = create_page(
        pages_client, flow_name, "calendar-booking",
        entry_message="Perfect! Let me confirm: I'm booking a 30-minute call for $session.params.meeting_date at $session.params.meeting_time. I'll send the calendar invite to $session.params.email. Sound good?"
    )
    
    # Page 7: Confirmation
    pages['confirmation'] = create_page(
        pages_client, flow_name, "confirmation",
        entry_message="All set! You'll receive the calendar invite shortly. We're looking forward to speaking with you. Have a great day!"
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
    
    config_file = os.path.join(config_dir, "appointment-setting-flow.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    # Save flow name for other scripts
    flow_name_file = os.path.join(config_dir, "appointment-setting-flow-name.txt")
    with open(flow_name_file, "w") as f:
        f.write(flow_name)
    
    print(f"   ✓ Config saved: appointment-setting-flow.json")
    print(f"   ✓ Flow name saved: appointment-setting-flow-name.txt")
    print()
    
    # Success message
    print("=" * 70)
    print("✅ APPOINTMENT SETTING FLOW READY!")
    print("=" * 70)
    print()
    print("Conversation Structure:")
    print("  1. Purpose Confirmation → Confirm still interested")
    print("  2. Availability Inquiry → Morning or afternoon?")
    print("  3. Suggest Times → Offer 3 specific slots")
    print("  4. Alternate Time → If none work, ask for their preference")
    print("  5. Collect Email → Get email for calendar invite")
    print("  6. Calendar Booking → Confirm details (webhook to book)")
    print("  7. Confirmation → Calendar invite sent, thank you")
    print()
    print(f"🎤 Voice: {TTS_VOICE}")
    print("=" * 70)
    print()
    print(f"🎉 Success: {flow_name}")
    print()
    print("Next Steps:")
    print("  1. Implement calendar-availability webhook (check free slots)")
    print("  2. Implement calendar-book webhook (create Google Calendar event)")
    print("  3. Add intents for routing (time_slot.accept, time_slot.reject, etc.)")
    print("  4. Test with: python3 scripts/make-test-call.py --flow appointment-setting")
    print()

if __name__ == "__main__":
    try:
        create_appointment_flow()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
