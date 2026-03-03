# AI Voice Caller Test Results - 2026-02-11 08:01 MST

## Test Session: All 3 Approaches

### Option 2: Dialogflow CX ❌ FAILED
**Call SID:** a85cff02-74ab-4b23-9d18-3290224b0633  
**Time:** 15:01:01 UTC  
**Duration:** 0 seconds  
**Status:** failed  
**SIP Result Code:** 500 - Service Unavailable  
**Hangup By:** +16022950104 (Samson's phone)  
**Hangup Direction:** inbound  

**Analysis:**
- Webhook received call correctly
- SignalWire initiated call
- **Samson's phone rejected the call** with SIP 500
- Likely carrier spam filtering or call blocking

**Webhook Logs:**
```
CallStatus: 'initiated' → CallStatus: 'failed'
SipResultCode: '500'
SipInviteResultPhrase: 'Service Unavailable'
HangupBy: '+16022950104'
```

---

### Option 1: SignalWire Agents SDK ⏳ TESTING
**Call ID:** unknown  
**Time:** ~15:01 UTC  
**Status:** 200 OK response, waiting for ring  
**Agent:** Discovery Mode (make-ai-call.py)  

**Expected:**
- AI agent should introduce as Paul from Fortinet
- Ask for IT contact info
- Real AI conversation (not pre-recorded)

**Status:** Waiting to hear if phone rings

---

### Option A: SignalWire Native AI Agent API ❌ FAILED (Wrong Endpoint)
**Agent ID:** f2c41814-4a36-436b-b723-71d5cdffec60  
**Status:** 404 Not Found  
**Error:** Used wrong API endpoint (`/api/relay/rest/calls`)  

**Issue:** Need to use Compatibility API (Twilio-compatible), not Relay REST API

**Fix Needed:** Update test-native-ai-agent.py to use:
```
https://{space_url}/api/laml/2010-04-01/Accounts/{project_id}/Calls
```

---

## Pattern Identified

**All outbound calls are being rejected by carrier:**
- SIP 500 "Service Unavailable"
- Hangup by recipient phone
- Duration: 0 seconds
- Consistent across all approaches

**Hypothesis:**
1. **Carrier spam filter** - T-Mobile/AT&T/Verizon blocking SignalWire number
2. **STIR/SHAKEN** - Call attestation failing
3. **New number reputation** - +16028985026 purchased Feb 11, no reputation yet
4. **Automated call detection** - Carrier detecting robocall pattern

**Next Steps:**
1. Try **inbound test** - have Samson call +16028985026
2. Check SignalWire **caller ID verification** status
3. Enable **CNAM registration** (Caller ID name)
4. Wait 24-48 hours for **number warming**
5. Try calling a **different test number** (not Samson's cell)

---

## Recommendations

### Immediate
1. **Inbound test:** Samson calls +16028985026 to verify webhook works
2. **Different number:** Try calling a landline or Google Voice number
3. **SignalWire dashboard:** Check caller ID reputation/verification

### Short-term
4. **CNAM registration:** Add "Fortinet" as caller ID name
5. **Number warming:** Make manual calls first (human→human)
6. **STIR/SHAKEN:** Verify attestation level in SignalWire

### If Still Failing
7. **Contact SignalWire support:** Ask about call completion rates to major carriers
8. **Try different carrier:** Get a number from different provider
9. **Use different approach:** SMS first, then call after relationship established

---

**Status:** No approach working yet - root cause is carrier-level call blocking, not code issues.
