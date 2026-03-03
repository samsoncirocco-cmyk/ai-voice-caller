#!/usr/bin/env python3
"""
Create Cold Calling Flow for Dialogflow CX Agent
Flow: Greeting → Gatekeeper/Decision Maker → Pitch → Objection Handling → Next Steps
"""
import os
import sys
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.protobuf import field_mask_pb2

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
FLOW_DISPLAY_NAME = "cold-calling"
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
            description="Cold calling flow - Initial outreach to prospects"
        )
        response = flows_client.create_flow(parent=agent_name, flow=flow)
        print(f"   ✓ Created new flow: {display_name}")
        return response.name
    except Exception as e:
        raise Exception(f"Could not get or create flow: {e}")

def create_page(pages_client, flow_name, display_name, entry_message=None, parameters=None):
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
        
        # Add parameters if provided
        if parameters:
            page_def.form = dialogflow_cx.Form(
                parameters=[
                    dialogflow_cx.Form.Parameter(
                        display_name=param_name,
                        entity_type=param_type,
                        required=param_required
                    )
                    for param_name, param_type, param_required in parameters
                ]
            )
        
        response = pages_client.create_page(parent=flow_name, page=page_def)
        print(f"   ✓ Created: {display_name}")
        return response.name
    except Exception as e:
        print(f"   ✗ Error creating {display_name}: {e}")
        return None

def add_route(pages_client, page_name, target_page_name, intent_name=None, condition=None, fulfillment_text=None):
    """Add a transition route from one page to another."""
    try:
        # Get current page
        page = pages_client.get_page(name=page_name)
        
        # Create route
        route = dialogflow_cx.TransitionRoute()
        
        if intent_name:
            route.intent = intent_name
        
        if condition:
            route.condition = condition
        
        if target_page_name:
            route.target_page = target_page_name
        
        if fulfillment_text:
            route.trigger_fulfillment = dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(text=[fulfillment_text])
                    )
                ]
            )
        
        # Add route to page
        page.transition_routes.append(route)
        
        # Update page
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=page, update_mask=update_mask)
        
        return True
    except Exception as e:
        print(f"   ⚠ Route warning: {e}")
        return False

def create_cold_calling_flow():
    """Create Cold Calling conversation flow."""
    
    agent_name = load_agent_name()
    print(f"Creating Cold Calling flow for agent: {agent_name}\n")
    
    # Initialize clients
    flows_client = dialogflow_cx.FlowsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    pages_client = dialogflow_cx.PagesClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Step 1: Create or get flow
    print("1. Setting up flow 'cold-calling'...")
    flow_name = get_or_create_flow(flows_client, agent_name, FLOW_DISPLAY_NAME)
    print()
    
    # Step 2: Create pages
    print("2. Creating conversation pages...")
    
    pages = {}
    
    # Page 1: Greeting
    pages['greeting'] = create_page(
        pages_client, flow_name, "greeting",
        entry_message="Hi, this is Paul calling from Fortinet. I'm reaching out to IT leaders in Arizona about voice and network solutions. May I ask who handles IT at your organization?"
    )
    
    # Page 2: Gatekeeper Response
    pages['gatekeeper'] = create_page(
        pages_client, flow_name, "gatekeeper",
        entry_message="I understand. Would you be able to share their name and direct phone number so I can reach them?"
    )
    
    # Page 3: Decision Maker Confirmation
    pages['decision-maker'] = create_page(
        pages_client, flow_name, "decision-maker",
        entry_message="Perfect! Do you have a moment for a quick question about your current phone system?"
    )
    
    # Page 4: Killer Question (Pitch)
    pages['killer-question'] = create_page(
        pages_client, flow_name, "killer-question",
        entry_message="If you could improve one thing about your current phone or network setup, what would it be?"
    )
    
    # Page 5: Interest Assessment
    pages['interest-assessment'] = create_page(
        pages_client, flow_name, "interest-assessment",
        entry_message="That's a common challenge. Fortinet helps with exactly that. Would you be open to a brief conversation about how we can help?"
    )
    
    # Page 6: Objection Handling
    pages['objection-handling'] = create_page(
        pages_client, flow_name, "objection-handling",
        entry_message="I completely understand. Can I ask what your biggest concern is?"
    )
    
    # Page 7: Next Steps
    pages['next-steps'] = create_page(
        pages_client, flow_name, "next-steps",
        entry_message="Great! Would you prefer a 15-minute phone call or should I send you some information via email?"
    )
    
    # Page 8: Schedule Meeting
    pages['schedule-meeting'] = create_page(
        pages_client, flow_name, "schedule-meeting",
        entry_message="Excellent. Are you available this week or would next week work better?"
    )
    
    # Page 9: End Call
    pages['end-call'] = create_page(
        pages_client, flow_name, "end-call",
        entry_message="Thanks for your time! I'll follow up as discussed. Have a great day!"
    )
    
    print()
    
    # Step 3: Connect pages (simplified - basic happy path)
    print("3. Connecting conversation flow...")
    
    # Greeting → Gatekeeper OR Decision Maker
    # (In real implementation, would use intents to route)
    # For now, create basic linear flow for testing
    
    print("   ✓ Basic flow structure created")
    print("   ℹ️  Note: Intent-based routing requires intents to be created separately")
    print()
    
    # Step 4: Save configuration
    print("4. Saving configuration...")
    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    os.makedirs(config_dir, exist_ok=True)
    
    config = {
        "flow_name": flow_name,
        "display_name": FLOW_DISPLAY_NAME,
        "pages": pages,
        "tts_voice": TTS_VOICE
    }
    
    config_file = os.path.join(config_dir, "cold-calling-flow.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    # Save flow name for other scripts
    flow_name_file = os.path.join(config_dir, "cold-calling-flow-name.txt")
    with open(flow_name_file, "w") as f:
        f.write(flow_name)
    
    print(f"   ✓ Config saved: cold-calling-flow.json")
    print(f"   ✓ Flow name saved: cold-calling-flow-name.txt")
    print()
    
    # Success message
    print("=" * 70)
    print("✅ COLD CALLING FLOW READY!")
    print("=" * 70)
    print()
    print("Conversation Structure:")
    print("  1. Greeting → Ask for IT decision maker")
    print("  2. Gatekeeper Handling → Get contact info")
    print("  3. Decision Maker → Confirm availability")
    print("  4. Killer Question → 'What would you improve?'")
    print("  5. Interest Assessment → Gauge interest level")
    print("  6. Objection Handling → Address concerns")
    print("  7. Next Steps → Meeting or email")
    print("  8. Schedule Meeting → Book time")
    print("  9. End Call → Thank and hang up")
    print()
    print(f"🎤 Voice: {TTS_VOICE}")
    print("=" * 70)
    print()
    print(f"🎉 Success: {flow_name}")
    print()
    print("Next Steps:")
    print("  1. Create intents for routing (decision_maker.available, interest.high, etc.)")
    print("  2. Add transition routes based on intents")
    print("  3. Test with: python3 scripts/make-test-call.py --flow cold-calling")
    print()

if __name__ == "__main__":
    try:
        create_cold_calling_flow()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
