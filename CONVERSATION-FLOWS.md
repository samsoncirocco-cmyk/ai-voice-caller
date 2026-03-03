# AI Voice Caller - Conversation Flows
**Version:** 1.0  
**Last Updated:** 2026-02-10  
**Status:** Design Phase  

---

## Table of Contents
1. [Overview](#1-overview)
2. [Entity Definitions](#2-entity-definitions)
3. [Intent Definitions](#3-intent-definitions)
4. [Use Case 1: Cold Calling](#4-use-case-1-cold-calling)
5. [Use Case 2: Follow-Up Calls](#5-use-case-2-follow-up-calls)
6. [Use Case 3: Appointment Setting](#6-use-case-3-appointment-setting)
7. [Use Case 4: Lead Qualification](#7-use-case-4-lead-qualification)
8. [Use Case 5: Information Delivery](#8-use-case-5-information-delivery)
9. [Common Handlers](#9-common-handlers)
10. [Gemini Integration Points](#10-gemini-integration-points)

---

## 1. Overview

### 1.1 Flow Structure

Each use case is implemented as a **Dialogflow CX Flow** with the following structure:

```
Flow
├── Start Page
├── Page 1 (e.g., Greeting)
│   ├── Entry Fulfillment (what bot says)
│   ├── Route 1 → Page 2 (if intent matches)
│   ├── Route 2 → Page 3 (if different intent)
│   └── Route 3 → Error Handler (if no match)
├── Page 2
│   └── ... more routes
└── End Session Page
```

### 1.2 Context Parameters

Parameters persist throughout the session and inform responses:

```json
{
  "account_name": "Phoenix Union High School District",
  "contact_name": "John",
  "contact_title": "IT Director",
  "use_case": "cold_calling",
  "conversation_goal": "qualify_interest",
  "lead_score": 0,
  "pain_points": [],
  "objections_count": 0,
  "current_system": null,
  "meeting_scheduled": false,
  "email_collected": null,
  "opted_out": false
}
```

### 1.3 Webhook Call Points

| Webhook | Trigger Point | Purpose |
|---------|---------------|---------|
| `gemini-responder` | Low-confidence intent match | Generate intelligent response |
| `calendar-availability` | User agrees to meeting | Check available slots |
| `calendar-book` | User confirms time | Create calendar event |
| `salesforce-update` | Call ends | Create task, update lead |
| `call-logger` | Call ends | Log call to Firestore |
| `send-email` | User requests info | Send follow-up email |

---

## 2. Entity Definitions

### 2.1 @confirmation

**Purpose:** Detect yes/no/maybe responses

**Type:** Regexp entity

```
Entity: @confirmation
├── yes
│   ├── yes
│   ├── yeah
│   ├── yep
│   ├── sure
│   ├── absolutely
│   ├── definitely
│   ├── correct
│   ├── that's right
│   ├── sounds good
│   ├── works for me
│   ├── I'd be interested
│   └── let's do it
│
├── no
│   ├── no
│   ├── nope
│   ├── not really
│   ├── not interested
│   ├── no thanks
│   ├── we're good
│   ├── not right now
│   ├── don't need it
│   └── pass
│
└── maybe
    ├── maybe
    ├── possibly
    ├── not sure
    ├── I'll think about it
    ├── let me check
    ├── depends
    └── we might be interested
```

### 2.2 @time-preference

**Purpose:** Detect preferred meeting times

**Type:** Regexp entity

```
Entity: @time-preference
├── morning
│   ├── morning
│   ├── mornings
│   ├── AM
│   ├── before noon
│   ├── early in the day
│   └── first thing
│
├── afternoon
│   ├── afternoon
│   ├── afternoons
│   ├── PM
│   ├── after noon
│   ├── after lunch
│   └── later in the day
│
├── specific_time (captures value)
│   ├── [0-9]{1,2}(:[0-9]{2})?\s?(am|pm)?
│   ├── at $number
│   ├── $number o'clock
│   └── around $number
│
└── anytime
    ├── anytime
    ├── whenever
    ├── flexible
    ├── any time works
    └── I'm open
```

### 2.3 @date-preference

**Purpose:** Detect preferred meeting dates

**Type:** System entity + custom

```
Entity: @date-preference
├── @sys.date (system entity)
│   ├── Monday, Tuesday, etc.
│   ├── tomorrow
│   ├── next week
│   └── February 15th, etc.
│
├── next_week
│   ├── next week
│   ├── sometime next week
│   └── early next week
│
├── this_week
│   ├── this week
│   ├── before Friday
│   └── in the next few days
│
└── specific_day
    ├── $day_name
    └── on $date
```

### 2.4 @email

**Purpose:** Capture email addresses

**Type:** Regexp entity

```
Entity: @email
Pattern: [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}

Synonyms:
├── spelled out: "j smith at phoenix dot k12 dot az dot us"
└── phonetic: "j as in john, smith, at phoenix..."
```

### 2.5 @phone-system

**Purpose:** Detect current phone system vendor

**Type:** Custom entity

```
Entity: @phone-system
├── cisco
│   ├── Cisco
│   ├── CUCM
│   ├── UCM
│   ├── CallManager
│   ├── Cisco Unity
│   └── Webex Calling
│
├── microsoft
│   ├── Microsoft Teams
│   ├── Teams Phone
│   ├── Skype for Business
│   └── Teams
│
├── avaya
│   ├── Avaya
│   ├── Avaya IP Office
│   └── Aura
│
├── mitel
│   ├── Mitel
│   ├── MiVoice
│   └── ShoreTel
│
├── ringcentral
│   ├── RingCentral
│   └── RingCentral MVP
│
├── zoom
│   ├── Zoom Phone
│   └── Zoom
│
├── legacy
│   ├── Nortel
│   ├── NEC
│   ├── Panasonic
│   └── analog
│
└── cloud_other
    ├── 8x8
    ├── Vonage
    ├── Dialpad
    └── Nextiva
```

### 2.6 @objection-type

**Purpose:** Classify objections for handling

**Type:** Custom entity

```
Entity: @objection-type
├── not_interested
│   ├── not interested
│   ├── don't need it
│   ├── we're all set
│   └── no need
│
├── bad_timing
│   ├── not a good time
│   ├── busy right now
│   ├── call back later
│   └── in a meeting
│
├── send_email
│   ├── just send me an email
│   ├── email me
│   └── put it in writing
│
├── have_vendor
│   ├── we already have a vendor
│   ├── under contract
│   ├── locked in
│   └── happy with what we have
│
├── no_budget
│   ├── no budget
│   ├── can't afford it
│   ├── too expensive
│   └── not in the budget
│
└── wrong_person
    ├── wrong person
    ├── I don't handle that
    ├── not my area
    └── talk to someone else
```

### 2.7 @user-count

**Purpose:** Capture organization size

**Type:** Regexp + custom

```
Entity: @user-count
├── small (1-24)
│   ├── [1-9]
│   ├── 1[0-9]
│   ├── 2[0-4]
│   ├── handful
│   ├── small team
│   └── just a few
│
├── medium (25-99)
│   ├── 2[5-9]
│   ├── [3-9][0-9]
│   ├── around 50
│   ├── about 75
│   └── less than 100
│
├── large (100-499)
│   ├── [1-4][0-9]{2}
│   ├── a couple hundred
│   ├── few hundred
│   └── over 100
│
└── enterprise (500+)
    ├── [5-9][0-9]{2}
    ├── [0-9]{4,}
    ├── over 500
    ├── thousand
    └── several hundred
```

---

## 3. Intent Definitions

### 3.1 Core Intents

#### confirm_identity
**Purpose:** Caller confirms they are the right person

**Training Phrases:**
```
- "Yes"
- "Yes, this is [name]"
- "Speaking"
- "That's me"
- "This is [name]"
- "You got me"
- "What can I do for you?"
- "Who's calling?"
- "What's this about?"
```

#### wrong_person
**Purpose:** Caller indicates they are not the intended contact

**Training Phrases:**
```
- "No, wrong number"
- "You have the wrong person"
- "That's not me"
- "[name] isn't here"
- "They're not available"
- "Can I take a message?"
- "[name] no longer works here"
- "Let me transfer you"
```

#### express_interest
**Purpose:** Caller shows positive interest

**Training Phrases:**
```
- "That sounds interesting"
- "Tell me more"
- "I'd like to learn more"
- "What does that look like?"
- "How does it work?"
- "What would that cost?"
- "We've been thinking about that"
- "Actually, we're looking at that right now"
- "That's good timing"
- "We might be interested"
```

#### express_disinterest
**Purpose:** Caller declines or shows negative sentiment

**Training Phrases:**
```
- "Not interested"
- "We're all set"
- "Don't need it"
- "No thanks"
- "We're happy with what we have"
- "Not looking to change"
- "Please don't call again"
- "Take me off your list"
- "Stop calling"
```

#### request_information
**Purpose:** Caller asks for more details or materials

**Training Phrases:**
```
- "Can you send me something?"
- "Do you have a brochure?"
- "Send me an email"
- "What's your website?"
- "Can I get more information?"
- "Put it in writing"
- "I'd like to see some documentation"
```

#### agree_to_meeting
**Purpose:** Caller agrees to schedule a meeting

**Training Phrases:**
```
- "Sure, let's set something up"
- "I can do a meeting"
- "That works"
- "Let's find a time"
- "I'm open to a call"
- "Yeah, let's talk more"
- "Schedule something"
```

#### provide_time_preference
**Purpose:** Caller provides scheduling preference

**Training Phrases:**
```
- "Mornings work best"
- "How about Tuesday?"
- "I'm free next week"
- "Afternoons are better"
- "I can do 10 AM"
- "What about Thursday at 2?"
- "Anytime works for me"
```

#### confirm_time
**Purpose:** Caller confirms a proposed meeting time

**Training Phrases:**
```
- "That works"
- "Perfect"
- "Sounds good"
- "I'll be there"
- "Let's do it"
- "Book it"
- "Yes, that time works"
```

#### reject_time
**Purpose:** Caller rejects a proposed meeting time

**Training Phrases:**
```
- "That doesn't work"
- "I'm not available then"
- "Can we do a different time?"
- "I have a conflict"
- "That's not good for me"
```

#### ask_question
**Purpose:** Caller asks a question (route to Gemini)

**Training Phrases:**
```
- "What is [topic]?"
- "How does [feature] work?"
- "Can you explain [thing]?"
- "What's the difference between [A] and [B]?"
- "Why would I need [product]?"
- "What makes you different from [competitor]?"
```

#### provide_information
**Purpose:** Caller provides requested information

**Training Phrases:**
```
- "We use [system]"
- "About [number] users"
- "Our contract ends [date]"
- "We have [number] locations"
- "My email is [email]"
- "It's [answer]"
```

#### request_callback
**Purpose:** Caller requests to be called back later

**Training Phrases:**
```
- "Can you call back later?"
- "I'm busy right now"
- "Try me next week"
- "Call me tomorrow"
- "This isn't a good time"
- "Let me give you a better time to call"
```

#### opt_out
**Purpose:** Caller requests to not be called again

**Training Phrases:**
```
- "Stop calling"
- "Don't call me again"
- "Take me off your list"
- "Remove my number"
- "Opt out"
- "Unsubscribe"
- "I don't want any more calls"
```

### 3.2 Discovery Intents

#### describe_current_system
**Purpose:** Caller describes their current phone system

**Training Phrases:**
```
- "We use Cisco"
- "We have Teams"
- "It's an old Avaya system"
- "We're on RingCentral"
- "We've got an on-prem PBX"
- "It's pretty outdated"
- "We just upgraded last year"
```

**Entities extracted:** @phone-system

#### describe_pain_point
**Purpose:** Caller mentions a problem or frustration

**Training Phrases:**
```
- "It goes down a lot"
- "We have issues when the internet is out"
- "Support is expensive"
- "It's hard to manage"
- "We can't support remote workers"
- "The quality is bad"
- "We're paying too much"
- "It's end of life"
```

**Parameters set:**
```json
{
  "pain_points": {"append": "$detected_pain"},
  "lead_score": {"increment": 1}
}
```

#### describe_buying_timeline
**Purpose:** Caller mentions timeline for changes

**Training Phrases:**
```
- "We're looking to change this year"
- "Probably not until next fiscal year"
- "We're evaluating options now"
- "Contract renews in [month]"
- "No plans to change"
- "We're in the middle of a project"
```

### 3.3 Fallback Intents

#### Default Welcome Intent
**Trigger:** Session start

#### Default Negative Intent
**Trigger:** Strong negative sentiment

#### Default Fallback Intent
**Trigger:** No other intent matches (confidence < 0.3)
**Action:** Route to Gemini webhook

---

## 4. Use Case 1: Cold Calling

### 4.1 Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     COLD CALLING FLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Start   │───▶│ Greeting │───▶│ Killer   │───▶│ Interest │  │
│  │          │    │          │    │ Question │    │  Check   │  │
│  └──────────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘  │
│                       │               │               │         │
│               wrong   │        answer │        ┌──────┴──────┐  │
│               person  │               │        │             │  │
│                  ▼    │               │        ▼             ▼  │
│              ┌───────┐│               │  ┌──────────┐  ┌──────┐ │
│              │Find   ││               │  │  Book    │  │ Send │ │
│              │Right  ││               │  │ Meeting  │  │ Info │ │
│              │Person ││               │  │          │  │      │ │
│              └───────┘│               │  └────┬─────┘  └──┬───┘ │
│                       │               │       │           │     │
│                       ▼               ▼       ▼           ▼     │
│                  ┌────────────────────────────────────────┐     │
│                  │              End Session               │     │
│                  └────────────────────────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Page: Start

**Entry Fulfillment:** (none - silent start)

**Routes:**
| Condition | Target Page |
|-----------|-------------|
| true | Greeting |

### 4.3 Page: Greeting

**Entry Fulfillment:**
```
Hi, is this $session.params.contact_name?
```

**SSML:**
```xml
<speak>
  Hi, <break time="200ms"/> is this <break time="100ms"/> 
  $session.params.contact_name?
</speak>
```

**Routes:**

| Intent | Condition | Target Page | Fulfillment |
|--------|-----------|-------------|-------------|
| confirm_identity | - | Introduction | - |
| wrong_person | - | Find Right Person | - |
| - | $page.params.no_input_count >= 2 | Retry Greeting | "I didn't catch that. Is this $contact_name?" |
| Default Fallback | - | Introduction | (assume yes if unclear) |

### 4.4 Page: Introduction

**Entry Fulfillment:**
```
Great! This is Paul from Fortinet. I work with IT leaders in 
$session.params.account_state on voice and network solutions. 
Do you have 2 minutes for a quick question?
```

**SSML:**
```xml
<speak>
  Great! <break time="300ms"/>
  This is Paul from Fortinet. <break time="200ms"/>
  I work with <say-as interpret-as="characters">IT</say-as> leaders in 
  $session.params.account_state on voice and network solutions.
  <break time="400ms"/>
  Do you have 2 minutes for a quick question?
</speak>
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| yes (confirmation.yes) | Killer Question | - |
| no (confirmation.no) | Handle Busy | - |
| request_callback | Schedule Callback | - |
| opt_out | Opt Out Handler | - |
| Default Fallback | Killer Question | (proceed if unclear) |

### 4.5 Page: Killer Question

**Entry Fulfillment:**
```
Perfect. Quick question: what happens to your phones when the internet goes down?
```

**SSML:**
```xml
<speak>
  Perfect. <break time="300ms"/>
  Quick question: <break time="200ms"/>
  <emphasis level="moderate">what happens to your phones</emphasis> 
  when the internet goes down?
</speak>
```

**Webhook:** (none on entry)

**Routes:**

| Intent | Condition | Target Page | Parameter Updates | Fulfillment |
|--------|-----------|-------------|-------------------|-------------|
| describe_pain_point | - | Interest Check | pain_points += $detected_pain, lead_score += 1 | - |
| provide_information | @phone-system detected | Interest Check | current_system = @phone-system | - |
| ask_question | - | Gemini Handler | - | [Webhook: gemini-responder] |
| express_interest | - | Interest Check | lead_score += 2 | - |
| express_disinterest | - | Handle Objection | objection_type = "not_interested" | - |
| Default Fallback | confidence < 0.3 | Gemini Handler | - | [Webhook: gemini-responder] |
| - | $page.params.no_input_count >= 2 | Clarify Question | - | "Sorry, I didn't catch that. When your internet goes down, do your phones still work?" |

**Expected Responses & Handling:**

```
Response: "They go down too"
  → Route to Interest Check
  → Set pain_points = ["no_survivability"]
  → Set lead_score += 2

Response: "We have failover"
  → Route to Interest Check
  → Entry: "Smart. A lot of districts don't. Are you happy with that setup, or is it something you'd improve?"

Response: "I don't know"
  → Route to Interest Check
  → Entry: "That's a common gap. Most districts don't realize their phones are internet-dependent until an outage hits."

Response: "Why do you ask?"
  → Route to Gemini Handler
  → Gemini generates explanation

Response: "We use cell phones"
  → Route to Interest Check
  → Entry: "Makes sense as a backup. How about 911 calling – does that route properly from cells in your buildings?"
```

### 4.6 Page: Interest Check

**Entry Fulfillment:** (dynamic based on previous response)

Default:
```
Got it. Are you happy with your current voice setup, or is it something you're looking to improve?
```

After pain point:
```
That's actually one of the main things we solve. Would you be open to a 15-minute call to discuss local survivability options?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| express_interest | Offer Meeting | lead_score += 2 | "Great! Let me tell you what I can do..." |
| agree_to_meeting | Book Meeting | lead_score += 3 | - |
| confirmation.maybe | Offer More Info | lead_score += 1 | "I understand. Would it help if I sent you some information first?" |
| express_disinterest | Handle Objection | objection_type = "not_interested" | - |
| request_information | Collect Email | - | "Happy to send you something. What's the best email?" |
| ask_question | Gemini Handler | - | [Webhook: gemini-responder] |

### 4.7 Page: Offer Meeting

**Entry Fulfillment:**
```
Based on what you've shared, I think there's a fit here. 
Would you be open to a 15-minute call with our partner High Point Networks? 
They can walk through how this works and answer any technical questions.
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| agree_to_meeting | Book Meeting | - |
| confirmation.yes | Book Meeting | - |
| confirmation.no | Offer More Info | "No problem. Would it help if I sent you some information to review first?" |
| confirmation.maybe | Offer More Info | - |
| request_callback | Schedule Callback | - |

### 4.8 Page: Book Meeting

**Entry Fulfillment:**
```
Perfect. Let me check availability. Are mornings or afternoons better for you?
```

**Webhook on Entry:** `calendar-availability` (check available slots)

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_time_preference | Propose Time | time_preference = @time-preference | [Use webhook response with available slots] |
| confirmation.yes (to first proposed time) | Confirm Meeting | selected_time = $proposed_time | - |

**Page: Propose Time**

**Entry Fulfillment:** (from webhook)
```
I have $available_slot_1 or $available_slot_2 available. Which works better?
```

**Routes:**

| Intent | Condition | Target Page | Parameter Updates |
|--------|-----------|-------------|-------------------|
| confirm_time | slot mentioned | Confirm Meeting | selected_time = matched slot |
| reject_time | - | Propose Time | [Get next slots from webhook] |

**Page: Confirm Meeting**

**Entry Fulfillment:**
```
Great! I've got you down for $selected_time. 
What email should I send the calendar invite to?
```

**Webhook on Entry:** `calendar-book` (create event)

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_information | Meeting Confirmed | email = @email | - |
| - | $session.params.email_known | Meeting Confirmed | - | (skip if email already known)

**Page: Meeting Confirmed**

**Entry Fulfillment:**
```
Perfect. You'll receive a calendar invite at $email with a video link. 
$partner_name from High Point Networks will be on the call. 
Is there anything specific you'd like us to cover?
```

**Webhook on Entry:** `salesforce-update` (create task)

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| provide_information | End Session - Success | "Got it. I'll make sure they're prepared for that. Thanks for your time, $contact_name. Talk soon!" |
| confirmation.no | End Session - Success | "Sounds good. Talk to you on $meeting_date. Have a great day!" |
| Default Fallback | End Session - Success | "All set. Looking forward to the call. Thanks $contact_name!" |

### 4.9 Page: Offer More Info

**Entry Fulfillment:**
```
Would it help if I sent you some information to review? 
I can send a quick overview of local survivability options.
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| confirmation.yes | Collect Email | "Great! What's the best email address?" |
| express_interest | Collect Email | - |
| confirmation.no | End Session - Cold | "No problem. If voice modernization ever comes up, feel free to reach out. Have a great day!" |

### 4.10 Page: Collect Email

**Entry Fulfillment:**
```
What's the best email to reach you?
```

**Routes:**

| Intent | Condition | Target Page | Parameter Updates | Fulfillment |
|--------|-----------|-------------|-------------------|-------------|
| provide_information | @email detected | Confirm Email | email = @email | "Just to confirm, that's $email?" |
| - | $page.params.no_input_count >= 2 | End Session - Warm | - | "No problem. I'll follow up with a call. Thanks for your time!" |

**Page: Confirm Email**

**Entry Fulfillment:**
```
Just to confirm, that's $session.params.email?
```

**Routes:**

| Intent | Target Page | Fulfillment | Webhook |
|--------|-------------|-------------|---------|
| confirmation.yes | End Session - Warm | "Perfect. I'll send that over today. Keep an eye out for an email from Paul at Fortinet. Thanks $contact_name!" | `send-email` |
| confirmation.no | Collect Email | "Let me get that again. What's your email?" | - |

### 4.11 Page: Handle Objection

**Entry Fulfillment:** (varies by objection_type)

```
objection_type = "not_interested":
  "Totally understand. Can I ask – is it not a fit right now, or not a fit at all? 
   Just so I know whether to check back when your situation changes."

objection_type = "have_vendor":
  "Got it. Are you under contract, or just happy with them? 
   Sometimes I can offer perspective on what's changed in the market."

objection_type = "no_budget":
  "I hear you. Are you in budget planning for next year? 
   We've helped districts get E-Rate funding for voice projects."

objection_type = "bad_timing":
  "No problem. When would be a better time to catch you?"
```

**Webhook on Entry:** `gemini-responder` (for intelligent objection handling)

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| express_interest | Offer Meeting | "Great! Let me tell you what I can do..." |
| request_callback | Schedule Callback | - |
| confirmation.no | End Session - Not Interested | "Fair enough. If things change, you know where to find us. Have a great day!" |
| opt_out | Opt Out Handler | - |

### 4.12 Page: Handle Busy

**Entry Fulfillment:**
```
No problem, I'll keep it quick. When the internet goes down, do your phones still work?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| provide_information | Interest Check | - |
| request_callback | Schedule Callback | - |
| express_disinterest | End Session - Busy | "Understood. Would it be okay to call back another time?" |

### 4.13 Page: Schedule Callback

**Entry Fulfillment:**
```
No problem. When's a better time to catch you?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_time_preference | Confirm Callback | callback_time = @time-preference + @date-preference | "Got it. I'll call you $callback_time. Talk then!" |
| - | no match | End Session - Callback | callback_time = "tomorrow" | "I'll try you tomorrow. Have a great day!" |

### 4.14 Page: Find Right Person

**Entry Fulfillment:**
```
I apologize. I'm looking for someone who handles voice systems or IT. 
Could you point me in the right direction?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_information | End Session - Referral | referral_info = $input | "Thank you! I'll reach out to them. Have a great day!" |
| confirmation.no | End Session - Wrong Number | - | "No problem. Sorry to bother you. Have a great day!" |

### 4.15 Page: Opt Out Handler

**Entry Fulfillment:**
```
I completely understand. I'm removing your number from our list right now. 
You won't receive any more calls. Have a great day.
```

**Webhook on Entry:** `call-logger` with `opted_out: true`

**Routes:**

| Condition | Target Page |
|-----------|-------------|
| true | End Session - Opted Out |

### 4.16 End Session Pages

**End Session - Success** (meeting booked)
```
lead_score += 3
call_outcome = "interested_meeting_booked"
→ Webhook: salesforce-update, call-logger
→ End conversation
```

**End Session - Warm** (info sent)
```
lead_score += 1
call_outcome = "interested_send_info"
→ Webhook: send-email, salesforce-update, call-logger
→ End conversation
```

**End Session - Callback** (scheduled callback)
```
call_outcome = "callback_scheduled"
→ Webhook: salesforce-update, call-logger
→ End conversation
```

**End Session - Not Interested**
```
call_outcome = "not_interested"
→ Webhook: salesforce-update, call-logger
→ End conversation
```

**End Session - Opted Out**
```
call_outcome = "opted_out"
→ Webhook: call-logger (add to DNC)
→ End conversation
```

---

## 5. Use Case 2: Follow-Up Calls

### 5.1 Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     FOLLOW-UP FLOW                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │  Start   │───▶│ Greeting │───▶│ Email    │                   │
│  │          │    │          │    │ Check    │                   │
│  └──────────┘    └──────────┘    └────┬─────┘                   │
│                                       │                          │
│                    ┌──────────────────┼──────────────────┐      │
│                    │                  │                  │      │
│                    ▼                  ▼                  ▼      │
│              ┌──────────┐      ┌──────────┐      ┌──────────┐  │
│              │ Read It  │      │ Didn't   │      │ Not      │  │
│              │ (discuss)│      │ See It   │      │Interested│  │
│              └────┬─────┘      └────┬─────┘      └────┬─────┘  │
│                   │                 │                  │        │
│                   ▼                 ▼                  ▼        │
│              ┌──────────┐      ┌──────────┐      ┌──────────┐  │
│              │ Book     │      │ Quick    │      │ Handle   │  │
│              │ Meeting  │      │ Pitch    │      │ Objection│  │
│              └────┬─────┘      └────┬─────┘      └──────────┘  │
│                   │                 │                           │
│                   ▼                 ▼                           │
│              ┌────────────────────────────┐                     │
│              │       End Session          │                     │
│              └────────────────────────────┘                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Page: Start

**Context Required:**
```json
{
  "contact_name": "John",
  "account_name": "Phoenix Union HSD",
  "email_topic": "voice modernization",
  "email_sent_date": "last week",
  "previous_pain_points": ["aging infrastructure"]
}
```

### 5.3 Page: Greeting

**Entry Fulfillment:**
```
Hi $contact_name, this is Paul from Fortinet. 
I sent you an email $email_sent_date about $email_topic. 
Did you get a chance to look at it?
```

**SSML:**
```xml
<speak>
  Hi $contact_name, <break time="200ms"/>
  this is Paul from Fortinet.
  <break time="300ms"/>
  I sent you an email $email_sent_date about $email_topic.
  <break time="400ms"/>
  Did you get a chance to look at it?
</speak>
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| confirmation.yes | Email Discussion | "Great! What did you think?" |
| confirmation.no | Quick Pitch | - |
| wrong_person | End Session - Wrong Person | "I apologize. Have a great day!" |
| express_disinterest | Handle Objection | - |
| request_callback | Schedule Callback | - |

### 5.4 Page: Email Discussion

**Entry Fulfillment:**
```
Great! What did you think? Any questions I can answer?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| express_interest | Offer Meeting | - |
| ask_question | Gemini Handler | [Webhook: gemini-responder] |
| confirmation.no | Alternative Content | "No worries. Is there something different I can send that would be more relevant?" |
| express_disinterest | Handle Objection | - |

### 5.5 Page: Quick Pitch

**Entry Fulfillment:**
```
No worries, inboxes are crazy. Quick summary: we're helping 
$account_type in $account_state with $email_topic. 

Based on what we discussed before about $previous_pain_points[0], 
I think there might be a fit. Would it be worth a 15-minute call 
to explore your options?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| agree_to_meeting | Book Meeting | - |
| express_interest | Book Meeting | - |
| confirmation.maybe | Offer More Info | "I understand. Want me to resend that email, or would a different resource be more helpful?" |
| express_disinterest | Handle Objection | - |
| ask_question | Gemini Handler | [Webhook: gemini-responder] |

### 5.6 Page: Alternative Content

**Entry Fulfillment:**
```
I can send you a case study from a $account_type similar to yours, 
or a quick one-pager on $email_topic. Which would be more useful?
```

**Routes:**

| Intent | Condition | Target Page | Fulfillment |
|--------|-----------|-------------|-------------|
| provide_information | mentions "case study" | Collect Email | content_type = "case_study" |
| provide_information | mentions "one-pager" | Collect Email | content_type = "one_pager" |
| confirmation.no | - | End Session - Not Interested | "No problem. If things change, don't hesitate to reach out." |

---

## 6. Use Case 3: Appointment Setting

### 6.1 Flow Overview

This flow is typically entered from other flows (Cold Calling, Follow-Up) when the caller agrees to a meeting.

```
┌─────────────────────────────────────────────────────────────────┐
│                  APPOINTMENT SETTING FLOW                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Entry   │───▶│ Time     │───▶│ Propose  │───▶│ Confirm  │  │
│  │          │    │ Preference│    │ Options  │    │ Meeting  │  │
│  └──────────┘    └──────────┘    └────┬─────┘    └────┬─────┘  │
│                                       │               │         │
│                                       │ reject        │         │
│                                       ▼               ▼         │
│                                ┌──────────┐    ┌──────────┐     │
│                                │ More     │    │ Capture  │     │
│                                │ Options  │    │ Email    │     │
│                                └──────────┘    └────┬─────┘     │
│                                                     │           │
│                                                     ▼           │
│                                              ┌──────────┐       │
│                                              │ Success  │       │
│                                              │          │       │
│                                              └──────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Page: Entry

**Entry Fulfillment:**
```
Sounds like this could be a fit. Would you be open to a 15-minute call 
with our partner High Point Networks? They specialize in voice for 
$account_type and can answer any technical questions.
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| confirmation.yes | Time Preference | "Great! Let me check availability." |
| agree_to_meeting | Time Preference | - |
| confirmation.no | Offer Alternative | "No problem. Would you prefer to just get some information first?" |

### 6.3 Page: Time Preference

**Entry Fulfillment:**
```
Are mornings or afternoons generally better for you?
```

**Webhook on Entry:** `calendar-availability` with `duration_minutes: 30`

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_time_preference | Propose Options | time_pref = @time-preference | - |
| - | no specific preference | Propose Options | time_pref = "anytime" | - |

### 6.4 Page: Propose Options

**Entry Fulfillment:** (from webhook response)
```
Looking at the calendar... I have $slot_1_display or $slot_2_display available. 
Which works better for you?
```

**Example fulfillments:**
```
"I have Tuesday the 17th at 9:30 AM or Wednesday the 18th at 10:00 AM. 
Which works better?"

"Next week, I see openings on Monday at 2 PM, Tuesday at 10 AM, or 
Thursday at 3 PM. Any of those work?"
```

**Routes:**

| Intent | Condition | Target Page | Parameter Updates |
|--------|-----------|-------------|-------------------|
| confirm_time | mentions slot 1 | Confirm Meeting | selected_slot = $slot_1 |
| confirm_time | mentions slot 2 | Confirm Meeting | selected_slot = $slot_2 |
| provide_time_preference | different preference | More Options | - |
| reject_time | - | More Options | - |

### 6.5 Page: More Options

**Entry Fulfillment:**
```
Let me look at other options. What day works best for you?
```

**Webhook:** `calendar-availability` with new parameters

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| provide_time_preference | Propose Options | - |
| - | 3rd attempt | Send Scheduler | "You know what, let me send you a scheduling link. That way you can pick exactly what works. What's your email?" |

### 6.6 Page: Confirm Meeting

**Entry Fulfillment:**
```
Perfect, I've got you down for $selected_slot_display. 
That's a 30-minute call with $partner_name from High Point Networks. 
What email should I send the calendar invite to?
```

**Webhook on Entry:** `calendar-book`

**Routes:**

| Intent | Condition | Target Page | Parameter Updates |
|--------|-----------|-------------|-------------------|
| provide_information | @email detected | Finalize Meeting | attendee_email = @email |
| - | email already known | Finalize Meeting | - |

### 6.7 Page: Finalize Meeting

**Entry Fulfillment:**
```
Excellent. You'll receive a calendar invite at $attendee_email 
with a Google Meet link. $partner_name will send a quick intro 
email before the call. 

Is there anything specific you'd like to cover in the meeting?
```

**Webhook on Entry:** `salesforce-update` (create task, log activity)

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_information | End Session - Success | meeting_topics = $input | "Got it. I'll make sure they're prepared for that. Talk to you on $meeting_date!" |
| confirmation.no | End Session - Success | - | "Sounds good. They'll cover everything. Thanks $contact_name, talk soon!" |

---

## 7. Use Case 4: Lead Qualification

### 7.1 Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   LEAD QUALIFICATION FLOW                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Start   │───▶│ Current  │───▶│ User     │───▶│ Timeline │  │
│  │          │    │ System   │    │ Count    │    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └────┬─────┘  │
│                                                       │         │
│                                         ┌─────────────┴───────┐ │
│                                         │                     │ │
│                                         ▼                     ▼ │
│                                   ┌──────────┐          ┌──────┐│
│                                   │ Pain     │          │Score ││
│                                   │ Points   │────────▶ │Lead  ││
│                                   └──────────┘          └──┬───┘│
│                                                            │    │
│                        ┌───────────────────┬───────────────┤    │
│                        │                   │               │    │
│                        ▼                   ▼               ▼    │
│                  ┌──────────┐        ┌──────────┐   ┌──────────┐│
│                  │ Hot Lead │        │ Warm Lead│   │Cold Lead ││
│                  │ (Book    │        │ (Send    │   │(Nurture) ││
│                  │ Meeting) │        │ Info)    │   │          ││
│                  └──────────┘        └──────────┘   └──────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Page: Start

**Entry Fulfillment:**
```
Before we schedule something, let me ask a few quick questions 
to make sure we're focusing on the right solution for you. 
Sound good?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| confirmation.yes | Current System | "Great, first question..." |
| confirmation.no | Explain Value | "I get it. Let me explain why these questions matter..." |

### 7.3 Page: Current System

**Entry Fulfillment:**
```
First, what phone system are you running today?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Lead Score |
|--------|-------------|-------------------|------------|
| describe_current_system | User Count | current_system = @phone-system | - |
| provide_information | User Count | current_system = $input | - |

**Score Calculation:**
```javascript
if (system_age > 5 years) lead_score += 2;
if (system in ["legacy", "cisco", "avaya"]) lead_score += 1;
```

### 7.4 Page: User Count

**Entry Fulfillment:**
```
Got it, $current_system. And how many phone users do you have 
across all your locations?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Lead Score |
|--------|-------------|-------------------|------------|
| provide_information | Timeline | user_count = @user-count | +2 if large |

### 7.5 Page: Timeline

**Entry Fulfillment:**
```
Perfect. Last question – are you planning any changes to your 
voice system in the next 6 to 12 months?
```

**Routes:**

| Intent | Target Page | Parameter Updates | Lead Score |
|--------|-------------|-------------------|------------|
| describe_buying_timeline | Pain Points | buying_timeline = $timeline | +3 if within 6 months |
| confirmation.yes | Pain Points | buying_timeline = "yes" | +3 |
| confirmation.no | Pain Points | buying_timeline = "no" | +0 |

### 7.6 Page: Pain Points

**Entry Fulfillment:**
```
Great. One more thing – what's the biggest challenge with your 
current setup? What would you fix if you could?
```

**Webhook on Entry:** (optional) `gemini-responder` if previous answers need context

**Routes:**

| Intent | Target Page | Parameter Updates | Lead Score |
|--------|-------------|-------------------|------------|
| describe_pain_point | Score Lead | pain_points += $detected_pain | +2 per pain point |
| provide_information | Score Lead | pain_points = [$input] | +1 |
| confirmation.no | Score Lead | pain_points = [] | +0 |

### 7.7 Page: Score Lead

**Entry Fulfillment:** (none - calculation page)

**Logic:**
```javascript
// Calculate final score
let score = session.params.lead_score;

// Apply scoring matrix
if (system_age > 5) score += 2;
if (user_count >= 25) score += 2;
if (buying_timeline === "within_6_months") score += 3;
if (pain_points.length >= 2) score += 2;
if (decision_maker) score += 1;

session.params.lead_score = score;

// Route based on score
if (score >= 5) {
  route_to = "Hot Lead";
} else if (score >= 3) {
  route_to = "Warm Lead";
} else {
  route_to = "Cold Lead";
}
```

**Routes:**

| Condition | Target Page |
|-----------|-------------|
| lead_score >= 5 | Hot Lead |
| lead_score >= 3 | Warm Lead |
| lead_score < 3 | Cold Lead |

### 7.8 Page: Hot Lead

**Entry Fulfillment:**
```
Based on what you've shared, I think there's definitely a strong fit. 
You've got $current_system with $user_count users, you're looking 
at changes in the next $buying_timeline, and $pain_points[0] is 
exactly what we solve.

I'd love to set up a call with our partner who specializes in 
$account_type. They can give you a demo and answer any technical 
questions. Do you have 30 minutes this week?
```

**Routes:**

| Intent | Target Page |
|--------|-------------|
| agree_to_meeting | Appointment Setting Flow |
| confirmation.yes | Appointment Setting Flow |
| confirmation.no | Warm Lead |

### 7.9 Page: Warm Lead

**Entry Fulfillment:**
```
I understand you might not be ready for a meeting yet. 
Let me send you some relevant information – a case study 
from a $account_type that was in a similar situation. 

What's the best email to reach you?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| provide_information | Schedule Follow-up | email = @email |

**Page: Schedule Follow-up**

**Entry Fulfillment:**
```
Perfect. I'll send that over today. When would be a good time 
to follow up – in a couple weeks when you've had a chance to 
review it?
```

**Webhook on Entry:** `send-email`, `salesforce-update`

**Routes:**

| Intent | Target Page | Parameter Updates | Fulfillment |
|--------|-------------|-------------------|-------------|
| provide_time_preference | End Session - Warm | callback_date = @date-preference | "Sounds good. I'll reach out $callback_date. Thanks $contact_name!" |
| confirmation.yes | End Session - Warm | callback_date = "2_weeks" | - |

### 7.10 Page: Cold Lead

**Entry Fulfillment:**
```
It sounds like the timing might not be right, but I appreciate 
you taking the time to chat. Would it be okay if I checked back 
in 6 months to see if anything has changed?
```

**Webhook on Entry:** `salesforce-update` (add to nurture campaign)

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| confirmation.yes | End Session - Nurture | "Great. I'll reach out then. In the meantime, feel free to reach out if anything changes. Have a great day!" |
| confirmation.no | End Session - Closed | "No problem. Thanks for your time. Have a great day!" |

---

## 8. Use Case 5: Information Delivery

### 8.1 Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  INFORMATION DELIVERY FLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │  Start   │───▶│ Deliver  │───▶│ Response │                   │
│  │          │    │ Message  │    │ Handler  │                   │
│  └──────────┘    └──────────┘    └────┬─────┘                   │
│                                       │                          │
│                    ┌──────────────────┼──────────────────┐      │
│                    │                  │                  │      │
│                    ▼                  ▼                  ▼      │
│              ┌──────────┐      ┌──────────┐      ┌──────────┐  │
│              │ Interested│     │ Questions│      │ Decline  │  │
│              │ (action)  │     │ (answer) │      │ (close)  │  │
│              └──────────┘      └──────────┘      └──────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Context Parameters

```json
{
  "delivery_type": "product_launch | contract_renewal | event_invite | announcement",
  "message_content": {
    "product_launch": {
      "product": "FortiOS 8.0",
      "feature": "agentic AI security",
      "date": "next month",
      "offer": "preview webinar"
    },
    "contract_renewal": {
      "contract_type": "FortiGate support",
      "expiry_date": "March 15, 2026",
      "action": "renewal quote"
    },
    "event_invite": {
      "event_name": "SLED Roundtable",
      "event_date": "March 20, 2026",
      "event_location": "Phoenix",
      "topic": "AI-powered security"
    }
  }
}
```

### 8.3 Page: Start

**Entry Fulfillment:**
```
Hi $contact_name, this is a quick call from Fortinet.
```

**Routes:**

| Intent | Target Page |
|--------|-------------|
| * | Deliver Message |

### 8.4 Page: Deliver Message

**Entry Fulfillment:** (varies by delivery_type)

**Product Launch:**
```
I wanted to let you know about $product. It launches $date 
with $feature. If you're interested in seeing a preview, 
we're hosting a webinar on $webinar_date. 
Would you like me to send you the link?
```

**Contract Renewal:**
```
I'm reaching out because your $contract_type expires on $expiry_date. 
I wanted to make sure you have time to budget for renewal. 
Should I have our partner send you a quote?
```

**Event Invite:**
```
We're hosting a $event_name in $event_location on $event_date 
to discuss $topic. Several IT leaders from nearby $account_type 
are attending. Would you be interested in joining us?
```

**Announcement:**
```
I have a quick update for you. $announcement_content
Any questions about that?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| express_interest | Action Handler | - |
| confirmation.yes | Action Handler | - |
| ask_question | Gemini Handler | [Webhook: gemini-responder] |
| express_disinterest | Soft Close | - |
| confirmation.no | Soft Close | - |

### 8.5 Page: Action Handler

**Entry Fulfillment:** (varies by delivery_type)

**Product Launch (webinar signup):**
```
Great! What email should I send the webinar link to?
```
→ Collect email → Send registration → End Session

**Contract Renewal (quote request):**
```
Perfect. I'll have our partner High Point Networks reach out 
with a quote. Is $contact_email still the best email?
```
→ Confirm email → Create Salesforce task → End Session

**Event Invite (RSVP):**
```
Excellent! I'll register you. Will it just be you, or will 
you be bringing anyone from your team?
```
→ Capture attendee count → Register → Send confirmation → End Session

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| provide_information | Confirm Action | - |

### 8.6 Page: Soft Close

**Entry Fulfillment:**
```
No problem at all. Can I ask – is there anything else 
we can help you with? Any questions about your current 
Fortinet setup?
```

**Routes:**

| Intent | Target Page | Fulfillment |
|--------|-------------|-------------|
| express_interest | Gemini Handler | - |
| ask_question | Gemini Handler | [Webhook: gemini-responder] |
| confirmation.no | End Session | "Thanks for your time, $contact_name. Have a great day!" |

---

## 9. Common Handlers

### 9.1 Gemini Handler (Fallback)

**Purpose:** Handle any response Dialogflow can't classify with high confidence

**Entry:** (none - webhook handles response)

**Webhook:** `gemini-responder`

**Request to Gemini:**
```json
{
  "user_utterance": "$input",
  "conversation_history": [
    {"role": "bot", "text": "$previous_bot_message"},
    {"role": "human", "text": "$input"}
  ],
  "context": {
    "use_case": "$use_case",
    "conversation_goal": "$conversation_goal",
    "account_name": "$account_name",
    "contact_name": "$contact_name",
    "current_system": "$current_system",
    "pain_points": "$pain_points"
  },
  "instructions": "Generate a natural, conversational response that advances toward $conversation_goal. Keep response under 50 words."
}
```

**Response Handling:**
- If Gemini returns a question → Stay in Gemini Handler
- If Gemini detects interest → Route to appropriate flow
- If Gemini detects objection → Route to Handle Objection
- If Gemini detects opt-out → Route to Opt Out Handler

### 9.2 No Input Handler

**Trigger:** Silence for >5 seconds

**Page: No Input 1**
```
I didn't catch that. Are you still there?
```
→ Wait for response → If response, continue flow

**Page: No Input 2** (second silence)
```
Hello? I think we might have a bad connection.
```
→ Wait for response → If response, continue flow

**Page: No Input 3** (third silence)
```
It seems like we got disconnected. I'll try calling back 
at a better time. Have a great day.
```
→ End Session with outcome = "disconnected"

### 9.3 Speech Error Handler

**Trigger:** Low confidence speech recognition

**Fulfillment:**
```
Sorry, I didn't catch that. Could you repeat that for me?
```

**Alternative Fulfillment (after 2 tries):**
```
I'm having trouble hearing you. Let me ask a different way. 
[Rephrase question]
```

### 9.4 Call Length Monitor

**Trigger:** Call duration > 8 minutes

**Fulfillment:**
```
I appreciate you taking the time to chat. I want to be 
respectful of your time. Can I schedule a follow-up call 
to continue this conversation?
```
→ Route to Schedule Callback or End Session

---

## 10. Gemini Integration Points

### 10.1 When to Use Gemini

| Scenario | Dialogflow | Gemini |
|----------|------------|--------|
| Yes/No response | ✓ | |
| Time preference | ✓ | |
| Email address | ✓ | |
| Objection handling | | ✓ |
| Open-ended question | | ✓ |
| Complex explanation | | ✓ |
| Competitive discussion | | ✓ |
| Custom pain point | | ✓ |
| Unexpected topic | | ✓ |

### 10.2 Gemini Prompt Template

```
You are Paul, a friendly sales representative from Fortinet calling 
a prospect in the SLED (government/education) sector.

Current situation:
- You're speaking with $contact_name ($contact_title) from $account_name
- Goal: $conversation_goal
- They use: $current_system
- Pain points mentioned: $pain_points

The caller just said: "$user_utterance"

Generate a natural, conversational response that:
1. Acknowledges what they said
2. Keeps them engaged
3. Moves toward the goal: $conversation_goal
4. Sounds human, not robotic
5. Is under 50 words (phone-friendly)

If they asked a question you can't answer, offer to send information 
or schedule a call with a technical expert.

If they seem not interested, acknowledge gracefully and offer to 
follow up later.

Response:
```

### 10.3 Gemini Response Processing

```javascript
function processGeminiResponse(response, context) {
  // Clean response for TTS
  let cleanResponse = response
    .replace(/[*_~`]/g, '')  // Remove markdown
    .replace(/\n/g, ' ')     // Single line
    .replace(/\s+/g, ' ')    // Normalize spaces
    .trim();
  
  // Add SSML for natural pacing
  let ssmlResponse = `<speak>${cleanResponse}</speak>`;
  
  // Detect sentiment for routing
  const sentiment = analyzeSentiment(response);
  
  return {
    text: cleanResponse,
    ssml: ssmlResponse,
    suggestedNextPage: getSuggestedPage(sentiment, context)
  };
}
```

### 10.4 Gemini Error Handling

| Error | Fallback Response |
|-------|-------------------|
| Timeout (>3s) | "Let me think about that for a second..." + retry once |
| Rate limit | Use template response based on context |
| Content filter | "That's a great question. Let me have someone follow up with you on that." |
| Parse error | "I want to make sure I give you accurate information. Can I have someone call you back to discuss that?" |

---

## Document Control

**Author:** AI Voice Caller Subagent  
**Created:** 2026-02-10  
**Status:** Ready for Implementation  
**Next Steps:** Build intents and entities in Dialogflow CX console
