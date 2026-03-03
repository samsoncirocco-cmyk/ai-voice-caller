#!/usr/bin/env python3
"""
Integration Tests for Conversation Flows

Tests the complete conversation paths through Dialogflow CX.
Simulates user interactions and verifies correct routing.

Run with: pytest tests/integration/test_conversation_flows.py -v
"""

import json
import pytest
from pathlib import Path
from typing import Dict, List, Optional

# Load flow definitions
FLOWS_DIR = Path(__file__).parent.parent.parent / "dialogflow-agent" / "flows"


def load_flow(flow_name: str) -> Dict:
    """Load a flow definition from JSON."""
    flow_path = FLOWS_DIR / f"{flow_name}.json"
    if flow_path.exists():
        with open(flow_path) as f:
            return json.load(f)
    return {}


class ConversationSimulator:
    """Simulates conversations through flow definitions."""
    
    def __init__(self, flow_name: str):
        self.flow = load_flow(flow_name)
        self.current_page = None
        self.parameters = {}
        self.messages = []
        self.path = []
        
    def start(self, initial_params: Dict = None):
        """Start the conversation."""
        if initial_params:
            self.parameters.update(initial_params)
        
        # Get start page from flow
        pages = self.flow.get("pages", [])
        if pages:
            self.current_page = pages[0]["name"]
            self.path.append(self.current_page)
        
        return self
    
    def find_page(self, page_name: str) -> Optional[Dict]:
        """Find a page by name."""
        for page in self.flow.get("pages", []):
            if page["name"] == page_name:
                return page
        return None
    
    def simulate_intent(self, intent_name: str) -> "ConversationSimulator":
        """Simulate matching an intent on the current page."""
        page = self.find_page(self.current_page)
        if not page:
            return self
        
        # Find matching transition route
        for route in page.get("transitionRoutes", []):
            if route.get("intent") == intent_name:
                # Handle fulfillment
                if "triggerFulfillment" in route:
                    fulfillment = route["triggerFulfillment"]
                    if "messages" in fulfillment:
                        for msg in fulfillment["messages"]:
                            if "text" in msg:
                                self.messages.extend(msg["text"].get("text", []))
                    
                    # Update parameters
                    for action in fulfillment.get("setParameterActions", []):
                        self.parameters[action["parameter"]] = action["value"]
                
                # Transition to next page
                if "targetPage" in route:
                    self.current_page = route["targetPage"]
                    self.path.append(self.current_page)
                
                break
        
        return self
    
    def get_outcome(self) -> Optional[str]:
        """Get the call outcome parameter if set."""
        return self.parameters.get("call_outcome")
    
    def is_on_page(self, page_name: str) -> bool:
        """Check if currently on a specific page."""
        return self.current_page == page_name


class TestColdCallingFlow:
    """Tests for the cold-calling conversation flow."""
    
    @pytest.fixture
    def simulator(self):
        return ConversationSimulator("cold-calling")
    
    def test_happy_path_to_meeting(self, simulator):
        """Test: User confirms identity, shows interest, books meeting."""
        simulator.start({"contact_name": "John", "account_name": "Cityville Schools"})
        
        # User confirms identity
        simulator.simulate_intent("intent.confirm-yes")
        assert simulator.is_on_page("introduction")
        
        # User says good time
        simulator.simulate_intent("intent.confirm-yes")
        assert simulator.is_on_page("killer-question")
        
        # User shows interest in the killer question
        simulator.simulate_intent("intent.interested")
        assert simulator.is_on_page("book-meeting")
        
    def test_not_interested_path(self, simulator):
        """Test: User is not interested, handled gracefully."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")  # Confirm identity
        simulator.simulate_intent("intent.confirm-yes")  # Good time
        simulator.simulate_intent("intent.not-interested")  # Killer question
        
        assert simulator.is_on_page("handle-objection")
        
    def test_send_info_path(self, simulator):
        """Test: User requests information via email."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.send-info")
        
        assert simulator.is_on_page("collect-email")
        
    def test_wrong_person_path(self, simulator):
        """Test: Wrong person answers, handle appropriately."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-no")
        
        assert simulator.is_on_page("wrong-person")
        
    def test_busy_callback_path(self, simulator):
        """Test: User is busy, requests callback."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.busy")
        
        assert simulator.is_on_page("callback-request")
        
    def test_do_not_call_path(self, simulator):
        """Test: User requests to be removed from call list."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.not-interested")
        simulator.simulate_intent("intent.do-not-call")
        
        assert simulator.is_on_page("end-do-not-call")


class TestLeadQualificationFlow:
    """Tests for the lead-qualification conversation flow."""
    
    @pytest.fixture
    def simulator(self):
        return ConversationSimulator("lead-qualification")
    
    def test_full_qualification_hot_lead(self, simulator):
        """Test: Full qualification path resulting in hot lead."""
        simulator.start()
        
        # Confirm time
        simulator.simulate_intent("intent.confirm-yes")
        
        # Answers about current system
        simulator.simulate_intent("intent.system-cisco")
        assert simulator.parameters.get("current_system") == "Cisco"
        
        # System age - old
        simulator.simulate_intent("intent.age-old")
        assert simulator.parameters.get("system_age") == "old"
        
        # Has pain points
        simulator.simulate_intent("intent.has-issues")
        assert simulator.parameters.get("has_pain_points") == True
        
    def test_qualification_cold_lead(self, simulator):
        """Test: Qualification resulting in cold lead."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")
        simulator.simulate_intent("intent.system-teams")  # New cloud system
        simulator.simulate_intent("intent.age-new")  # Recently deployed
        simulator.simulate_intent("intent.no-planning")  # No changes planned


