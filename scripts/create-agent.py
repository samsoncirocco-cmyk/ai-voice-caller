#!/usr/bin/env python3
"""
Create Dialogflow CX Agent for Fortinet SLED Voice Caller
"""
import os
import json
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx
from google.api_core import exceptions

PROJECT_ID = "tatt-pro"
LOCATION = "us-central1"
AGENT_DISPLAY_NAME = "Fortinet-SLED-Caller"
TIME_ZONE = "America/Phoenix"
DEFAULT_LANGUAGE = "en"

def create_agent():
    """Create a Dialogflow CX agent with speech and logging enabled."""
    
    # Initialize client
    client = dialogflow_cx.AgentsClient(
        client_options={"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    )
    
    # Parent location for the agent
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    
    print(f"Creating agent '{AGENT_DISPLAY_NAME}' in {parent}...")
    
    # Configure agent with speech settings
    agent = dialogflow_cx.Agent(
        display_name=AGENT_DISPLAY_NAME,
        default_language_code=DEFAULT_LANGUAGE,
        time_zone=TIME_ZONE,
        enable_stackdriver_logging=True,
        enable_spell_correction=True,
        speech_to_text_settings=dialogflow_cx.SpeechToTextSettings(
            enable_speech_adaptation=True
        ),
    )
    
    try:
        # Create the agent
        response = client.create_agent(parent=parent, agent=agent)
        
        agent_name = response.name
        agent_id = agent_name.split("/")[-1]
        
        print(f"✓ Agent created successfully!")
        print(f"  Resource Name: {agent_name}")
        print(f"  Agent ID: {agent_id}")
        print(f"  Display Name: {response.display_name}")
        print(f"  Language: {response.default_language_code}")
        print(f"  Time Zone: {response.time_zone}")
        
        # Save agent details to config
        config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
        os.makedirs(config_dir, exist_ok=True)
        
        # Save agent name to text file
        agent_name_file = os.path.join(config_dir, "agent-name.txt")
        with open(agent_name_file, "w") as f:
            f.write(agent_name)
        print(f"✓ Agent name saved to: {agent_name_file}")
        
        # Save full agent details to JSON
        agent_config = {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "project_id": PROJECT_ID,
            "location": LOCATION,
            "display_name": response.display_name,
            "default_language_code": response.default_language_code,
            "time_zone": response.time_zone,
            "console_url": f"https://dialogflow.cloud.google.com/cx/{PROJECT_ID}/locations/{LOCATION}/agents/{agent_id}",
        }
        
        agent_config_file = os.path.join(config_dir, "dialogflow-agent.json")
        with open(agent_config_file, "w") as f:
            json.dump(agent_config, f, indent=2)
        print(f"✓ Agent config saved to: {agent_config_file}")
        
        print(f"\n🌐 View in console:")
        print(f"   {agent_config['console_url']}")
        
        return agent_name
        
    except exceptions.AlreadyExists:
        print(f"⚠ Agent '{AGENT_DISPLAY_NAME}' already exists in {LOCATION}")
        print("Searching for existing agent...")
        
        # List agents to find existing one
        request = dialogflow_cx.ListAgentsRequest(parent=parent)
        agents = client.list_agents(request=request)
        
        for agent in agents:
            if agent.display_name == AGENT_DISPLAY_NAME:
                print(f"✓ Found existing agent: {agent.name}")
                
                # Save to config files
                config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
                os.makedirs(config_dir, exist_ok=True)
                
                agent_name_file = os.path.join(config_dir, "agent-name.txt")
                with open(agent_name_file, "w") as f:
                    f.write(agent.name)
                
                agent_id = agent.name.split("/")[-1]
                agent_config = {
                    "agent_name": agent.name,
                    "agent_id": agent_id,
                    "project_id": PROJECT_ID,
                    "location": LOCATION,
                    "display_name": agent.display_name,
                    "default_language_code": agent.default_language_code,
                    "time_zone": agent.time_zone,
                    "console_url": f"https://dialogflow.cloud.google.com/cx/{PROJECT_ID}/locations/{LOCATION}/agents/{agent_id}",
                }
                
                agent_config_file = os.path.join(config_dir, "dialogflow-agent.json")
                with open(agent_config_file, "w") as f:
                    json.dump(agent_config, f, indent=2)
                
                return agent.name
        
        raise Exception("Agent exists but couldn't be found in listing")
        
    except Exception as e:
        print(f"✗ Error creating agent: {e}")
        raise

if __name__ == "__main__":
    try:
        agent_name = create_agent()
        print(f"\n✅ Success! Agent is ready: {agent_name}")
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        exit(1)
