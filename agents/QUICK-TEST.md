# Quick Test Guide - Cold Call Agent

## Start the Agent

```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
source venv/bin/activate
python3 agents/cold_call_agent.py
```

**Expected Output:**
```
======================================================================
☎️  Cold Call Agent Starting
======================================================================

This agent will:
  1. Greet prospects professionally
  2. Qualify interest in Fortinet solutions (SASE, OT Security, AI Security)
  3. Handle objections and competitive mentions
  4. Schedule follow-ups or send information
  5. Log all outcomes to Firestore

Target call duration: < 3 minutes
Voice: en-US-Neural2-J (Professional male)

SWAIG Functions:
  - save_lead: Log call outcome
  - schedule_callback: Schedule follow-up call
  - send_info_email: Queue follow-up email

Connect your SignalWire number to: http://YOUR_PUBLIC_URL:3001/
======================================================================
```

## Verify Agent is Running

```bash
curl -s http://localhost:3001/ | head -20
```

Should return SignalWire webhook response or agent info.

## Check Firestore Collections

```bash
# Query recent leads
gcloud firestore documents list \
  --collection-path=cold-call-leads \
  --project=tatt-pro \
  --limit=5

# Query callbacks
gcloud firestore documents list \
  --collection-path=callbacks \
  --project=tatt-pro \
  --limit=5

# Query email queue
gcloud firestore documents list \
  --collection-path=email-queue \
  --project=tatt-pro \
  --limit=5
```

## Connect to SignalWire

1. Go to: https://6eyes.signalwire.com/dashboard
2. Click on Phone Numbers
3. Click on: +1 (602) 898-5026
4. Under "Voice Settings" → "When a call comes in"
5. Set webhook URL to: `http://YOUR_PUBLIC_URL:3001/`
6. Save changes

## Make a Test Call

**Call:** +1 (602) 898-5026

**Expected Flow:**
1. Agent: "Hi, is this [YOUR_NAME]?"
2. You: "Yes"
3. Agent: "This is Paul from Fortinet... Do you have 2 minutes?"
4. You: "Sure"
5. Agent: "Quick question: what happens to your phones when the internet goes down?"
6. You: [Answer to test qualification]

**Test Scenarios:**

### Scenario 1: Interested Prospect
- Say: "They go down too, we have no backup"
- Agent should identify pain point and offer meeting
- Say: "Yes" to meeting
- Agent should attempt to schedule

### Scenario 2: Send Info
- Say: "Can you send me some information?"
- Agent should ask for email
- Provide email address
- Agent should confirm and queue email

### Scenario 3: Not Interested
- Say: "Not interested right now"
- Agent should probe timing vs. fit
- Say: "Not a fit at all"
- Agent should politely end call and log

### Scenario 4: Competitor Mention
- Say: "We use Cisco/Teams/RingCentral"
- Agent should acknowledge and differentiate
- Watch for competitive positioning

### Scenario 5: Wrong Person
- Say: "I'm not the right person"
- Agent should ask who to contact
- Provide a name/number
- Agent should log referral

## Monitor Logs

```bash
# Watch agent logs in real-time
tail -f /tmp/cold-call-agent.log

# Or if running in terminal, watch the output
```

## Verify Data Logged

After test call, check Firestore:

```python
from google.cloud import firestore
db = firestore.Client(project="tatt-pro")

# Get latest lead
leads = db.collection("cold-call-leads").order_by(
    "timestamp", 
    direction=firestore.Query.DESCENDING
).limit(1).stream()

for lead in leads:
    print(lead.to_dict())
```

## Stop the Agent

Press `Ctrl+C` in the terminal running the agent.

## Troubleshooting

**Agent won't start:**
- Check venv is activated: `which python3` should show venv path
- Check dependencies: `pip list | grep signalwire-agents`

**No response from webhook:**
- Check port 3001 is accessible: `netstat -tuln | grep 3001`
- Check firewall allows inbound connections
- Verify SignalWire webhook URL matches your public IP/domain

**Firestore errors:**
- Check auth: `gcloud auth application-default print-access-token`
- Check project: `gcloud config get-value project` (should be tatt-pro)

**Agent not understanding:**
- Check logs for confidence scores
- May need to adjust prompt sections
- Test with clear, simple responses first

## Production Deployment

Once testing is successful, deploy with PM2:

```bash
pm2 start agents/cold_call_agent.py \
  --name cold-call-agent \
  --interpreter python3 \
  --cwd /home/samson/.openclaw/workspace/projects/ai-voice-caller

pm2 save
pm2 startup  # Configure to start on boot
```

## Monitoring Production

```bash
# Check agent status
pm2 status cold-call-agent

# View logs
pm2 logs cold-call-agent

# Restart if needed
pm2 restart cold-call-agent

# Stop
pm2 stop cold-call-agent
```

---

**Quick Reference:**
- Agent Port: 3001
- Voice: en-US-Neural2-J
- Project: tatt-pro
- Phone: +1 (602) 898-5026
- SignalWire: https://6eyes.signalwire.com
- Firestore: cold-call-leads, callbacks, email-queue
