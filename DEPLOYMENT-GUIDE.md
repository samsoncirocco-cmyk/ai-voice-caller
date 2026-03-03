# Dialogflow CX + SignalWire Deployment Guide

**Status:** Ready to Deploy ✅  
**Estimated Time:** 15 minutes  
**Date:** 2026-02-11

---

## 🎯 What We're Building

A working AI voice calling system that:
- Makes outbound calls via SignalWire
- Uses Dialogflow CX for natural conversation
- Follows the Discovery Mode flow to collect IT contact info
- Logs everything to Firestore

**Architecture:**
```
SignalWire Phone Number (+1 602-898-5026)
  ↓
Cloud Function Webhook (dialogflowWebhook)
  ↓
Dialogflow CX Agent (Fortinet-SLED-Caller)
  ↓
Discovery Mode Flow
  ↓
Response back through webhook to SignalWire
```

---

## ✅ Prerequisites (Already Done)

- ✅ Google Cloud project: `tatt-pro`
- ✅ APIs enabled: Dialogflow CX, Cloud Functions, Firestore
- ✅ Dialogflow CX agent created: `35ba664e-b443-4b8e-bf60-b9c445b31273`
- ✅ Discovery Mode flow built and deployed
- ✅ SignalWire account configured
- ✅ Phone number purchased: +1 (602) 898-5026

---

## 📦 Step 1: Deploy the Webhook

The webhook bridges SignalWire calls to Dialogflow CX.

```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller/webhook
bash deploy.sh
```

**Expected output:**
```
🚀 Deploying SignalWire ↔ Dialogflow CX webhook...

Deploying function (may take a while - up to 2 minutes)...
✅ Deployment complete!

Webhook URL:
https://us-central1-tatt-pro.cloudfunctions.net/dialogflowWebhook
```

**What this does:**
- Deploys Node.js Cloud Function (2nd gen)
- Sets up HTTP trigger (publicly accessible)
- Configures 512MB memory, 60s timeout
- Returns webhook URL for SignalWire configuration

**Time:** ~2 minutes

---

## 📞 Step 2: Configure SignalWire

Connect your SignalWire phone number to the webhook.

### Option A: Manual (SignalWire Dashboard)

1. Go to https://6eyes.signalwire.com/phone_numbers
2. Click on phone number: **+1 (602) 898-5026**
3. Scroll to **"Voice & Fax"** section
4. Under **"A Call Comes In"**:
   - Select: **Webhook**
   - URL: `https://us-central1-tatt-pro.cloudfunctions.net/dialogflowWebhook`
   - Method: **POST**
   - Fallback: Leave empty
5. Click **Save**

### Option B: API (Automated)

```bash
python3 scripts/configure-signalwire.py
```

**Time:** ~2 minutes

---

## 🧪 Step 3: Test the Integration

Make a test call to verify everything works.

```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
python3 scripts/make-dialogflow-call.py 6022950104
```

**Expected flow:**

1. **Call connects** → Your phone rings
2. **Answer the call**
3. **AI speaks:** "Hi, this is Paul from Fortinet. I'm trying to reach the person who handles IT and cybersecurity. Who would that be?"
4. **You respond:** "That's me" or "That would be John Smith"
5. **AI continues:** "Great! What's the best phone number to reach you?"
6. **You respond:** "602-555-1234"
7. **AI confirms:** "So I have John Smith at 602-555-1234. Is that correct?"
8. **You confirm:** "Yes"
9. **AI ends:** "Perfect! Someone from Fortinet will follow up soon. Have a great day!"
10. **Call ends**

**Monitor the call:**

```bash
# View Cloud Function logs (real-time)
gcloud functions logs read dialogflowWebhook --region=us-central1 --limit=50

# Check Firestore (active calls)
gcloud firestore collections list
gcloud firestore export --collection-ids=active_calls

# Or use Firebase Console
# https://console.firebase.google.com/project/tatt-pro/firestore
```

**Time:** ~3 minutes

---

## 📊 Step 4: Verify Results

Check that data was captured correctly.

### Check Firestore

**Active calls (while call is in progress):**
```bash
gcloud firestore documents list active_calls --limit=5
```

**Completed calls:**
```bash
gcloud firestore documents list completed_calls --limit=5
```

**Conversation logs:**
```bash
gcloud firestore documents list conversation_logs --limit=10
```

### View in Firebase Console

1. Go to https://console.firebase.google.com/project/tatt-pro/firestore
2. Collections:
   - `active_calls` — Ongoing conversations
   - `completed_calls` — Call history
   - `conversation_logs` — Turn-by-turn transcripts

**Time:** ~2 minutes

---

## 🎉 Success Criteria

Your system is working if:

- ✅ Test call connects and AI speaks
- ✅ AI responds naturally to your input
- ✅ Conversation follows Discovery Mode flow
- ✅ Call completes successfully
- ✅ Data logged to Firestore
- ✅ No errors in Cloud Function logs

---

## 🐛 Troubleshooting

### Call doesn't connect

**Symptom:** Call fails immediately or doesn't ring.

**Check:**
```bash
# Test SignalWire credentials
python3 scripts/test-signalwire-auth.py

# Test phone number
python3 scripts/make-test-call.py 6022950104
```

**Fix:** Verify SignalWire config in `config/signalwire.json`

---

### AI doesn't speak

**Symptom:** Call connects but silent, or immediate hangup.

