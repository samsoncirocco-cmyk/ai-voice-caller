#!/usr/bin/env python3
"""
Update SignalWire Native AI Agent with humanized prompt
"""
import json
import requests

CONFIG_FILE = "/home/samson/.openclaw/workspace/projects/ai-voice-caller/config/signalwire.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def update_agent_prompt():
    config = load_config()
    
    project_id = config['project_id']
    auth_token = config['auth_token']
    space_url = config['space_url']
    agent_id = config['ai_agent']['agent_id']
    new_prompt = config['ai_agent']['prompt']
    
    print(f"🔧 Updating AI Agent prompt...")
    print(f"   Agent ID: {agent_id}")
    print(f"   Space: {space_url}")
    
    # SignalWire AI Agents API endpoint
    api_url = f"https://{space_url}/api/fabric/resources/{agent_id}"
    
    # Update payload
    payload = {
        "prompt": {
            "text": new_prompt
        }
    }
    
    try:
        response = requests.patch(
            api_url,
            auth=(project_id, auth_token),
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code in [200, 201, 204]:
            print(f"\n✅ Agent prompt updated successfully!")
            print(f"\n📝 New prompt (first 200 chars):")
            print(f"   {new_prompt[:200]}...")
            print(f"\n🎯 Key improvements:")
            print(f"   ✓ Warm and conversational tone")
            print(f"   ✓ Gratitude for picking up")
            print(f"   ✓ Acknowledges cold call")
            print(f"   ✓ Natural language patterns")
            print(f"   ✓ Humble and helpful approach")
            print(f"\n🧪 Ready to test:")
            print(f"   python3 scripts/test-native-ai-agent.py 6022950104")
            return True
        else:
            print(f"\n❌ Update failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
            # Try alternative endpoint (AI Agents might use different API)
            print(f"\n🔄 Trying alternative API endpoint...")
            alt_url = f"https://{space_url}/api/relay/rest/ai/agents/{agent_id}"
            
            response2 = requests.put(
                alt_url,
                auth=(project_id, auth_token),
                json={"prompt": new_prompt},
                headers={"Content-Type": "application/json"}
            )
            
            if response2.status_code in [200, 201, 204]:
                print(f"✅ Success via alternative endpoint!")
                return True
            else:
                print(f"❌ Also failed: {response2.status_code}")
                print(f"   Response: {response2.text}")
                print(f"\n💡 Manual update required:")
                print(f"   1. Go to: https://{space_url}/ai_agents")
                print(f"   2. Click on 'Discovery Mode' agent")
                print(f"   3. Update the prompt with the new text from config/signalwire.json")
                return False
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"🤖 UPDATING AI AGENT PROMPT")
    print(f"{'='*70}\n")
    
    success = update_agent_prompt()
    
    if success:
        print(f"\n{'='*70}")
        print(f"✅ AGENT UPDATED - READY FOR TESTING")
        print(f"{'='*70}")
    else:
        print(f"\n{'='*70}")
        print(f"⚠️  MANUAL UPDATE NEEDED")
        print(f"{'='*70}")
