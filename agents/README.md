# AI Voice Caller Agents

SignalWire-based AI agents for automated calling workflows.

## Agents

### 1. Discovery Agent (`discovery_agent.py`)
**Purpose:** Collect IT contact information from organization main lines.

**Flow:**
1. Greets person who answers
2. Identifies as Paul from Fortinet
3. Asks for IT contact name and direct number
4. Confirms information
5. Logs to Firestore

**Port:** 3000

### 2. Lead Qualification Agent (`lead_qualification_agent.py`)
**Purpose:** BANT-based lead scoring and intelligent routing.

**Flow:**
1. Introduction and permission
2. Discovery questions (current system, user count, timeline, pain points)
3. BANT scoring (Budget, Authority, Need, Timeline)
4. Intelligent routing:
   - **Hot leads (70+):** Book meeting → Create Salesforce opportunity → Route to Samson
   - **Warm leads (40-69):** Send information → Schedule follow-up
   - **Cold leads (<40):** Graceful exit → Add to nurture campaign

**Port:** 3001

**BANT Scoring Matrix:**

| Criterion | Points | Triggers |
|-----------|--------|----------|
| **Need** | 0-30 | Pain points (5 each, max 15), System age 7+ years (+10), Legacy system (+5) |
| **Timeline** | 0-25 | Within 3 months (+25), Within 6 months (+20), Within 12 months (+10) |
| **Budget** | 0-25 | 500+ users (+15), 100-499 users (+10), 25-99 users (+5), E-Rate eligible (+10) |
| **Authority** | 0-20 | Decision maker (+20), Influencer (+10), Recommender (+10) |

**SWAIG Functions:**
- `score_lead()` - Calculate BANT score
- `create_salesforce_opp()` - Create opportunity for hot leads
- `route_to_sales()` - Route hot lead to Samson
- `log_qualified_lead()` - Log full conversation context
- `disqualify_lead()` - Gracefully handle unqualified leads

## Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install signalwire-agents google-cloud-firestore
```

## Testing

```bash
# Activate venv
source venv/bin/activate

# Run lead qualification tests
python3 agents/test_lead_qualification.py
```

## Deployment

### Discovery Agent
```bash
source venv/bin/activate
python3 agents/discovery_agent.py
# Listens on port 3000
```

### Lead Qualification Agent
```bash
source venv/bin/activate
python3 agents/lead_qualification_agent.py
# Listens on port 3001
```

### SignalWire Configuration
1. Log in to SignalWire dashboard
2. Go to Phone Numbers
3. Configure webhook URL:
   - Discovery: `http://YOUR_SERVER:3000/`
   - Lead Qualification: `http://YOUR_SERVER:3001/`

## Data Storage

### Firestore Collections

#### `discovered-contacts`
- Raw contact data from discovery calls
- Fields: `contact_name`, `phone_number`, `organization`, `timestamp`

#### `qualified-leads`
- Full lead qualification data with BANT scores
- Fields: `account_name`, `contact_name`, `current_system`, `user_count`, `timeline`, `pain_points`, `lead_score`, `qualification`

#### `salesforce-opportunities`
- Hot leads that need Salesforce sync
- Fields: `account_name`, `opportunity_name`, `lead_score`, `stage`, `pain_points`

#### `hot-leads`
- High-priority leads requiring immediate follow-up
- Fields: `account_name`, `contact_name`, `lead_score`, `urgency`, `notes`, `routed_to`

#### `disqualified-leads`
- Leads that don't meet criteria (for future nurture)
- Fields: `contact_name`, `reason`, `follow_up_timeline`

## E-Rate Support

The Lead Qualification Agent has specialized E-Rate handling:
- Detects K-12 organizations
- Asks about E-Rate funding (+10 points if eligible)
- Routes to E-Rate specialists for qualified leads
- Understands E-Rate buying cycles and timelines

## Conversation Best Practices

### Discovery Questions
✅ "What phone system are you using today?"
✅ "How many phone users do you have?"
✅ "What's the biggest challenge with your current setup?"

❌ "Do you want to buy from us?"
❌ "Can I send you a quote?"
❌ "When can we meet?"

### Buying Signals to Watch For
- "We're actively looking"
- "Contract expires soon"
- "We're having problems with..."
- "What would this cost?"
- "Do you have a case study?"

### Disqualification Triggers
- Just renewed 3+ year contract
- No budget whatsoever
- Wrong person (and can't refer)
- "Stop calling" (immediate opt-out)

## Monitoring

Monitor agent performance via:
- Firestore collections (real-time data)
- SignalWire dashboard (call logs, recordings)
- Lead score distribution (track qualification rates)

## Troubleshooting

### Agent won't start
```bash
# Check port availability
lsof -i :3000
lsof -i :3001

# Kill conflicting process
kill -9 <PID>
```

### Firestore connection issues
```bash
# Verify Google Cloud credentials
gcloud auth application-default login

# Check project ID
gcloud config get-value project
```

### SWAIG functions not working
- Check function signatures match SDK requirements
- Verify `@AgentBase.tool` decorator is present
- Check SignalWire logs for function call errors

## Next Steps

1. **Production Deployment:** Deploy to server with public IP
2. **Webhook Configuration:** Point SignalWire number to agent URL
3. **Live Testing:** Make test calls to validate flows
4. **Monitoring Setup:** Configure alerts for hot leads
5. **Salesforce Integration:** Complete opportunity sync
6. **CRM Integration:** Auto-create tasks for follow-ups

## Version History

- **v1.0.0** (2026-02-11): Initial release
  - Discovery Agent: Basic contact collection
  - Lead Qualification Agent: BANT scoring with E-Rate support
  - Full test suite with 100% pass rate
