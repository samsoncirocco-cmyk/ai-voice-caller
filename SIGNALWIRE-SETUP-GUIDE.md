# SignalWire Setup Guide (5 Minutes)

## Step-by-Step Instructions

### 1. Sign Up (2 minutes)
1. Go to: https://signalwire.com/signup
2. Fill out form:
   - Email: (your work email)
   - Password: (create one)
   - Company: Fortinet
3. Verify email (check inbox)

### 2. Create Space (1 minute)
After signup, you'll create a "Space" (like a project):
- Space name: `fortinet-sled-caller` (or whatever you want)
- This becomes your Space URL: `fortinet-sled-caller.signalwire.com`

### 3. Get Phone Number (1 minute)
1. In SignalWire dashboard, go to: **Phone Numbers** → **Buy a Number**
2. Search for area code: (pick one - maybe 515 for Iowa, 402 for Nebraska, 605 for South Dakota)
3. Pick a number from results
4. Click **Buy** ($1/month)

### 4. Get API Credentials (1 minute)
1. In SignalWire dashboard, go to: **API** → **Credentials**
2. You'll see:
   - **Project ID:** (looks like `12345678-abcd-1234-abcd-123456789abc`)
   - **API Token:** (looks like `PTxxx...`)
   - **Space URL:** `yourspace.signalwire.com`
3. **Copy these** - you'll give them to Paul

### 5. Share Credentials with Paul

Send Paul:
```
SignalWire Credentials:
- Project ID: [paste here]
- API Token: [paste here]  
- Space URL: [paste here]
- Phone Number: [the number you bought]
```

**Security note:** These are like passwords - only share via secure channel (Telegram is fine)

---

## What SignalWire Does

Think of SignalWire as the "phone company" for the bot:
- Provides a phone number
- Routes calls to/from Google Cloud
- Handles telephony stuff (SIP, voice codecs, etc.)

**Why SignalWire vs. Twilio?**
- Cheaper: $0.0085/min vs. Twilio $0.013/min
- Better for this use case (native FreeSWITCH)
- More programmable

---

## Cost Breakdown

| Item | Cost |
|------|------|
| Phone number | $1/month |
| Outbound calls | $0.0085/minute |
| Example: 100 calls × 3 min avg | 300 min = $2.55/month |
| **Total monthly** | **~$3.50/month** |

**First month free trial** (usually $50 credit)

---

## Troubleshooting

**Q: Do I need a business account?**  
A: No, regular account is fine.

**Q: What if I already have a Twilio account?**  
A: SignalWire is better for this, but we could use Twilio if you prefer (just costs more).

**Q: Can I use the phone number for other things?**  
A: Yes, but dedicated to bot is cleaner.

**Q: What if I want to port my extra cell phone number to SignalWire?**  
A: Possible but not needed for testing. Let's start simple with a new number.

---

## Next Steps After Signup

1. Send credentials to Paul (via Telegram)
2. Paul configures bot to use SignalWire
3. Paul tests by calling your extra phone
4. If it works, we're ready for real discovery calls

**Estimated time to first test call:** 1-2 hours after Paul gets credentials
