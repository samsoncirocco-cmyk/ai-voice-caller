#!/usr/bin/env python3
"""
Follow-Up Agent - Nurtures warm leads after initial contact
Uses SignalWire Agents SDK for natural AI conversation
"""
import os
import sys
import json
from datetime import datetime, timedelta
from signalwire_agents import AgentBase, SwaigFunctionResult
from google.cloud import firestore

# Configuration
PROJECT_ID = "tatt-pro"
FIRESTORE_COLLECTION = "follow-up-calls"
CONTACTS_COLLECTION = "discovered-contacts"


class FollowUpAgent(AgentBase):
    """
    Follow-Up agent that reconnects with prospects after initial contact.
    
    Conversation flow:
    1. Greets contact warmly by name
    2. References previous interaction (email/quote/demo)
    3. Checks if they received and reviewed the material
    4. Gauges interest level
    5. Answers questions about products/pricing
    6. Moves prospect forward (meeting, quote, next step)
    7. Handles "not ready yet" gracefully
    8. Logs follow-up outcome to Firestore
    """
    
    def __init__(self, context=None):
        """
        Initialize the Follow-Up agent.
        
        Args:
            context: Dictionary with previous interaction details
                - account_name: Organization name
                - contact_name: Person's name
                - previous_contact: Type of previous interaction (email, quote, demo)
                - email_topic: Subject of previous email
                - email_sent_date: When material was sent
                - previous_pain_points: Array of pain points discussed
        """
        super().__init__(name="follow-up-agent")
        
        # Store context
        self.context = context or {}
        
        # Configure agent personality and behavior
        self.prompt_add_section(
            "Role",
            """You are Paul, a warm and professional assistant calling on behalf of 
            Samson from Fortinet. You're following up after a previous conversation or 
            email exchange. Your tone should be conversational, not pushy - you're 
            checking in to help, not to force a sale."""
        )
        
        self.prompt_add_section(
            "Task",
            f"""You're following up with {self.context.get('contact_name', 'the contact')} 
            about {self.context.get('email_topic', 'voice modernization')}.
            
            When they answer:
            1. Greet them warmly: "Hi {self.context.get('contact_name', '[name]')}, this is Paul from Fortinet."
            2. Reference the previous interaction: "I sent you an email {self.context.get('email_sent_date', 'last week')} about {self.context.get('email_topic', 'our conversation')}."
            3. Ask if they got a chance to review it: "Did you get a chance to look at it?"
            4. Based on their response:
               - If YES: "Great! What did you think? Any questions I can answer?"
               - If NO: "No worries, inboxes are crazy. Quick summary: [brief pitch based on their previous pain points]."
               - If MAYBE: "I understand. Is there something different I can send that would be more relevant?"
            5. Answer any questions they have (use get_product_info function if needed)
            6. Move them forward: "Would it be worth a 15-minute call to explore your options?"
            7. If they agree, offer to schedule: "Perfect! Let me check availability..."
            8. If they're not ready: "I completely understand. When would be a better time to check back in?"
            9. Log the outcome using save_follow_up_result function
            
            Keep the conversation under 2-3 minutes. Be helpful, not pushy."""
        )
        
        self.prompt_add_section(
            "Guidelines",
            """- Reference specific details from the previous interaction to show you remember them
            - If they mention a pain point (cost, reliability, features), acknowledge it and offer a solution
            - If they ask technical questions, be honest about what you know vs. what requires a technical expert
            - If they're genuinely not interested, respect that: "I appreciate your time. If anything changes, feel free to reach out."
            - If they ask about pricing, provide ranges but emphasize that a quote requires a quick assessment call
            - Always offer value (information, insights, resources) before asking for the meeting
            - Use their name naturally in conversation (but not too much)
            - Mirror their energy level - if they're busy, be brief; if they're chatty, engage more"""
        )
        
        self.prompt_add_section(
            "Context Memory",
            f"""Previous interaction details:
            - Organization: {self.context.get('account_name', 'Unknown')}
            - Contact: {self.context.get('contact_name', 'Unknown')}
            - Previous contact type: {self.context.get('previous_contact', 'email')}
            - Email topic: {self.context.get('email_topic', 'voice modernization')}
            - Sent date: {self.context.get('email_sent_date', 'recently')}
            - Pain points discussed: {', '.join(self.context.get('previous_pain_points', ['system reliability']))}
            - Account type: {self.context.get('account_type', 'school district')}
            """
        )
        
        # Configure voice settings
        self.add_language(
            name="English",
            code="en-US",
            voice="en-US-Neural2-J"  # Professional male voice
        )
        
        # Initialize Firestore client
        self.db = firestore.Client(project=PROJECT_ID)
    
    @AgentBase.tool(description="Retrieve previous interaction details from the database")
    def get_previous_interaction(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Fetch details about the previous interaction with this contact.
        
        Args:
            args: Dictionary containing:
                - phone_number (str): Phone number to lookup
                - account_name (str, optional): Organization name
        """
        phone_number = args.get("phone_number", "")
        account_name = args.get("account_name", "")
        
        try:
            # Query contacts collection
            collection = self.db.collection(CONTACTS_COLLECTION)
            
            # Try phone number first
            if phone_number:
                query = collection.where("phone_number", "==", phone_number).limit(1)
                results = list(query.stream())
            # Fall back to account name
            elif account_name:
                query = collection.where("account_name", "==", account_name).limit(1)
                results = list(query.stream())
            else:
                return SwaigFunctionResult("No search criteria provided", success=False)
            
            if results:
                doc = results[0].to_dict()
                summary = f"""Previous interaction found:
                - Contact: {doc.get('contact_name', 'Unknown')}
                - Organization: {doc.get('account_name', 'Unknown')}
                - Last contact: {doc.get('last_contact_date', 'Unknown')}
                - Status: {doc.get('status', 'Unknown')}
                - Pain points: {', '.join(doc.get('pain_points', []))}
                - Notes: {doc.get('notes', 'None')}
                """
                return SwaigFunctionResult(summary)
            else:
                return SwaigFunctionResult("No previous interaction found for this contact.")
                
        except Exception as e:
            return SwaigFunctionResult(f"Could not retrieve previous interaction: {str(e)}", success=False)
    
    @AgentBase.tool(description="Get information about Fortinet products, pricing, or features")
    def get_product_info(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Retrieve product information to answer customer questions.
        
        Args:
            args: Dictionary containing:
                - topic (str): What they're asking about (pricing, features, comparison, etc.)
                - specific_product (str, optional): Specific product name
        """
        topic = args.get("topic", "general")
        product = args.get("specific_product", "")
        
        # Knowledge base (simplified for demo)
        knowledge = {
            "pricing": """Fortinet voice solutions pricing varies based on:
            - Number of users (typically $20-40/user/month for cloud)
            - Hardware requirements (if on-prem)
            - Support level (standard vs. premium)
            - Contract length (1-3 years)
            
            To get an accurate quote, we need to understand your specific requirements.
            A 15-minute call with our partner can get you exact pricing.""",
            
            "features": """Key features of Fortinet voice solutions:
            - Local survivability (phones work even if internet is down)
            - Advanced call routing and auto-attendant
            - Mobile app for remote workers
            - Integration with Microsoft Teams
            - E911 support with location tracking
            - Call analytics and reporting
            - Unified communications (voice, video, chat)""",
            
            "survivability": """Local survivability means your phone system keeps working 
            even when your internet connection goes down. We install a local gateway that 
            caches your configuration and handles calls during outages. This is critical 
            for schools and government offices that need 911 access 24/7.""",
            
            "vs_teams": """Fortinet voice integrates with Microsoft Teams but adds:
            - Local survivability (Teams alone fails when internet is down)
            - Better call quality with QoS
            - True E911 with location tracking
            - Cheaper per-user cost for large deployments
            - Support for traditional desk phones
            - More advanced call center features""",
            
            "implementation": """Typical implementation takes 4-6 weeks:
            - Week 1-2: Site survey and design
            - Week 3-4: Equipment deployment
            - Week 5: Configuration and testing
            - Week 6: Training and cutover
            
            We can do phased rollouts for multi-site deployments."""
        }
        
        # Try to match topic
        info = knowledge.get(topic.lower(), None)
        
        if info:
            return SwaigFunctionResult(info)
        else:
            return SwaigFunctionResult(
                f"I don't have specific information about {topic} in my knowledge base. "
                "This would be a great question for our technical specialist on a call. "
                "Would you like me to schedule a brief call to get you detailed answers?"
            )
    
    @AgentBase.tool(description="Schedule a follow-up meeting or callback")
    def schedule_meeting(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Schedule a meeting or callback with the prospect.
        
        Args:
            args: Dictionary containing:
                - meeting_type (str): "technical_call", "demo", "quote_review", "callback"
                - time_preference (str, optional): When they prefer (morning, afternoon, specific date)
                - urgency (str): "urgent", "this_week", "next_week", "flexible"
        """
        meeting_type = args.get("meeting_type", "technical_call")
        time_pref = args.get("time_preference", "flexible")
        urgency = args.get("urgency", "flexible")
        
        # In production, this would integrate with actual calendar API
        response_map = {
            "technical_call": f"""Perfect! I'll schedule a 30-minute technical call.
            Preference: {time_pref}
            I'll send you a calendar invite with our partner from High Point Networks.
            You'll receive it at the email we have on file.
            They'll be prepared to answer all your technical questions and provide exact pricing.""",
            
            "demo": f"""Excellent! I'll set up a 45-minute demo.
            Preference: {time_pref}
            Our team will show you the system in action and tailor it to your environment.
            You'll receive a calendar invite shortly.""",
            
            "quote_review": f"""Great! I'll schedule a 20-minute quote review call.
            Preference: {time_pref}
            We'll walk through the proposal line by line and answer any questions.
            Calendar invite coming your way.""",
            
            "callback": f"""No problem! I'll call you back {time_pref}.
            I'll set a reminder to follow up then.
            In the meantime, feel free to reach out if you think of any questions."""
        }
        
        response = response_map.get(meeting_type, "I'll get that scheduled for you.")
        return SwaigFunctionResult(response)
    
    @AgentBase.tool(description="Log the outcome of the follow-up call to Firestore")
    def save_follow_up_result(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Save the follow-up call outcome to Firestore.
        
        Args:
            args: Dictionary containing:
                - outcome (str): "interested_meeting_booked", "interested_needs_time", 
                                "not_interested", "callback_scheduled", "opted_out"
                - interest_level (int): 1-10 scale
                - next_action (str): What happens next
                - notes (str): Any important details from the conversation
        """
        outcome = args.get("outcome", "unknown")
        interest_level = args.get("interest_level", 5)
        next_action = args.get("next_action", "")
        notes = args.get("notes", "")
        
        # Get call metadata from raw_data if available
        caller_number = raw_data.get("call_from", "") if raw_data else ""
        call_id = raw_data.get("call_id", "") if raw_data else ""
        
        # Prepare document
        doc_data = {
            "account_name": self.context.get("account_name", ""),
            "contact_name": self.context.get("contact_name", ""),
            "phone_number": caller_number or self.context.get("phone_number", ""),
            "call_id": call_id,
            "outcome": outcome,
            "interest_level": interest_level,
            "next_action": next_action,
            "notes": notes,
            "previous_contact_type": self.context.get("previous_contact", ""),
            "email_topic": self.context.get("email_topic", ""),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "created_at": datetime.utcnow().isoformat(),
            "source": "follow-up-agent",
            "call_duration_seconds": raw_data.get("duration", 0) if raw_data else 0
        }
        
        try:
            # Save to Firestore
            collection = self.db.collection(FIRESTORE_COLLECTION)
            doc_ref = collection.add(doc_data)
            
            result_message = f"Follow-up logged: {outcome} (interest level: {interest_level}/10)"
            print(f"✅ {result_message}")
            print(f"   Account: {self.context.get('account_name', 'Unknown')}")
            print(f"   Next action: {next_action}")
            print(f"   Document ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to save follow-up result: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message, success=False)
    
    @AgentBase.tool(description="Update Salesforce with follow-up call results")
    def update_salesforce(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Update Salesforce with the follow-up call outcome.
        
        Args:
            args: Dictionary containing:
                - lead_id (str): Salesforce Lead ID
                - status (str): New lead status
                - task_description (str): Description for the follow-up task
                - next_follow_up_date (str, optional): When to follow up next
        """
        lead_id = args.get("lead_id", "")
        status = args.get("status", "")
        task_description = args.get("task_description", "")
        next_follow_up = args.get("next_follow_up_date", "")
        
        # In production, this would use Salesforce API
        # For now, we'll simulate the response
        
        if not lead_id:
            # Try to look up lead by account name
            account = self.context.get("account_name", "")
            if account:
                lead_id = f"[LOOKED_UP_FROM_{account}]"
        
        result = f"""Salesforce updated:
        - Lead ID: {lead_id or 'Unknown'}
        - Status: {status}
        - Task: {task_description}
        - Next follow-up: {next_follow_up or 'Not scheduled'}
        
        (Note: In production, this would make actual Salesforce API calls)
        """
        
        print(f"📊 Salesforce update simulated for {self.context.get('account_name', 'Unknown')}")
        return SwaigFunctionResult(result)


def main():
    """
    Start the Follow-Up agent server.
    Listens on port 3001 for incoming SignalWire requests.
    
    Context should be passed as environment variables or config file:
    - ACCOUNT_NAME
    - CONTACT_NAME
    - PREVIOUS_CONTACT (email, quote, demo)
    - EMAIL_TOPIC
    - EMAIL_SENT_DATE
    - PREVIOUS_PAIN_POINTS (comma-separated)
    """
    print("="*70)
    print("🤖 Follow-Up Agent Starting")
    print("="*70)
    
    # Load context from environment or config
    context = {
        "account_name": os.getenv("ACCOUNT_NAME", "Phoenix Union HSD"),
        "contact_name": os.getenv("CONTACT_NAME", "John"),
        "previous_contact": os.getenv("PREVIOUS_CONTACT", "email"),
        "email_topic": os.getenv("EMAIL_TOPIC", "voice modernization and local survivability"),
        "email_sent_date": os.getenv("EMAIL_SENT_DATE", "last week"),
        "previous_pain_points": os.getenv("PREVIOUS_PAIN_POINTS", "aging infrastructure,internet dependency").split(","),
        "account_type": os.getenv("ACCOUNT_TYPE", "school district"),
        "phone_number": os.getenv("PHONE_NUMBER", "")
    }
    
    print("\nContext:")
    print(f"  Account: {context['account_name']}")
    print(f"  Contact: {context['contact_name']}")
    print(f"  Previous: {context['previous_contact']} about {context['email_topic']}")
    print(f"  Sent: {context['email_sent_date']}")
    print(f"  Pain points: {', '.join(context['previous_pain_points'])}")
    
    print("\nThis agent will:")
    print("  1. Reference the previous interaction")
    print("  2. Check if they reviewed the material")
    print("  3. Gauge interest level")
    print("  4. Answer questions")
    print("  5. Move them forward in the sales cycle")
    print("  6. Log outcome to Firestore")
    
    print("\nAgent is ready to receive calls!")
    print(f"\nConnect your SignalWire number to: http://YOUR_PUBLIC_URL:3001/")
    print("="*70)
    
    agent = FollowUpAgent(context=context)
    agent.run(host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()
