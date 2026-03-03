#!/usr/bin/env python3
"""
AI Voice Agent using SignalWire Agents SDK
This creates a proper conversational AI agent, not just TTS playback
"""
import os
import sys
import json
import logging
from signalwire_agents import AgentBase
from signalwire_agents.core.function_result import SwaigFunctionResult
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("ai_voice_agent")

class FortinedVoiceAgent(AgentBase):
    """
    Fortinet Discovery Mode AI Agent
    
    This agent can:
    - Have natural conversations (real AI, not scripted)
    - Listen and respond to user speech
    - Ask for IT contact information
    - Handle objections naturally
    """
    
    def __init__(self):
        super().__init__(
            name="fortinet-discovery",
            route="/agent",
            host="0.0.0.0",
            port=3000,
            use_pom=True
        )
        
        # Configure AI personality and behavior
        self.setPersonality(
            "You are Paul, a friendly and professional sales representative "
            "from Fortinet. You're calling on behalf of Fortinet to gather "
            "IT decision-maker contact information for cybersecurity solutions."
        )
        
        self.setGoal(
            "Identify and collect the name and direct phone number of the "
            "person who handles IT and cybersecurity decisions at the organization."
        )
        
        self.setInstructions([
            "Introduce yourself as Paul from Fortinet",
            "Be brief and respectful of the person's time",
            "Ask who handles IT or cybersecurity at the organization",
            "Ask for their direct phone number",
            "If they ask what this is about, mention cybersecurity solutions and network security",
            "If they're not interested, politely thank them and end the call",
            "If you get the information, confirm it back to them and thank them",
            "Keep responses under 3 sentences unless asked for more detail"
        ])
        
        # Configure AI parameters for natural conversation
        self.set_params({
            "ai_model": "gpt-4.1-nano",  # Fast, efficient model
            "wait_for_user": False,  # Start speaking immediately after answer
            "end_of_speech_timeout": 1500,  # 1.5 seconds of silence before responding
            "ai_volume": 8,  # Clear, audible volume
            "local_tz": "America/Phoenix"
        })
        
        # Use a natural-sounding voice (Rime voices sound better than Polly)
        self.add_language(
            name="English",
            code="en-US",
            voice="rime.spore",  # Natural male voice
            speech_fillers=["Let me think...", "Hmm..."],
            function_fillers=["One moment...", "Let me note that down..."]
        )
        
        # Add hints for better recognition
        self.add_hints([
            "Fortinet",
            "cybersecurity", 
            "IT department",
            "information technology"
        ])
        
        # Enable SIP routing
        self.enable_sip_routing(auto_map=True)
        
        logger.info("✅ Fortinet AI Agent initialized")
        logger.info("   Name: Paul from Fortinet")
        logger.info("   Purpose: IT contact discovery")
        logger.info("   Voice: Rime Spore (natural male voice)")
    
    def setPersonality(self, text):
        self.prompt_add_section("Personality", body=text)
        return self
    
    def setGoal(self, text):
        self.prompt_add_section("Goal", body=text)
        return self
    
    def setInstructions(self, items):
        self.prompt_add_section("Instructions", bullets=items)
        return self
    
    @AgentBase.tool(
        name="save_contact_info",
        description="Save the IT contact's name and phone number",
        parameters={
            "contact_name": {
                "type": "string",
                "description": "The name of the IT decision maker"
            },
            "phone_number": {
                "type": "string",
                "description": "Their direct phone number"
            }
        }
    )
    def save_contact_info(self, args, raw_data):
        """Save IT contact information"""
        name = args.get("contact_name", "Unknown")
        phone = args.get("phone_number", "Unknown")
        
        logger.info(f"📝 IT Contact captured:")
        logger.info(f"   Name: {name}")
        logger.info(f"   Phone: {phone}")
        
        # In production, this would save to Firestore/database
        # For now, just log it
        
        return SwaigFunctionResult(
            f"Got it! I have {name} at {phone}. I'll make sure our team "
            f"reaches out to them about Fortinet's cybersecurity solutions. "
            f"Thanks so much for your help!"
        )

if __name__ == "__main__":
    agent = FortinedVoiceAgent()
    
    # Get auth credentials
    username, password, source = agent.get_basic_auth_credentials(include_source=True)
    
    print("=" * 70)
    print("🤖 FORTINET AI VOICE AGENT")
    print("=" * 70)
    print(f"\n✅ Agent running at: http://localhost:3000/agent")
    print(f"🔐 Auth: {username}:{password}")
    print(f"\n📞 This agent can:")
    print("   - Have natural AI conversations (not scripted)")
    print("   - Listen and respond intelligently")
    print("   - Gather IT contact information")
    print("   - Handle objections gracefully")
    print(f"\n🎯 Press Ctrl+C to stop\n")
    print("=" * 70)
    
    try:
        agent.run()
    except KeyboardInterrupt:
        print("\n\n👋 Agent stopped")
        sys.exit(0)
