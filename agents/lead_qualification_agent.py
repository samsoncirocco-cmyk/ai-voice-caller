#!/usr/bin/env python3
"""
Lead Qualification Agent - BANT-based lead scoring and routing
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
FIRESTORE_COLLECTION = "qualified-leads"
SALESFORCE_OPPORTUNITY_THRESHOLD = 60  # Score threshold for auto-creating opportunity

# Lead Score Thresholds
HOT_LEAD_SCORE = 70  # Book meeting immediately
WARM_LEAD_SCORE = 40  # Send info, schedule follow-up
# Below WARM_LEAD_SCORE = Cold lead (nurture campaign)


class LeadQualificationAgent(AgentBase):
    """
    Lead Qualification agent that uses BANT criteria to score leads.
    
    BANT Scoring:
    - Budget (0-25 points): E-Rate eligible, budget authority, current spend
    - Authority (0-20 points): Decision maker, influencer, or gatekeeper
    - Need (0-30 points): Pain points, urgency, current system limitations
    - Timeline (0-25 points): Buying window, contract renewal, project timeline
    
    Conversation flow:
    1. Introduction and permission to qualify
    2. Current system discovery (Need assessment)
    3. User count and scale (Budget indicator)
    4. Timeline and buying window (Timeline)
    5. Pain points and challenges (Need)
    6. Authority check (Authority)
    7. Score calculation and routing
    8. Hot leads → Book meeting
    9. Warm leads → Send info
    10. Cold leads → Graceful exit + nurture
    """
    
    def __init__(self):
        super().__init__(name="lead-qualification")
        
        # Configure agent personality
        self.prompt_add_section(
            "Role",
            """You are Paul, a consultative and friendly assistant calling on behalf of 
            Samson from Fortinet. Your goal is to understand the prospect's situation through 
            natural conversation, not interrogation. You're helping them discover whether 
            modernizing their voice infrastructure makes sense for their organization."""
        )
        
        self.prompt_add_section(
            "Discovery Questions",
            """Ask these questions naturally, one at a time, in conversation flow:
            
            1. Current System: "What phone system are you using today?"
               - Listen for: vendor name, age, on-prem vs cloud, pain points
               - Follow-up: "How long have you had that system?"
            
            2. Scale: "How many phone users do you have across all locations?"
               - Listen for: size (impacts budget), multi-site (complexity)
            
            3. Timeline: "Are you planning any changes to your voice system in the next 6-12 months?"
               - Listen for: contract renewal, budget cycle, active project
               - Follow-up: "When does your current contract renew?"
            
            4. Pain Points: "What's the biggest challenge with your current setup?"
               - Listen for: reliability, cost, features, support, survivability
               - Follow-up: "What would you fix if you could?"
            
            5. Budget/Authority: "Are you involved in the decision-making for voice infrastructure?"
               - Listen for: decision maker, influencer, recommender
               - For K-12: "Do you typically use E-Rate funding for voice projects?"
            
            Keep it conversational. If they volunteer information, skip that question."""
        )
        
        self.prompt_add_section(
            "Buying Signals",
            """Watch for these HIGH-VALUE signals (add 5+ points each):
            - "We're actively looking"
            - "Contract expires soon" (within 6 months)
            - "We're having problems with..."
            - "We need to modernize"
            - "What would this cost?"
            - "Do you have a case study?"
            
            Watch for DISQUALIFIERS (immediate graceful exit):
            - "Just renewed a 3-year contract"
            - "No budget at all"
            - "Not my area" (and can't refer to right person)
            - "Stop calling" (opt-out)"""
        )
        
        self.prompt_add_section(
            "Qualification Principles",
            """- Be consultative, not pushy
            - Listen more than you talk
            - Acknowledge their situation
            - If they're not qualified, exit gracefully
            - If they're qualified, create urgency naturally
            - Always offer value (info, insights, case studies)
            - Respect their time (keep under 5 minutes)"""
        )
        
        self.prompt_add_section(
            "Routing Logic",
            """After gathering information, call score_lead() to calculate BANT score.
            
            Then route based on score:
            - 70+ points (Hot): "Based on what you've shared, I think there's a strong fit. 
              Would you be open to a 15-minute call with our technical team this week?"
            
            - 40-69 points (Warm): "This could be a fit. Let me send you some information 
              about [relevant solution]. What's your email?"
            
            - Below 40 (Cold): "I appreciate your time. It sounds like the timing might not 
              be right. Would it be okay if I checked back in 6 months?"
            
            After routing, call create_salesforce_opp() for hot leads (70+)."""
        )
        
        # Configure languages (optional - defaults to en-US)
        # Voice settings are configured in SignalWire dashboard/SWML
        # self.set_languages(["en-US"])
        
        # Initialize Firestore client
        self.db = firestore.Client(project=PROJECT_ID)
    
    @AgentBase.tool(
        description="""Calculate lead score based on BANT criteria. Call this after gathering 
        discovery information. Returns qualification level (hot/warm/cold) and score."""
    )
    def score_lead(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Calculate BANT-based lead score.
        
        Args:
            args: Dictionary containing:
                - current_system (str): Phone system vendor/type
                - system_age (int): Years since deployment
                - user_count (int): Number of phone users
                - timeline (str): Buying timeline (within_3_months, within_6_months, 
                  within_12_months, no_plans)
                - pain_points (list): List of pain points mentioned
                - decision_authority (str): decision_maker, influencer, or gatekeeper
                - erate_eligible (bool): For K-12, uses E-Rate funding
                - contract_renewal_date (str): Date contract renews (optional)
        
        Returns:
            SwaigFunctionResult with score and qualification level
        """
        score = 0
        scoring_details = []
        
        # NEED ASSESSMENT (0-30 points)
        pain_points = args.get("pain_points", [])
        score += min(len(pain_points) * 5, 15)  # 5 points per pain point, max 15
        if pain_points:
            scoring_details.append(f"Pain points identified: {len(pain_points)} (+{min(len(pain_points) * 5, 15)})")
        
        system_age = args.get("system_age", 0)
        if system_age >= 7:
            score += 10
            scoring_details.append(f"System age: {system_age} years (+10)")
        elif system_age >= 5:
            score += 5
            scoring_details.append(f"System age: {system_age} years (+5)")
        
        current_system = args.get("current_system", "").lower()
        legacy_systems = ["cisco", "avaya", "nortel", "nec", "mitel", "shoretel"]
        if any(vendor in current_system for vendor in legacy_systems):
            score += 5
            scoring_details.append(f"Legacy system: {current_system} (+5)")
        
        # TIMELINE ASSESSMENT (0-25 points)
        timeline = args.get("timeline", "").lower()
        timeline_scores = {
            "within_3_months": 25,
            "active_project": 25,
            "within_6_months": 20,
            "within_12_months": 10,
            "next_year": 5,
            "no_plans": 0
        }
        timeline_score = timeline_scores.get(timeline, 0)
        score += timeline_score
        if timeline_score > 0:
            scoring_details.append(f"Timeline: {timeline} (+{timeline_score})")
        
        # BUDGET ASSESSMENT (0-25 points)
        user_count = args.get("user_count", 0)
        if user_count >= 500:
            score += 15
            scoring_details.append(f"User count: {user_count} (Enterprise) (+15)")
        elif user_count >= 100:
            score += 10
            scoring_details.append(f"User count: {user_count} (Large) (+10)")
        elif user_count >= 25:
            score += 5
            scoring_details.append(f"User count: {user_count} (Medium) (+5)")
        
        erate_eligible = args.get("erate_eligible", False)
        if erate_eligible:
            score += 10
            scoring_details.append("E-Rate eligible (+10)")
        
        # AUTHORITY ASSESSMENT (0-20 points)
        decision_authority = args.get("decision_authority", "").lower()
        authority_scores = {
            "decision_maker": 20,
            "influencer": 10,
            "recommender": 10,
            "gatekeeper": 0
        }
        authority_score = authority_scores.get(decision_authority, 5)
        score += authority_score
        if authority_score > 0:
            scoring_details.append(f"Authority: {decision_authority} (+{authority_score})")
        
        # Determine qualification level
        if score >= HOT_LEAD_SCORE:
            qualification = "hot"
            action = "book_meeting"
        elif score >= WARM_LEAD_SCORE:
            qualification = "warm"
            action = "send_info"
        else:
            qualification = "cold"
            action = "nurture"
        
        result = {
            "score": score,
            "qualification": qualification,
            "action": action,
            "scoring_details": scoring_details
        }
        
        # Store in session for logging
        if raw_data:
            raw_data["lead_score"] = score
            raw_data["qualification"] = qualification
        
        result_message = f"Lead Score: {score}/100 ({qualification.upper()})\n"
        result_message += "\n".join(scoring_details)
        result_message += f"\n\nRecommended Action: {action}"
        
        # Store result in session context (if raw_data provided)
        if raw_data:
            raw_data.update(result)
        
        print(f"✅ Lead Scored: {score}/100 ({qualification})")
        
        return SwaigFunctionResult(result_message)
    
    @AgentBase.tool(
        description="""Create a Salesforce opportunity for hot leads. Call this after booking 
        a meeting with a qualified lead (score 70+)."""
    )
    def create_salesforce_opp(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Create a Salesforce opportunity for qualified leads.
        
        Args:
            args: Dictionary containing:
                - account_name (str): Organization name
                - contact_name (str): Contact person name
                - contact_phone (str): Contact phone number
                - contact_email (str): Contact email
                - opportunity_name (str): Opportunity description
                - lead_score (int): Calculated BANT score
                - pain_points (list): Identified pain points
                - timeline (str): Buying timeline
                - current_system (str): Current phone system
                - user_count (int): Number of users
        
        Returns:
            SwaigFunctionResult with opportunity ID
        """
        # In production, this would call Salesforce API
        # For now, we'll log to Firestore and create a placeholder
        
        account_name = args.get("account_name", "Unknown Organization")
        contact_name = args.get("contact_name", "Unknown Contact")
        lead_score = args.get("lead_score", 0)
        
        opp_data = {
            "account_name": account_name,
            "contact_name": contact_name,
            "contact_phone": args.get("contact_phone", ""),
            "contact_email": args.get("contact_email", ""),
            "opportunity_name": args.get("opportunity_name", f"Voice Modernization - {account_name}"),
            "lead_score": lead_score,
            "stage": "Qualification",
            "pain_points": args.get("pain_points", []),
            "timeline": args.get("timeline", ""),
            "current_system": args.get("current_system", ""),
            "user_count": args.get("user_count", 0),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "lead-qualification-agent",
            "source": "ai_voice_caller",
            "next_step": "Schedule technical discovery call"
        }
        
        try:
            # Save to Firestore
            collection = self.db.collection("salesforce-opportunities")
            doc_ref = collection.add(opp_data)
            
            result_message = f"Opportunity created: {opp_data['opportunity_name']}"
            result_message += f"\nAccount: {account_name}"
            result_message += f"\nContact: {contact_name}"
            result_message += f"\nScore: {lead_score}/100"
            result_message += f"\nFirestore Doc ID: {doc_ref[1].id}"
            
            print(f"✅ Salesforce Opportunity Created")
            print(f"   {opp_data['opportunity_name']}")
            print(f"   Score: {lead_score}/100")
            print(f"   Doc ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to create opportunity: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message)
    
    @AgentBase.tool(
        description="""Route qualified lead to Samson for immediate follow-up. Use for hot 
        leads (70+ score) who need human touch."""
    )
    def route_to_sales(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Route hot lead to sales team (Samson).
        
        Args:
            args: Dictionary containing:
                - account_name (str): Organization name
                - contact_name (str): Contact person
                - contact_phone (str): Contact phone
                - lead_score (int): BANT score
                - urgency (str): high, medium, low
                - notes (str): Key points from conversation
        
        Returns:
            SwaigFunctionResult with routing confirmation
        """
        account_name = args.get("account_name", "Unknown")
        contact_name = args.get("contact_name", "Unknown")
        lead_score = args.get("lead_score", 0)
        urgency = args.get("urgency", "medium")
        notes = args.get("notes", "")
        
        routing_data = {
            "account_name": account_name,
            "contact_name": contact_name,
            "contact_phone": args.get("contact_phone", ""),
            "lead_score": lead_score,
            "urgency": urgency,
            "notes": notes,
            "routed_at": datetime.utcnow().isoformat(),
            "routed_to": "samson",
            "status": "pending_contact",
            "source": "lead-qualification-agent"
        }
        
        try:
            # Save to Firestore hot-leads collection
            collection = self.db.collection("hot-leads")
            doc_ref = collection.add(routing_data)
            
            # TODO: In production, trigger notification to Samson (email, SMS, Telegram)
            
            result_message = f"Hot lead routed to Samson"
            result_message += f"\nAccount: {account_name}"
            result_message += f"\nContact: {contact_name}"
            result_message += f"\nScore: {lead_score}/100"
            result_message += f"\nUrgency: {urgency.upper()}"
            
            print(f"🔥 HOT LEAD ROUTED TO SAMSON")
            print(f"   {account_name} - {contact_name}")
            print(f"   Score: {lead_score}/100")
            print(f"   Urgency: {urgency}")
            print(f"   Doc ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to route lead: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message)
    
    @AgentBase.tool(
        description="""Log qualified lead to database with full conversation context and 
        BANT scores. Call at end of qualification conversation."""
    )
    def log_qualified_lead(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Log qualified lead with full context to Firestore.
        
        Args:
            args: Dictionary containing full lead qualification data
        
        Returns:
            SwaigFunctionResult with confirmation
        """
        lead_data = {
            "account_name": args.get("account_name", ""),
            "contact_name": args.get("contact_name", ""),
            "contact_phone": args.get("contact_phone", ""),
            "contact_email": args.get("contact_email", ""),
            "current_system": args.get("current_system", ""),
            "system_age": args.get("system_age", 0),
            "user_count": args.get("user_count", 0),
            "pain_points": args.get("pain_points", []),
            "timeline": args.get("timeline", ""),
            "decision_authority": args.get("decision_authority", ""),
            "erate_eligible": args.get("erate_eligible", False),
            "lead_score": args.get("lead_score", 0),
            "qualification": args.get("qualification", ""),
            "call_outcome": args.get("call_outcome", ""),
            "next_action": args.get("next_action", ""),
            "logged_at": firestore.SERVER_TIMESTAMP,
            "created_at": datetime.utcnow().isoformat(),
            "source": "lead-qualification-agent"
        }
        
        try:
            collection = self.db.collection(FIRESTORE_COLLECTION)
            doc_ref = collection.add(lead_data)
            
            result_message = f"Lead logged: {lead_data['account_name']}"
            result_message += f"\nContact: {lead_data['contact_name']}"
            result_message += f"\nScore: {lead_data['lead_score']}/100"
            result_message += f"\nQualification: {lead_data['qualification']}"
            
            print(f"✅ Lead Logged to Firestore")
            print(f"   {lead_data['account_name']}")
            print(f"   Score: {lead_data['lead_score']}/100")
            print(f"   Doc ID: {doc_ref[1].id}")
            
            return SwaigFunctionResult(result_message)
            
        except Exception as e:
            error_message = f"Failed to log lead: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(error_message)
    
    @AgentBase.tool(
        description="""Handle disqualification gracefully when lead doesn't meet criteria. 
        Offers to stay in touch or check back later."""
    )
    def disqualify_lead(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Gracefully disqualify a lead and offer future follow-up.
        
        Args:
            args: Dictionary containing:
                - reason (str): Disqualification reason
                - contact_name (str): Contact name
                - follow_up_timeline (str): When to check back (optional)
        
        Returns:
            SwaigFunctionResult with graceful exit message
        """
        reason = args.get("reason", "not_qualified")
        contact_name = args.get("contact_name", "")
        follow_up = args.get("follow_up_timeline", "6_months")
        
        # Map reasons to graceful responses
        responses = {
            "just_renewed": f"I appreciate your time, {contact_name}. It sounds like you're locked in for a while. Would it be okay if I checked back when your contract is up for renewal?",
            
            "no_budget": f"I understand budget constraints. {contact_name}, would it be helpful if I sent you some information for when budget planning opens up?",
            
            "wrong_person": f"Thanks for your time, {contact_name}. Can you point me to who handles voice infrastructure decisions?",
            
            "no_need": f"That makes sense, {contact_name}. If voice modernization ever comes up, feel free to reach out. Can I check back in 6 months just in case anything changes?",
            
            "not_decision_maker": f"I appreciate the context, {contact_name}. Who should I speak with about voice infrastructure decisions?",
            
            "not_qualified": f"Thanks for your time, {contact_name}. If your situation changes, don't hesitate to reach out. Have a great day!"
        }
        
        response = responses.get(reason, responses["not_qualified"])
        
        # Log disqualification
        disqual_data = {
            "contact_name": contact_name,
            "reason": reason,
            "follow_up_timeline": follow_up,
            "disqualified_at": datetime.utcnow().isoformat(),
            "source": "lead-qualification-agent"
        }
        
        try:
            collection = self.db.collection("disqualified-leads")
            collection.add(disqual_data)
            print(f"📋 Lead Disqualified: {reason}")
        except Exception as e:
            print(f"⚠️  Failed to log disqualification: {str(e)}")
        
        return SwaigFunctionResult(response)


def main():
    """
    Start the Lead Qualification agent server.
    Listens on port 3001 for incoming SignalWire requests.
    """
    print("="*70)
    print("🎯 Lead Qualification Agent Starting")
    print("="*70)
    print("\nThis agent will:")
    print("  1. Conduct BANT-based discovery conversations")
    print("  2. Score leads (Budget, Authority, Need, Timeline)")
    print("  3. Route qualified leads appropriately:")
    print("     - Hot leads (70+): Book meeting")
    print("     - Warm leads (40-69): Send info")
    print("     - Cold leads (<40): Graceful exit + nurture")
    print("  4. Log all interactions to Firestore")
    print("  5. Create Salesforce opportunities for hot leads")
    print("\nAgent is ready to qualify leads!")
    print(f"\nConnect your SignalWire number to: http://YOUR_PUBLIC_URL:3001/")
    print("="*70)
    
    agent = LeadQualificationAgent()
    agent.run(host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()