**Check:**
```bash
# View webhook logs
gcloud functions logs read dialogflowWebhook --region=us-central1 --limit=20
```

**Likely causes:**
1. Webhook not configured in SignalWire
2. Dialogflow agent not accessible
3. Cloud Function permissions issue

**Fix:**
```bash
# Test Dialogflow directly
gcloud dialogflow cx agents describe 35ba664e-b443-4b8e-bf60-b9c445b31273 \
  --location=us-central1

# Redeploy webhook
cd webhook && bash deploy.sh
```

---

### Speech not recognized

**Symptom:** AI says "I didn't catch that" repeatedly.

**Check webhook logs for speech transcription:**
```bash
gcloud functions logs read dialogflowWebhook --region=us-central1 --limit=50 | grep SpeechResult
```

**Likely causes:**
1. SignalWire speech settings incorrect
2. Background noise on call
3. Speaking too quietly

**Fix:**
- Speak clearly and loudly
- Reduce background noise
- Check webhook uses `speechModel="phone_call"` and `enhanced="true"`

---

### Conversation doesn't flow

**Symptom:** AI responses don't make sense or seem random.

**Check Dialogflow flow:**
```bash
# View Discovery Mode flow
cat config/discovery-mode-flow.json
```

**Likely cause:** Flow pages not connected properly.

**Fix:** Rebuild Discovery Mode flow:
```bash
python3 scripts/create-discovery-flow.py
```

---

### Session state lost

**Symptom:** AI forgets what was said in previous turns.

**Check Firestore:**
```bash
gcloud firestore documents list active_calls
```

**Likely cause:** Session not being stored/retrieved from Firestore.

**Fix:** Check webhook has Firestore permissions:
```bash
# Grant Firestore access to Cloud Function service account
gcloud projects add-iam-policy-binding tatt-pro \
  --member=serviceAccount:tatt-pro@appspot.gserviceaccount.com \
  --role=roles/datastore.user
```

---

## 📈 Next Steps

Once the basic system is working:

### 1. Scale Testing

Test with more phone numbers:
```bash
# Create a batch test
python3 scripts/batch-call.py --list data/test-numbers.csv --limit 10
```

### 2. Build More Flows

Expand beyond Discovery Mode:
```bash
# Cold Calling flow
python3 scripts/create-cold-calling-flow.py

# Appointment Setting flow
python3 scripts/create-appointment-setting-flow.py

# Lead Qualification flow
python3 scripts/create-lead-qualification-flow.py
```

### 3. Add Integrations

Connect to external systems:
- **Salesforce:** Create tasks after calls
- **Google Calendar:** Book meetings
- **Email:** Send follow-up emails

Deploy integration webhooks:
```bash
cd cloud-functions/salesforce-task && gcloud functions deploy ...
cd cloud-functions/calendar-booking && gcloud functions deploy ...
```

### 4. Analytics & Monitoring

Set up dashboards:
- Call success rate
- Average conversation length
- Discovery data captured per call
- Lead quality scores

### 5. Production Readiness

Before scaling to 100+ calls:
- [ ] Set up monitoring alerts
- [ ] Configure error notifications
- [ ] Implement retry logic
- [ ] Add rate limiting
- [ ] Set up backup phone numbers
- [ ] Test failover scenarios

---

## 💰 Cost Tracking

**Expected costs for testing (10 calls):**
- SignalWire: ~$0.30 (10 calls × $0.01/min × 3 min)
- Dialogflow CX: ~$0.20 (10 calls × 10 turns × $0.002)
- Cloud Functions: ~$0.01 (negligible)
- Firestore: ~$0.01 (negligible)

**Total:** ~$0.50 for 10 test calls

**Projected costs at scale (1,000 calls/month):**
- SignalWire: ~$30
- Dialogflow CX: ~$20
- Cloud Functions: ~$1
- Firestore: ~$1

**Total:** ~$52/month for 1,000 calls

---

## 📚 Documentation

- **Technical Spec:** `TECHNICAL-SPEC.md` — Complete system architecture
- **Integration Spec:** `INTEGRATION-SPEC.md` — SignalWire + Dialogflow details
- **Webhook README:** `webhook/README.md` — Cloud Function documentation
- **Build Log:** `BUILD.md` — What's been built so far

---

## 🎯 Quick Commands Reference

```bash
# Deploy webhook
cd webhook && bash deploy.sh

# Make test call
python3 scripts/make-dialogflow-call.py 6022950104

# View logs
gcloud functions logs read dialogflowWebhook --region=us-central1 --limit=50

# Check Firestore
gcloud firestore collections list

# Redeploy after changes
cd webhook && bash deploy.sh

# Test SignalWire connection
python3 scripts/test-signalwire-auth.py

# Monitor call status
python3 scripts/check-call-status.py <CALL_SID>
```

---

## ✅ Deployment Checklist

- [ ] Webhook deployed successfully
- [ ] SignalWire phone number configured
- [ ] Test call completed end-to-end
- [ ] AI conversation flows naturally
- [ ] Data logged to Firestore
- [ ] No errors in logs
- [ ] Discovery Mode flow works correctly
- [ ] Ready for more testing

**Once all checkboxes are complete, you're ready to scale! 🚀**

---

**Need help?** Check the troubleshooting section or review logs:
```bash
gcloud functions logs read dialogflowWebhook --region=us-central1
```
