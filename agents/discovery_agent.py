#!/usr/bin/env python3
"""
Discovery Mode Agent - Collects IT contact information from main lines
Uses SignalWire Agents SDK for natural AI conversation
"""
import os
import sys
import json
from datetime import datetime
from signalwire_agents import AgentBase, SwaigFunctionResult
from google.cloud import firestore

# Configuration
PROJECT_ID = "tatt-pro"
FIRESTORE_COLLECTION = "discovered-contacts"


class DiscoveryAgent(AgentBase):
    """
    Discovery Mode agent that asks for IT contact information.
    
    Conversation flow:
    1. Greets the person who answers
    2. Identifies as Paul calling for Samson from Fortinet
    3. Asks for IT contact name
    4. Asks for direct phone number
    5. Confirms what was heard
    6. Thanks them and ends call
    7. Logs to Firestore
    """
    
    def __init__(self):
        # Set simple, known credentials for SignalWire to use
        super().__init__(
            name="discovery-mode",
            basic_auth=("signalwire", "fortinet2026")  # Username and password
        )
        
        # Configure agent personality and behavior
        self.prompt_add_section(
            "Role",
            """You are Paul, a friendly and professional assistant calling on behalf of 
            Samson from Fortinet. Your goal is to collect IT contact information from 
            organizations in a brief, polite conversation."""
        )
        
        self.prompt_add_section(
            "Task",
            """When someone answers:
            1. Introduce yourself: "Hi, this is Paul calling for Samson from Fortinet."
            2. Ask: "Can you tell me who handles IT at your organization?"
            3. Once you get a name, ask: "And what's their direct phone number?"
            4. Confirm what you heard: "Great, so that's [NAME] at [PHONE]. Is that correct?"
            5. Thank them: "Perfect, thank you for your help! Have a great day."
            6. After confirming, call the save_contact function with the information.
            
            Keep the conversation under 60 seconds. Be friendly but efficient."""
        )
        
        self.prompt_add_section(
            "Guidelines",
            """- If they say "I don't know" or "I'm not sure", politely thank them and end the call
            - If they offer to transfer you, decline politely: "That's okay, I just need the contact info. Thank you!"
            - If they're hesitant, reassure them: "This is just for our records so Samson can reach out directly."
            - Stay professional and courteous at all times
            - Do NOT try to sell anything or set up meetings"""
        )
        
        # Configure voice and language settings
        self.add_language("English", "en-US", "en-US-Neural2-J")  # Professional male voice
        self.set_param("voice", "en-US-Neural2-J")
        
        # Initialize Firestore client
        self.db = firestore.Client(project=PROJECT_ID)
    
    @AgentBase.tool(description="Save the collected IT contact information to the database")
    def save_contact(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Save contact information to Firestore.
        
        Args:
            args: Dictionary containing:
                - contact_name (str): Name of the IT contact
                - phone_number (str): Direct phone number
                - organization (str, optional): Organization name if mentioned
        """
        contact_name = args.get("contact_name", "")
        phone_number = args.get("phone_number", "")
        organization = args.get("organization", "")
        
        # Get call metadata from raw_data if available
        caller_number = raw_data.get("call_from", "") if raw_data else ""
        
        # Prepare document
        doc_data = {
            "contact_name": contact_name,
            "phone_number": phone_number,
            "organization": organization,
            "called_from": caller_number,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "created_at": datetime.utcnow().isoformat(),
            "source": "discovery-mode-agent",
            "status": "new"
        }
        
        try:
            # Save to Firestore
            collection = self.db.collection(FIRESTORE_COLLECTION)
            doc_ref = collection.add(doc_data)
            
            result_message = f"Contact saved: {contact_name} at {phone_number}"
            if organization:
                result_message += f" ({organization})"
            
            print(f"✅ {result_message}")
            print(f"   Document ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to save contact: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message, success=False)
    
    @AgentBase.tool(description="Check if a phone number is already in our database")
    def check_existing_contact(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Check if we already have this contact information.
        
        Args:
            args: Dictionary containing:
                - phone_number (str): Phone number to check
        """
        phone_number = args.get("phone_number", "")
        
        try:
            # Query Firestore
            collection = self.db.collection(FIRESTORE_COLLECTION)
            query = collection.where("phone_number", "==", phone_number).limit(1)
            results = list(query.stream())
            
            if results:
                doc = results[0].to_dict()
                return SwaigFunctionResult(
                    f"We already have a contact at this number: {doc.get('contact_name', 'Unknown')}"
                )
            else:
                return SwaigFunctionResult("This is a new contact.")
                
        except Exception as e:
            return SwaigFunctionResult(f"Could not check database: {str(e)}", success=False)


def main():
    """
    Start the Discovery Mode agent server.
    Listens on port 3000 for incoming SignalWire requests.
    """
    print("="*70)
    print("🤖 Discovery Mode Agent Starting")
    print("="*70)
    print("\nThis agent will:")
    print("  1. Answer incoming calls")
    print("  2. Ask for IT contact information")
    print("  3. Save collected info to Firestore")
    print("\nAgent is ready to receive calls!")
    print(f"\nConnect your SignalWire number to: http://YOUR_PUBLIC_URL:3000/")
    print("="*70)
    
    agent = DiscoveryAgent()
    agent.run(host="0.0.0.0", port=3000)


if __name__ == "__main__":
    main()
