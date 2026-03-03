# SignalWire AI Agent Deployment - LIVE NOW

**Date:** 2026-02-11 07:15 MST  
**Status:** ✅ Agent Running & Exposed

---

## Current Setup

### Discovery Agent (RUNNING)
- **Local:** http://localhost:3000/
- **Public URL:** https://310295e3d6a69b.lhr.life/
- **Status:** ✅ LIVE
- **Process PID:** 639875
- **Auth:** Required (SignalWire will use HTTP Basic Auth)

---

## Next Steps to Complete Integration

### Step 1: Configure SignalWire Phone Number

1. **Log in to SignalWire Dashboard:**
   ```
   https://6eyes.signalwire.com/dashboard
   ```

2. **Go to Phone Numbers:**
   - Click "Phone Numbers" in left sidebar
   - Select your number: +1 (602) 898-5026

3. **Configure Incoming Calls:**
   ```
   Handle calls using: LaML Webhooks
   
   When a call comes in:
   Request URL: https://310295e3d6a69b.lhr.life/
   Method: POST
   
   (No auth needed - agent handles it internally)
   ```

4. **Save Configuration**

---

### Step 2: Make Test Call

After configuring SignalWire:

```bash
# Call the SignalWire number from your phone
# Dial: +1 (602) 898-5026

# Or use Python script to make outbound call TO your phone:
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
source venv/bin/activate
python3 scripts/make-outbound-call.py 6022950104
```

---

### Step 3: Verify It Works

**Expected behavior:**
1. Call connects
2. AI agent (Paul) answers
3. "Hi, this is Paul calling for Samson from Fortinet"
4. Asks for IT contact name
5. Asks for direct phone number
6. Confirms information
7. Thanks you and ends call
8. Contact info saved to Firestore

---

## Monitoring

### Check Agent Logs
```bash
tail -f /tmp/agent.log
```

### Check Tunnel Status
```bash
ps aux | grep "localhost.run"
```

### Check SignalWire Call Logs
```
https://6eyes.signalwire.com/dashboard → Call Logs
```

---

## Troubleshooting

### Agent Not Responding
```bash
# Check if agent is running
ps aux | grep discovery_agent

# Restart if needed
kill 639875
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
source venv/bin/activate
python3 agents/discovery_agent.py &
```

### Tunnel Died
```bash
# Restart tunnel
ssh -o StrictHostKeyChecking=no -R 80:localhost:3000 nokey@localhost.run &

# Get new URL
# Update SignalWire webhook URL with new domain
```

### Firestore Not Saving
```bash
# Check Google Cloud credentials
gcloud auth application-default login

# Verify project
gcloud config get-value project
```

---

## Architecture

```
Incoming Call Flow:
1. User dials +1 (602) 898-5026
2. SignalWire receives call
3. SignalWire POST → https://310295e3d6a69b.lhr.life/
4. Tunnel forwards → localhost:3000
5. Discovery Agent (Python) handles request
6. Agent returns SWML (AI configuration)
7. SignalWire's AI talks to caller
8. Agent saves data to Firestore

Outbound Call Flow:
1. Python script calls SignalWire REST API
2. SignalWire makes outbound call
3. When answered, requests SWML from agent
4. Same flow as above (steps 3-8)
```

---

## Files & Processes

| Component | Location | Status |
|-----------|----------|--------|
| Agent Code | `agents/discovery_agent.py` | ✅ Running |
| Process PID | 639875 | ✅ Active |
| Port | 3000 | ✅ Listening |
| Tunnel | localhost.run | ✅ Connected |
| Public URL | https://310295e3d6a69b.lhr.life/ | ✅ Active |
| SignalWire Number | +1 (602) 898-5026 | ⏳ Needs config |
| Firestore | `discovered-contacts` | ✅ Ready |

---

## What's Already Done ✅

- [x] Discovery agent built and tested
- [x] Agent running on port 3000
- [x] Public tunnel established
- [x] SignalWire credentials configured
- [x] Firestore collection ready
- [x] Phone number provisioned

## What's Left ⏳

- [ ] Configure SignalWire webhook (5 minutes)
- [ ] Make test call (1 minute)
- [ ] Verify data saved to Firestore (1 minute)

---

## Quick Test Commands

```bash
# Test agent locally (should return SWML JSON)
curl http://localhost:3000/

# Test via tunnel (should return SWML JSON)
curl https://310295e3d6a69b.lhr.life/

# Check agent is running
lsof -i :3000

# View recent logs
tail -20 /tmp/agent.log

# Monitor live traffic
tail -f /tmp/agent.log
```

---

**Status:** Agent is LIVE and ready. Just needs SignalWire webhook configuration!