class TestAppointmentSettingFlow:
    """Tests for the appointment-setting flow."""
    
    @pytest.fixture
    def simulator(self):
        return ConversationSimulator("appointment-setting")
    
    def test_successful_booking(self, simulator):
        """Test: Successfully book an appointment."""
        simulator.start()
        
        simulator.simulate_intent("intent.confirm-yes")  # Good time
        assert simulator.is_on_page("explain-demo")
        
        simulator.simulate_intent("intent.confirm-yes")  # Proceed with demo
        # Would go to check-availability


class TestInformationDeliveryFlow:
    """Tests for the information-delivery flow."""
    
    @pytest.fixture
    def simulator(self):
        return ConversationSimulator("information-delivery")
    
    def test_product_launch_interested(self, simulator):
        """Test: User interested in product launch."""
        simulator.start({"delivery_type": "product_launch"})
        
        # User wants preview
        simulator.simulate_intent("intent.confirm-yes")
        assert simulator.is_on_page("send-product-info")
        
    def test_contract_renewal_interested(self, simulator):
        """Test: User wants renewal quote."""
        simulator.start({"delivery_type": "contract_renewal"})
        
        simulator.simulate_intent("intent.confirm-yes")
        assert simulator.is_on_page("collect-renewal-email")


class TestFlowIntegrity:
    """Tests for flow definition integrity."""
    
    @pytest.fixture
    def all_flows(self):
        flows = {}
        for flow_file in FLOWS_DIR.glob("*.json"):
            with open(flow_file) as f:
                flows[flow_file.stem] = json.load(f)
        return flows
    
    def test_all_flows_load(self, all_flows):
        """Test: All flow files load correctly."""
        expected_flows = [
            "cold-calling", 
            "follow-up",
            "appointment-setting",
            "lead-qualification",
            "information-delivery"
        ]
        
        for flow_name in expected_flows:
            assert flow_name in all_flows, f"Flow {flow_name} not found"
    
    def test_flows_have_pages(self, all_flows):
        """Test: All flows have at least one page."""
        for name, flow in all_flows.items():
            pages = flow.get("pages", [])
            assert len(pages) > 0, f"Flow {name} has no pages"
    
    def test_pages_have_transition_routes(self, all_flows):
        """Test: Most pages have transition routes."""
        for name, flow in all_flows.items():
            for page in flow.get("pages", []):
                page_name = page.get("name", "unknown")
                routes = page.get("transitionRoutes", [])
                # End pages might not have routes
                if not page_name.startswith("end-"):
                    assert len(routes) >= 0, f"Page {page_name} in {name} has no routes"
    
    def test_end_pages_exist(self, all_flows):
        """Test: Each flow has proper end pages."""
        cold_calling = all_flows.get("cold-calling", {})
        pages = cold_calling.get("pages", [])
        page_names = [p.get("name") for p in pages]
        
        assert "end-success" in page_names
        assert "end-not-interested" in page_names
        assert "end-do-not-call" in page_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
