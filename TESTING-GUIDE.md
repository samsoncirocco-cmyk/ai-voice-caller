# Testing Guide - AI Voice Calling System

**Date:** 2026-02-11  
**Status:** Ready for testing

---

## Quick Start

### Test AI Call (Recommended)
```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller
source venv/bin/activate
python3 scripts/make-ai-call.py 6022950104
```

This makes a **real AI call** that can listen and respond naturally.

### Old TwiML Call (For comparison - don't use)
```bash
python3 scripts/make-test-call.py 6022950104
```

This uses the old broken TwiML approach (pre-recorded script, no AI).

---

## What to Expect

### AI Call Behavior

When Samson answers the phone:

1. **Immediate greeting** (no awkward pause)
   - "Hi, this is Paul calling from Fortinet"

2. **Natural conversation**
   - AI will ask about IT contact
   - AI will LISTEN to whatever Samson says
   - AI will RESPOND naturally (not scripted)

3. **Intelligent handling**
   - If Samson asks questions → AI answers them
   - If Samson says "not interested" → AI politely ends call
   - If Samson provides info → AI confirms and thanks

4. **Natural voice**
   - Rime Spore voice (sounds human, not robotic)
   - Proper intonation and rhythm
   - No weird pauses or delays

### What's Different from Before

| Old (TwiML) | New (AI Agent) |
|-------------|----------------|
| 8-second awkward pause | Immediate greeting |
| Robotic Polly voice | Natural Rime voice |
| Pre-recorded script | Real AI conversation |
| Can't listen | Listens and responds |
| Sounds like IVR | Sounds like real person |

---

## Test Scenarios

### Test 1: Basic Call Quality
**Goal:** Verify call connects and voice sounds natural

```bash
python3 scripts/make-ai-call.py 6022950104
```

**Expected:**
- ✅ Call connects within 2-3 seconds
- ✅ Greeting starts immediately (no long pause)
- ✅ Voice sounds natural and clear
- ✅ No robotic/mechanical quality

**Pass criteria:** Voice sounds natural, no technical issues

---

### Test 2: AI Listening
**Goal:** Verify AI can hear and understand responses

**Steps:**
1. Make call: `python3 scripts/make-ai-call.py 6022950104`
2. When AI asks "who handles IT?", say something like:
   - "That would be John Smith"
   - "I'm not sure"
   - "What is this about?"

