# Territory Targeting Directive

## Purpose
Define the Arizona SLED (State/Local/Education) territory targeting strategy for Fortinet UC/phone system prospecting via AI-powered outbound calling.

## Segment Strategy

### 1. K-12 School Districts (Primary Target)
**Why:** K-12 districts are the #1 opportunity because of E-Rate funding. The federal E-Rate program subsidizes 20-90% of telecom/networking costs for schools. Districts running legacy Cisco phone systems (most of them) are prime candidates for Fortinet FortiVoice replacement.

**Approach:** Call main district office, ask for Technology Director or CIO. The AI agent runs in discovery mode -- "who handles your phone systems and network infrastructure?"

**Target profile:**
- Arizona districts with 10k+ students (largest budgets)
- E-Rate eligible (all K-12 qualifies)
- Likely running aging Cisco UC infrastructure
- Decision cycle: budget approval in spring for summer deployment

### 2. Community Colleges
**Why:** Large user counts (faculty + staff + labs), E-Rate eligible for telecom, multi-campus deployments mean big deals. Maricopa Community College District alone has 10 campuses.

**Approach:** Similar to K-12 but target CIO/VP of IT. Community colleges have more centralized IT than K-12 districts.

### 3. County/City Government (Maricopa County Focus)
**Why:** Government refresh cycles create predictable replacement windows. Cities over 100k population have dedicated IT departments and meaningful telecom budgets. Not E-Rate eligible but funded through municipal budgets.

**Approach:** Call main city line, ask to be transferred to IT department or the person who manages phone systems/network infrastructure.

### 4. State Agencies & Universities
**Why:** State-level deals are whale accounts. Arizona Department of Administration controls state IT procurement. Universities have massive user counts and dedicated IT budgets.

**Approach:** Target CTO/CIO offices. Universities are E-Rate eligible for telecom services.

## E-Rate Opportunity
E-Rate is the single biggest differentiator for education targets:
- Category 1: Telecom services and internet access (20-90% discount)
- Category 2: Internal connections (switches, routers, wireless, etc.)
- Filing window: typically Jan-Mar for following fiscal year
- Fortinet FortiVoice + FortiSwitch + FortiAP qualify under both categories
- Positioning: "We can help you maximize your E-Rate funding while modernizing your infrastructure"

## CSV Format

The campaign CSV (campaigns/arizona-sled-targets.csv) feeds directly into campaign_runner.py:

    phone,name,account,notes,segment,erate_eligible,estimated_users
    +16024721000,Technology Director,Mesa Public Schools,60k students - largest AZ district,K12,yes,5000

**Columns:**
- phone: E.164 format, publicly listed main office number
- name: Contact name or title ("Technology Director" if name unknown)
- account: Organization name
- notes: Context for the AI agent during the call
- segment: K12, community_college, city_govt, county_govt, state_govt, higher_ed
- erate_eligible: yes/no -- affects pitch angle
- estimated_users: Approximate phone/network users (sizing info)

## How It Feeds Into campaign_runner.py

1. campaign_runner.py reads the CSV
2. For each row, it initiates an outbound call via SignalWire Compatibility API
3. The AI agent uses notes and segment to tailor the conversation
4. For E-Rate eligible targets, the agent leads with funding angle
5. For government targets, the agent leads with security/compliance angle
6. All calls log to Firestore (call_logs collection) with the account/segment data

## How to Add More Targets

1. Research the target organization on their official website
2. Find the publicly listed main office phone number
3. Identify IT leadership names if possible (district website staff directories, LinkedIn)
4. Add a row to campaigns/arizona-sled-targets.csv
5. Use the correct segment tag and E-Rate eligibility
6. Estimate user count from enrollment data or employee counts

## Expansion Roadmap

After Arizona is proven:
1. **Nevada SLED** -- Clark County School District (300k students), Las Vegas metro cities
2. **New Mexico SLED** -- Albuquerque Public Schools, state agencies
3. **Utah SLED** -- Granite School District, Salt Lake County cities
4. **Colorado SLED** -- Denver metro districts, state agencies

## Current Territory Stats
- **Total targets:** 35
- **K-12 districts:** 15
- **Community colleges:** 4
- **City/county government:** 11
- **State agencies:** 2
- **Higher education:** 3
- **E-Rate eligible:** 22 (63%)
