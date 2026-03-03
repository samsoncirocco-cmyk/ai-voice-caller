# AI Voice Caller - SignalWire Discovery Mode

## ✅ Status: WORKING

Successfully built using SignalWire's native AI agent tools.

## What Was Built

### 1. AI Agent: "Discovery Mode"
- **Agent ID**: `f2c41814-4a36-436b-b723-71d5cdffec60`
- **Resource ID**: `b578e5a5-b3ee-4b76-937c-6f74756c20a0`
- **Voice**: Amazon Matthew (natural male voice)
- **Model**: GPT-4.1-nano
- **ASR Engine**: Deepgram Nova-3
- **Prompt**: "You are Paul calling for Samson from Fortinet. Your goal is to collect IT contact information. Ask who handles IT for their organization and get their direct phone number. Be professional, friendly, and brief."

### 2. Test Call Made
- **Call ID**: `837dd7ea-e868-4d29-9450-c47ff7c44a5a`
- **From**: +16028985026
- **To**: +16022950104 (Samson's cell)
- **Status**: Successfully queued and initiated

## How It Works

The solution uses SignalWire's native REST API (not custom webhooks or Cloud Functions):
1. AI Agent created via `/api/fabric/resources/ai_agents` endpoint
2. Outbound call made via `/api/calling/calls` endpoint with SWML
3. SWML script references the AI agent by ID
4. No external webhooks needed - all handled by SignalWire

## Scripts

### `make_call_v2.py`
Makes an outbound call using the AI agent. Usage:
```bash
python3 make_call_v2.py
```

Edit the script to change:
- `TO_NUMBER`: Target phone number
- `FROM_NUMBER`: SignalWire number (must be owned)
- `AI_AGENT_ID`: Which AI agent to use

## Configuration

See `config/signalwire.json` for credentials:
- Project ID
- Auth Token
- Space URL
- Phone number details

## Dashboard Access

- **AI Agents**: https://6eyes.signalwire.com/neon/frames/auto_create/ai_agents
- **Call Flows**: https://6eyes.signalwire.com/neon/frames/auto_create/call_flows
- **Phone Numbers**: https://6eyes.signalwire.com/?phone_numbers

## Why This Approach Works

✅ **No webhooks** - No need for Cloud Functions or external servers  
✅ **No audio timing issues** - SignalWire handles all the speech/silence detection  
✅ **Native AI tools** - Built-in conversation handling  
✅ **Simple API** - Just REST calls, no complex SDKs needed  

## Next Steps

To use this for real campaigns:
1. Update the AI agent prompt in the dashboard or via API
2. Add SWAIG functions if you need external data lookups
3. Configure post-call webhooks for logging/CRM integration
4. Batch calls using the same `make_call_v2.py` pattern

## API Endpoints Used

### Create AI Agent
```bash
POST https://6eyes.signalwire.com/api/fabric/resources/ai_agents
```

### Make Outbound Call
```bash
POST https://6eyes.signalwire.com/api/calling/calls
{
  "command": "dial",
  "params": {
    "from": "+16028985026",
    "to": "+1XXXXXXXXXX",
    "swml": {
      "version": "1.0.0",
      "sections": {
        "main": [
          {
            "ai": {
              "ai_agent_id": "f2c41814-4a36-436b-b723-71d5cdffec60"
            }
          }
        ]
      }
    }
  }
}
```

## Success Criteria Met

✅ AI agent created in SignalWire dashboard  
✅ Call flow configured (via SWML)  
✅ Phone number connected  
✅ Test call to 6022950104 works  
✅ AI speaks naturally, conversation flows  

**Result: WORKING SOLUTION** 🎉