**Expected:**
- ✅ AI acknowledges what you said (proves it's listening)
- ✅ AI responds appropriately to your answer
- ✅ Conversation feels natural, not scripted

**Pass criteria:** AI demonstrates it heard and understood you

---

### Test 3: Information Gathering
**Goal:** Verify AI can collect contact information

**Steps:**
1. Make call: `python3 scripts/make-ai-call.py 6022950104`
2. Provide fake IT contact info:
   - "Our IT person is Mike Johnson"
   - (When asked) "His number is 602-555-1234"

**Expected:**
- ✅ AI asks for name
- ✅ AI asks for phone number
- ✅ AI confirms back what it heard
- ✅ AI thanks you and ends call professionally

**Pass criteria:** AI successfully gathered and confirmed information

---

### Test 4: Objection Handling
**Goal:** Verify AI handles "not interested" gracefully

**Steps:**
1. Make call: `python3 scripts/make-ai-call.py 6022950104`
2. Say: "I'm not interested" or "Please don't call again"

**Expected:**
- ✅ AI acknowledges the objection
- ✅ AI politely apologizes
- ✅ AI ends call quickly and professionally
- ✅ No arguing or persistence

**Pass criteria:** AI handles rejection professionally

---

### Test 5: Question Handling
**Goal:** Verify AI can answer questions about purpose

**Steps:**
1. Make call: `python3 scripts/make-ai-call.py 6022950104`
2. Ask: "What is this call about?" or "Why are you calling?"

**Expected:**
- ✅ AI explains it's about cybersecurity solutions
- ✅ AI mentions Fortinet products/services
- ✅ AI stays on topic (doesn't hallucinate)
- ✅ Answer is brief and relevant

**Pass criteria:** AI provides sensible answer to question

---

## Troubleshooting

### Call doesn't connect
**Symptom:** Script runs but no call received

**Check:**
1. Phone number format: `python3 scripts/make-ai-call.py +16022950104`
2. SignalWire account status (trial mode restrictions?)
3. Check logs: Look for error messages in output

**Fix:**
- Verify number is correct
- Check SignalWire dashboard for call logs
- Ensure phone can receive calls (not in DND mode)

---

### Voice sounds robotic
**Symptom:** AI voice sounds mechanical/computerized

**Likely cause:** Using wrong script (old TwiML version)

**Fix:**
```bash
# Make sure you're using the AI script, not the old one
python3 scripts/make-ai-call.py 6022950104  # ✅ Correct
python3 scripts/make-test-call.py 6022950104  # ❌ Old version
```

---

### AI doesn't respond to speech
**Symptom:** AI talks but doesn't react to what you say

**Likely cause:**
1. Audio connection issue
2. SWML configuration error
3. Microphone not working

**Fix:**
1. Ensure phone microphone is not muted
2. Check for background noise (AI might not detect speech end)
3. Try speaking clearly and pausing 1-2 seconds

---

### Long delay before speaking
**Symptom:** 5+ second pause after answering

**Likely cause:** Using old TwiML script with manual pause

**Fix:** Use `make-ai-call.py` (not `make-test-call.py`)

---

## Advanced Testing

### Check Call Status
After making a call, you can check its status:

```bash
# Get call ID from output, then:
python3 scripts/check-call-status.py <CALL_ID>
```

### View Call Logs
Check SignalWire dashboard:
1. Go to https://6eyes.signalwire.com/dashboard
2. Navigate to Call Logs
3. Find recent call by phone number
4. Review duration, status, errors

### Test Different Voices
Edit `scripts/make-ai-call.py` and change the voice:

```python
"languages": [
    {
        "name": "English",
        "code": "en-US",
        "voice": "rime.pablo"  # Try different voices
    }
]
```

Available voices:
- `rime.spore` - Natural male voice (current)
- `rime.pablo` - Alternative male voice
- `rime.hans` - German accent male
- `rime.alois` - French accent male

---

## Success Criteria

Before deploying to production, verify:

- [ ] 10 test calls completed successfully
- [ ] 0 voicemail failures (all calls reached phone)
- [ ] Voice quality rated 8+/10 (natural, not robotic)
- [ ] AI successfully listened and responded in 100% of calls
- [ ] No awkward pauses or delays
- [ ] Objection handling works properly
- [ ] Information gathering works correctly

---

## Comparison Results

### Before Fix (TwiML)
```
Call #1: FAILED (voicemail)
Call #2: FAILED (voicemail)
Call #3: SUCCESS but robotic voice, 8-second delay
Calls #4-6: FAILED
Success Rate: 16% (1/6)
Voice Quality: 3/10 (robotic)
```

### After Fix (AI Agent)
```
Test this and document results:
- Connection success rate: ____%
- Voice quality: ___/10
- AI responsiveness: ___/10
- Overall satisfaction: ___/10
```

---

## Next Steps

After successful testing:

1. **Production deployment**
   - Deploy AI agent to production server (or use inline SWML)
   - Configure webhook URLs if needed
   - Set up call logging to database

2. **Integration**
   - Connect to CRM (Salesforce)
   - Save contact info to Firestore
   - Generate follow-up tasks

3. **Optimization**
   - Fine-tune AI prompts based on call transcripts
   - Adjust voice settings if needed
   - Optimize response timing

---

**Testing Date:** 2026-02-11  
**Tester:** Samson  
**Status:** Ready for validation

Call 6022950104 and verify the AI works as expected!
