#!/usr/bin/env python3
"""
Cold Call Agent - Qualifies prospects for Fortinet solutions
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
FIRESTORE_COLLECTION = "cold-call-leads"


class ColdCallAgent(AgentBase):
    """
    Cold Call agent that qualifies interest in Fortinet solutions.
    
    Conversation flow:
    1. Greets prospect professionally
    2. Asks killer question about phone survivability
    3. Qualifies interest in Fortinet solutions (Unified SASE, OT Security, AI-Driven Security)
    4. Handles objections (not interested, send info, too expensive)
    5. Pivots based on pain points
    6. Attempts to schedule follow-up or demo
    7. Logs outcome to Firestore
    
    Target call duration: < 3 minutes
    """
    
    def __init__(self):
        super().__init__(name="cold-call-agent")
        
        # Configure agent personality and behavior
        self.prompt_add_section(
            "Role",
            """You are Paul, a knowledgeable and professional solutions consultant 
            calling on behalf of Fortinet. You specialize in helping IT leaders in 
            education and local government modernize their voice and security infrastructure.
            
            You are NOT pushy or aggressive. You're genuinely curious about their challenges
            and focused on finding solutions that fit their needs."""
        )
        
        self.prompt_add_section(
            "Primary Task",
            """Your goal is to qualify the prospect's interest in Fortinet solutions through
            a brief, value-focused conversation:
            
            1. GREETING: "Hi, this is Paul from Fortinet. Is this [CONTACT_NAME]?"
            2. CONFIRM TIME: "Do you have 2 minutes for a quick question about your voice systems?"
            3. KILLER QUESTION: "Quick question: what happens to your phones when the internet goes down?"
            4. QUALIFY INTEREST: Based on their answer, explore pain points:
               - No survivability → "That's a common gap. Most organizations lose 911 capability during outages."
               - Have failover → "Smart. Are you happy with that setup, or is it something you'd improve?"
               - Don't know → "That's actually why I'm calling. We help ensure voice reliability."
            5. PIVOT TO SOLUTION: "We're helping [ACCOUNT_TYPE] in [STATE] with three main areas:
               - Unified SASE (secure network access for hybrid work)
               - OT Security (protecting critical infrastructure)
               - AI-Driven Security (automated threat detection)
               Based on what you shared, [RELEVANT_AREA] might be a fit."
            6. SCHEDULE OR SEND INFO: "Would you be open to a 15-minute call with our partner 
               High Point Networks? They can show you exactly how this works."
            
            Keep the call under 3 minutes. Be consultative, not salesy."""
        )
        
        self.prompt_add_section(
            "Handling Objections",
            """You will encounter objections. Handle them professionally:
            
            "Not interested":
            → "I understand. Can I ask – is it not a fit right now, or not a fit at all?
               Just so I know whether to check back when your situation changes."
            
            "Send me info":
            → "Happy to. What specifically would be most helpful? A case study from a 
               [ACCOUNT_TYPE] like yours, or a quick overview of [RELEVANT_SOLUTION]?"
            
            "Too expensive":
            → "I hear you. Are you in budget planning for next year? We've helped 
               districts get E-Rate funding for these projects. Worth exploring?"
            
            "Already have a vendor":
            → "Got it. Who are you working with? [If Cisco/Palo Alto/etc.] 
               A lot of our customers started there. What we're doing differently is [VALUE_PROP].
               Would it be worth a comparison?"
            
            "Busy right now":
            → "Totally understand. This will be quick – 60 seconds. When your internet goes down,
               do your phones still work?" (Then proceed with qualification)
            
            "Wrong person":
            → "I apologize. Who would be the right person to talk to about voice systems?"
               (Use save_lead to capture referral)
            
            If they're still resistant after 2 objections, respect their time and offer to
            follow up later using schedule_callback."""
        )
        
        self.prompt_add_section(
            "Competitive Intelligence",
            """When prospects mention competitors, acknowledge and differentiate:
            
            Cisco/Webex:
            → "Cisco is solid. What we're seeing is organizations moving away from on-prem 
               UCM to cloud solutions with better failover. Have you looked at that?"
            
            Microsoft Teams:
            → "Teams is great for collaboration. Where we come in is ensuring it stays up 
               during outages and integrates with physical security systems. Is that a gap?"
            
            RingCentral/8x8/Vonage:
            → "Those are good voice providers. What we add is the security layer – 
               protecting the network, not just the phone system. Are you handling that separately?"
            
            Palo Alto Networks:
            → "Palo Alto has strong firewalls. Where Fortinet differs is the unified approach –
               SASE, SD-WAN, and security in one platform. Are you managing multiple vendors now?"
            
            Always position Fortinet as complementary or superior, never dismissive."""
        )
        
        self.prompt_add_section(
            "Success Metrics",
            """You are successful when:
            1. Meeting scheduled → HIGHEST VALUE (use schedule_callback)
            2. Qualified interest + info sent → HIGH VALUE (use send_info_email)
            3. Callback scheduled for later → MEDIUM VALUE (use schedule_callback)
            4. Referral to right person → MEDIUM VALUE (use save_lead)
            5. Not interested but respectful → LOW VALUE (still log with save_lead)
            
            Always use the appropriate SWAIG function to log the outcome before ending the call.
            
            If you sense genuine interest, push for the meeting. If they need info first, 
            get their email and send it immediately. If they're busy, schedule a specific 
            callback time rather than "I'll call later."""
        )
        
        self.prompt_add_section(
            "Conversation Guidelines",
            """- Keep sentences short and conversational
            - Use natural pauses (the SSML will add appropriate breaks)
            - Mirror their communication style (formal vs casual)
            - If they ask a complex question you're unsure about, be honest: 
              "That's a great question. Let me connect you with our technical team who can 
              walk through that in detail."
            - Never make up features or capabilities
            - If they say "call back later" without a specific time, nail down a time:
              "Happy to. What day and time works best? I want to make sure I catch you."
            - Always confirm email addresses by repeating them back
            - End every call with a clear next step"""
        )
        
        # Configure voice and language settings
        self.add_language("English", "en-US", "en-US-Neural2-J")  # Professional male voice
        self.set_param("voice", "en-US-Neural2-J")
        
        # Initialize Firestore client
        self.db = firestore.Client(project=PROJECT_ID)
    
    @AgentBase.tool(description="Save lead information and call outcome to the database")
    def save_lead(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Save lead information and call outcome to Firestore.
        
        Args:
            args: Dictionary containing:
                - contact_name (str): Name of the contact
                - outcome (str): Call outcome (qualified|not_interested|callback_requested|referral)
                - interest_level (str, optional): Interest level (hot|warm|cold)
                - pain_points (list, optional): List of pain points mentioned
                - current_system (str, optional): Current phone/security system
                - competitor_mentioned (str, optional): Competitor mentioned
                - notes (str, optional): Additional notes
        """
        contact_name = args.get("contact_name", "")
        outcome = args.get("outcome", "unknown")
        interest_level = args.get("interest_level", "unknown")
        pain_points = args.get("pain_points", [])
        current_system = args.get("current_system", "")
        competitor_mentioned = args.get("competitor_mentioned", "")
        notes = args.get("notes", "")
        
        # Get call metadata from raw_data if available
        caller_number = raw_data.get("call_from", "") if raw_data else ""
        call_id = raw_data.get("call_id", "") if raw_data else ""
        
        # Prepare document
        doc_data = {
            "contact_name": contact_name,
            "outcome": outcome,
            "interest_level": interest_level,
            "pain_points": pain_points if isinstance(pain_points, list) else [pain_points],
            "current_system": current_system,
            "competitor_mentioned": competitor_mentioned,
            "notes": notes,
            "phone_number": caller_number,
            "call_id": call_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "created_at": datetime.utcnow().isoformat(),
            "source": "cold-call-agent",
            "status": "new",
            "follow_up_required": outcome in ["qualified", "callback_requested"]
        }
        
        try:
            # Save to Firestore
            collection = self.db.collection(FIRESTORE_COLLECTION)
            doc_ref = collection.add(doc_data)
            
            result_message = f"Lead saved: {contact_name} - {outcome} ({interest_level})"
            print(f"✅ {result_message}")
            print(f"   Document ID: {doc_ref[1].id}")
            print(f"   Pain points: {', '.join(pain_points) if pain_points else 'None'}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to save lead: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message, success=False)
    
    @AgentBase.tool(description="Schedule a callback for a specific date and time")
    def schedule_callback(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Schedule a callback and create a task in Firestore.
        
        Args:
            args: Dictionary containing:
                - contact_name (str): Name of the contact
                - callback_datetime (str): Requested callback date/time (ISO format or natural language)
                - reason (str, optional): Reason for callback
                - phone_number (str, optional): Callback phone number
        """
        contact_name = args.get("contact_name", "")
        callback_datetime_str = args.get("callback_datetime", "")
        reason = args.get("reason", "Follow-up on Fortinet solutions")
        phone_number = args.get("phone_number", "")
        
        # Get call metadata from raw_data if available
        caller_number = raw_data.get("call_from", "") if raw_data else ""
        if not phone_number:
            phone_number = caller_number
        
        # Parse callback datetime (simplified - can be enhanced)
        try:
            # Try to parse ISO format first
            callback_datetime = datetime.fromisoformat(callback_datetime_str.replace('Z', '+00:00'))
        except:
            # Fallback: schedule for next business day at 10 AM
            callback_datetime = datetime.utcnow() + timedelta(days=1)
            callback_datetime = callback_datetime.replace(hour=17, minute=0, second=0, microsecond=0)  # 10 AM MST = 17:00 UTC
        
        # Prepare document
        doc_data = {
            "contact_name": contact_name,
            "phone_number": phone_number,
            "callback_datetime": callback_datetime.isoformat(),
            "reason": reason,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "source": "cold-call-agent",
            "type": "callback_task"
        }
        
        try:
            # Save to Firestore callbacks collection
            collection = self.db.collection("callbacks")
            doc_ref = collection.add(doc_data)
            
            # Also save to leads collection
            self.save_lead({
                "contact_name": contact_name,
                "outcome": "callback_requested",
                "interest_level": "warm",
                "notes": f"Callback scheduled for {callback_datetime.strftime('%Y-%m-%d %H:%M')}: {reason}"
            }, raw_data)
            
            result_message = f"Callback scheduled: {contact_name} on {callback_datetime.strftime('%Y-%m-%d at %I:%M %p')}"
            print(f"✅ {result_message}")
            print(f"   Task ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to schedule callback: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message, success=False)
    
    @AgentBase.tool(description="Send follow-up information to the prospect via email")
    def send_info_email(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Queue an email to be sent to the prospect with requested information.
        
        Args:
            args: Dictionary containing:
                - contact_name (str): Name of the contact
                - email (str): Email address
                - info_type (str): Type of information requested (case_study|overview|technical|demo)
                - specific_topic (str, optional): Specific topic (SASE|OT_Security|AI_Security|voice_modernization)
        """
        contact_name = args.get("contact_name", "")
        email = args.get("email", "")
        info_type = args.get("info_type", "overview")
        specific_topic = args.get("specific_topic", "")
        
        # Get call metadata
        caller_number = raw_data.get("call_from", "") if raw_data else ""
        
        # Prepare document
        doc_data = {
            "contact_name": contact_name,
            "email": email,
            "info_type": info_type,
            "specific_topic": specific_topic,
            "phone_number": caller_number,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "source": "cold-call-agent",
            "type": "email_task"
        }
        
        try:
            # Save to Firestore email queue collection
            collection = self.db.collection("email-queue")
            doc_ref = collection.add(doc_data)
            
            # Also save to leads collection
            self.save_lead({
                "contact_name": contact_name,
                "outcome": "info_requested",
                "interest_level": "warm",
                "notes": f"Requested {info_type} about {specific_topic or 'general solutions'} at {email}"
            }, raw_data)
            
            result_message = f"Email queued: {info_type} to {email}"
            print(f"✅ {result_message}")
            print(f"   Email task ID: {doc_ref[1].id}")
            print(f"   Topic: {specific_topic or 'General'}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to queue email: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message, success=False)


def main():
    """
    Start the Cold Call agent server.
    Listens on port 3001 for incoming SignalWire requests.
    """
    print("="*70)
    print("☎️  Cold Call Agent Starting")
    print("="*70)
    print("\nThis agent will:")
    print("  1. Greet prospects professionally")
    print("  2. Qualify interest in Fortinet solutions (SASE, OT Security, AI Security)")
    print("  3. Handle objections and competitive mentions")
    print("  4. Schedule follow-ups or send information")
    print("  5. Log all outcomes to Firestore")
    print("\nTarget call duration: < 3 minutes")
    print("Voice: en-US-Neural2-J (Professional male)")
    print("\nSWAIG Functions:")
    print("  - save_lead: Log call outcome")
    print("  - schedule_callback: Schedule follow-up call")
    print("  - send_info_email: Queue follow-up email")
    print(f"\nConnect your SignalWire number to: http://YOUR_PUBLIC_URL:3001/")
    print("="*70)
    
    agent = ColdCallAgent()
    agent.run(host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()
