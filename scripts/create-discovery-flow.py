#!/usr/bin/env python3
"""
Create Discovery Mode Flow for Dialogflow CX Agent
Flow: Greeting → Ask for IT Contact → Get Phone → Confirm → End
"""
import os
import sys
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.protobuf import field_mask_pb2

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
FLOW_DISPLAY_NAME = "discovery-mode"
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

def get_or_create_page(pages_client, flow_name, page_def, display_name):
    """Create a page or return existing one if it already exists."""
    try:
        response = pages_client.create_page(parent=flow_name, page=page_def)
        print(f"   ✓ Created: {display_name}")
        return response.name
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            print(f"   ⚠ {display_name} exists, finding it...")
            request = dialogflow_cx.ListPagesRequest(parent=flow_name)
            pages = pages_client.list_pages(request=request)
            for p in pages:
                if p.display_name == display_name:
                    print(f"   ✓ Found: {display_name}")
                    return p.name
        raise Exception(f"Could not create or find {display_name}: {e}")

def create_discovery_flow():
    """Create Discovery Mode conversation flow."""
    
    agent_name = load_agent_name()
    print(f"Creating Discovery Mode flow for agent: {agent_name}")
    
    # Initialize clients
    flows_client = dialogflow_cx.FlowsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    pages_client = dialogflow_cx.PagesClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Create or get the flow
    print(f"\n1. Setting up flow '{FLOW_DISPLAY_NAME}'...")
    flow = dialogflow_cx.Flow(
        display_name=FLOW_DISPLAY_NAME,
        description="Discovery Mode - Ask for IT contact info from main lines",
    )
    
    flow_name = None
    try:
        flow_response = flows_client.create_flow(parent=agent_name, flow=flow)
        flow_name = flow_response.name
        print(f"   ✓ Flow created")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            print(f"   ⚠ Flow exists, finding it...")
            request = dialogflow_cx.ListFlowsRequest(parent=agent_name)
            flows = flows_client.list_flows(request=request)
            for f in flows:
                if f.display_name == FLOW_DISPLAY_NAME:
                    flow_name = f.name
                    print(f"   ✓ Found existing flow")
                    break
        if not flow_name:
            raise Exception(f"Could not create or find flow: {e}")
    
    # Get START_PAGE reference
    start_page_name = f"{flow_name}/pages/START_PAGE"
    
    # Create pages
    print(f"\n2. Creating conversation pages...")
    
    # Check existing pages first
    print("   Checking existing pages...")
    request = dialogflow_cx.ListPagesRequest(parent=flow_name)
    existing_pages = pages_client.list_pages(request=request)
    page_map = {p.display_name: p.name for p in existing_pages}
    print(f"   Found {len(page_map)} existing pages")
    
    # Page 1: Greeting
    greeting_text = "Hi, this is Paul calling for Samson from Fortinet. Can you tell me who handles IT at your organization?"
    
    if "greeting" in page_map:
        greeting_page_name = page_map["greeting"]
        print(f"   ✓ Using existing: greeting")
    else:
        greeting_page = dialogflow_cx.Page(
            display_name="greeting",
            entry_fulfillment=dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(
                            text=[greeting_text]
                        )
                    )
                ]
            ),
        )
        greeting_page_name = get_or_create_page(pages_client, flow_name, greeting_page, "greeting")
    
    # Page 2: Capture IT Contact Name
    if "get-contact-name" in page_map:
        get_name_page_name = page_map["get-contact-name"]
        print(f"   ✓ Using existing: get-contact-name")
    else:
        get_name_page = dialogflow_cx.Page(
            display_name="get-contact-name",
            form=dialogflow_cx.Form(
                parameters=[
                    dialogflow_cx.Form.Parameter(
                        display_name="contact_name",
                        entity_type="projects/-/locations/-/agents/-/entityTypes/sys.person",
                        fill_behavior=dialogflow_cx.Form.Parameter.FillBehavior(
                            initial_prompt_fulfillment=dialogflow_cx.Fulfillment(
                                messages=[
                                    dialogflow_cx.ResponseMessage(
                                        text=dialogflow_cx.ResponseMessage.Text(
                                            text=[""]
                                        )
                                    )
                                ]
                            )
                        ),
                        required=True,
                    )
                ]
            ),
        )
        get_name_page_name = get_or_create_page(pages_client, flow_name, get_name_page, "get-contact-name")
    
    # Page 3: Ask for Phone Number
    if "get-phone-number" in page_map:
        get_phone_page_name = page_map["get-phone-number"]
        print(f"   ✓ Using existing: get-phone-number")
    else:
        get_phone_page = dialogflow_cx.Page(
            display_name="get-phone-number",
            entry_fulfillment=dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(
                            text=["And what's their direct phone number?"]
                        )
                    )
                ]
            ),
            form=dialogflow_cx.Form(
                parameters=[
                    dialogflow_cx.Form.Parameter(
                        display_name="phone_number",
                        entity_type="projects/-/locations/-/agents/-/entityTypes/sys.phone-number",
                        fill_behavior=dialogflow_cx.Form.Parameter.FillBehavior(
                            initial_prompt_fulfillment=dialogflow_cx.Fulfillment(
                                messages=[
                                    dialogflow_cx.ResponseMessage(
                                        text=dialogflow_cx.ResponseMessage.Text(
                                            text=[""]
                                        )
                                    )
                                ]
                            )
                        ),
                        required=True,
                    )
                ]
            ),
        )
        get_phone_page_name = get_or_create_page(pages_client, flow_name, get_phone_page, "get-phone-number")
    
    # Page 4: Confirm
    if "confirm" in page_map:
        confirm_page_name = page_map["confirm"]
        print(f"   ✓ Using existing: confirm")
    else:
        confirm_page = dialogflow_cx.Page(
            display_name="confirm",
            entry_fulfillment=dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(
                            text=["Great, so that's $session.params.contact_name at $session.params.phone_number. Is that correct?"]
                        )
                    )
                ]
            ),
            form=dialogflow_cx.Form(
                parameters=[
                    dialogflow_cx.Form.Parameter(
                        display_name="confirmed",
                        entity_type="projects/-/locations/-/agents/-/entityTypes/sys.any",
                        fill_behavior=dialogflow_cx.Form.Parameter.FillBehavior(
                            initial_prompt_fulfillment=dialogflow_cx.Fulfillment(
                                messages=[
                                    dialogflow_cx.ResponseMessage(
                                        text=dialogflow_cx.ResponseMessage.Text(
                                            text=[""]
                                        )
                                    )
                                ]
                            )
                        ),
                        required=True,
                    )
                ]
            ),
        )
        confirm_page_name = get_or_create_page(pages_client, flow_name, confirm_page, "confirm")
    
    # Page 5: End
    if "end" in page_map:
        end_page_name = page_map["end"]
        print(f"   ✓ Using existing: end")
    else:
        end_page = dialogflow_cx.Page(
            display_name="end",
            entry_fulfillment=dialogflow_cx.Fulfillment(
                messages=[
                    dialogflow_cx.ResponseMessage(
                        text=dialogflow_cx.ResponseMessage.Text(
                            text=["Perfect, thank you for your help! Have a great day."]
                        )
                    ),
                    dialogflow_cx.ResponseMessage(
                        end_interaction=dialogflow_cx.ResponseMessage.EndInteraction()
                    )
                ]
            ),
        )
        end_page_name = get_or_create_page(pages_client, flow_name, end_page, "end")
    
    # Configure transition routes
    print(f"\n3. Connecting pages...")
    
    # START_PAGE → Greeting
    try:
        start_page = dialogflow_cx.Page(
            name=start_page_name,
            transition_routes=[
                dialogflow_cx.TransitionRoute(
                    condition="true",
                    target_page=greeting_page_name,
                )
            ],
        )
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=start_page, update_mask=update_mask)
        print(f"   ✓ START_PAGE → Greeting")
    except Exception as e:
        print(f"   ⚠ START_PAGE transition: {e}")
    
    # Greeting → Get Contact Name
    try:
        greeting_page_updated = dialogflow_cx.Page(
            name=greeting_page_name,
            transition_routes=[
                dialogflow_cx.TransitionRoute(
                    condition="true",
                    target_page=get_name_page_name,
                )
            ],
        )
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=greeting_page_updated, update_mask=update_mask)
        print(f"   ✓ Greeting → Get Contact Name")
    except Exception as e:
        print(f"   ⚠ Greeting transition: {e}")
    
    # Get Contact Name → Get Phone Number
    try:
        get_name_page_updated = dialogflow_cx.Page(
            name=get_name_page_name,
            transition_routes=[
                dialogflow_cx.TransitionRoute(
                    condition="$page.params.status = 'FINAL'",
                    target_page=get_phone_page_name,
                )
            ],
        )
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=get_name_page_updated, update_mask=update_mask)
        print(f"   ✓ Get Contact Name → Get Phone Number")
    except Exception as e:
        print(f"   ⚠ Get Name transition: {e}")
    
    # Get Phone Number → Confirm
    try:
        get_phone_page_updated = dialogflow_cx.Page(
            name=get_phone_page_name,
            transition_routes=[
                dialogflow_cx.TransitionRoute(
                    condition="$page.params.status = 'FINAL'",
                    target_page=confirm_page_name,
                )
            ],
        )
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=get_phone_page_updated, update_mask=update_mask)
        print(f"   ✓ Get Phone Number → Confirm")
    except Exception as e:
        print(f"   ⚠ Get Phone transition: {e}")
    
    # Confirm → End
    try:
        confirm_page_updated = dialogflow_cx.Page(
            name=confirm_page_name,
            transition_routes=[
                dialogflow_cx.TransitionRoute(
                    condition="$page.params.status = 'FINAL'",
                    target_page=end_page_name,
                )
            ],
        )
        update_mask = field_mask_pb2.FieldMask(paths=["transition_routes"])
        pages_client.update_page(page=confirm_page_updated, update_mask=update_mask)
        print(f"   ✓ Confirm → End")
    except Exception as e:
        print(f"   ⚠ Confirm transition: {e}")
    
    # Set as agent's start flow
    print(f"\n4. Setting as default flow...")
    try:
        agents_client = dialogflow_cx.AgentsClient(
            client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
        )
        agent = agents_client.get_agent(name=agent_name)
        agent.start_flow = flow_name
        update_mask = field_mask_pb2.FieldMask(paths=["start_flow"])
        agents_client.update_agent(agent=agent, update_mask=update_mask)
        print(f"   ✓ Default flow updated")
    except Exception as e:
        print(f"   ⚠ Start flow: {e}")
    
    # Save configuration
    print(f"\n5. Saving configuration...")
    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    flow_config = {
        "flow_name": flow_name,
        "flow_display_name": FLOW_DISPLAY_NAME,
        "pages": {
            "start": start_page_name,
            "greeting": greeting_page_name,
            "get_contact_name": get_name_page_name,
            "get_phone_number": get_phone_page_name,
            "confirm": confirm_page_name,
            "end": end_page_name,
        },
        "tts_voice": TTS_VOICE,
    }
    
    flow_config_file = os.path.join(config_dir, "discovery-mode-flow.json")
    with open(flow_config_file, "w") as f:
        json.dump(flow_config, f, indent=2)
    print(f"   ✓ Config saved: discovery-mode-flow.json")
    
    # Summary
    print(f"\n{'='*70}")
    print(f"✅ DISCOVERY MODE FLOW READY!")
    print(f"{'='*70}")
    print(f"\nConversation:")
    print(f"  1. '{greeting_text}'")
    print(f"  2. [Listen for IT contact name]")
    print(f"  3. 'And what's their direct phone number?'")
    print(f"  4. [Listen for phone number]")
    print(f"  5. 'Great, so that's [NAME] at [PHONE]. Is that correct?'")
    print(f"  6. [Listen for confirmation]")
    print(f"  7. 'Perfect, thank you for your help! Have a great day.' [Hang up]")
    print(f"\n🎤 Voice: {TTS_VOICE}")
    print(f"{'='*70}")
    
    return flow_name

if __name__ == "__main__":
    try:
        flow_name = create_discovery_flow()
        print(f"\n🎉 Success: {flow_name}")
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
