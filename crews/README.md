# Voice Campaign Crew

**Automated outbound calling with CrewAI orchestration**

## Overview

Voice Campaign Crew is a CrewAI-powered system that automates end-to-end outbound calling campaigns:

1. **Lead Scoring** - Prioritize accounts based on pipeline value, E-Rate deadlines, and recent activity
2. **Call Execution** - Place calls via SignalWire AI agents
3. **Follow-up Generation** - Draft personalized emails based on call outcomes
4. **CRM Logging** - Automatically log all activity to Salesforce

## Architecture

### Agents

1. **Lead Scorer Agent**
   - Analyzes Salesforce data and E-Rate filings
   - Calculates priority scores (1-100)
   - Generates ranked call list with talking points

2. **Caller Agent**
   - Orchestrates SignalWire API calls
   - Tracks outcomes: ANSWERED, VOICEMAIL, NO_ANSWER, BUSY, FAILED
   - Respects rate limits (30s between calls, max 20/hour)

3. **Follow-up Agent**
   - Drafts outcome-specific emails:
     - **Answered**: Recap + promised resources
     - **Voicemail**: Soft acknowledgment + value prop
     - **No Answer**: Gentle touch + helpful resource

4. **CRM Agent**
   - Logs calls as Salesforce Task records
   - Creates follow-up tasks with appropriate due dates
   - Updates Account fields (last contact, call outcome)

## Usage

### Quick Start (Dry Run)

```bash
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller/crews
python run.py --dry-run
```

This will:
- Use 5 sample accounts
- Simulate calls (no actual SignalWire calls)
- Generate campaign report
- Save results to `~/.openclaw/workspace/output/voice-campaigns/`

### Use Your Own Account List

```bash
# Save sample format
python run.py --save-sample my_accounts.json

# Edit my_accounts.json with your data

# Run campaign
python run.py --accounts my_accounts.json --dry-run
```

### Live Campaign (Real Calls)

⚠️ **Use with caution!** This will place actual calls via SignalWire.

```bash
python run.py --accounts my_accounts.json --live
```

### Specify Output Directory

```bash
python run.py --accounts my_accounts.json --output ~/campaigns --dry-run
```

## Account List Format

JSON file with array of account objects:

```json
[
  {
    "account_name": "Example School District",
    "salesforce_id": "0011234567890ABC",
    "contact_name": "Jane Doe",
    "title": "CIO",
    "phone": "+14805551234",
    "email": "jane@example.edu",
    "pipeline_value": 75000,
    "days_since_contact": 21,
    "erate_deadline": "2026-03-15",
    "opportunity_stage": "Proposal",
    "industry": "K-12 Education"
  }
]
```

**Required Fields:**
- `account_name`, `contact_name`, `phone`

**Optional Fields:**
- `salesforce_id` - Enables Salesforce intelligence lookup
- `pipeline_value` - Used in priority scoring
- `days_since_contact` - Affects priority
- `erate_deadline` - ISO date string, boosts urgency
- `opportunity_stage` - Affects priority scoring
- `industry` - Used in email personalization

## Call Outcome Handling

| Outcome | Follow-up Email | CRM Task | Retry |
|---------|----------------|----------|-------|
| **ANSWERED** | Recap + resources | "Send demo materials" (today) | No |
| **VOICEMAIL** | Soft acknowledgment | "Follow-up call" (48h) | Yes |
| **NO_ANSWER** | Gentle touch | "Retry call" (24h) | Yes |
| **FAILED** | None | Log error | No |

## Integration Points

### SignalWire
- **Config**: `../config/signalwire.json`
- **Agent**: Cold Caller (`a774d2ee-dac8-4eb2-9832-845536168e52`)
- **Phone**: `+1 (480) 602-4668`

### Salesforce
- **Tools**: `tools/salesforce-intel/`
- **Query**: Uses `TypedSalesforceQuery` for account intelligence
- **Logging**: Creates Task and Follow-up Task records

### E-Rate Parser
- **Tools**: `tools/erate-parser/`
- **Purpose**: Extract deadline urgency for scoring

## Rate Limits

Configured in SignalWire config:
- **Min interval**: 30 seconds between calls
- **Max calls/hour**: 20
- **Max calls/day**: 100
- **Failure cooldown**: 5 minutes after 3 consecutive failures

## Output

Campaign results are saved to:
```
~/.openclaw/workspace/output/voice-campaigns/
├── voice_campaign_20260212_194500_results.json
└── voice_campaign_20260212_194500_report.md
```

**Results JSON** contains:
- Campaign metadata
- Call outcomes
- Follow-up email drafts
- CRM update summary

**Report Markdown** provides:
- Summary statistics
- Crew execution log
- Next steps checklist

## Testing

```bash
# Dry run with sample data
python run.py --dry-run

# Test with custom account list
python run.py --accounts test_accounts.json --dry-run

# Python import test
python -c "from crew import create_voice_campaign_crew; print('✓ Import successful')"
```

## Dependencies

```
crewai
crewai-tools
requests
```

Already installed in workspace Python environment.

## Files

```
crews/
├── __init__.py          # Package exports
├── agents.py            # Agent definitions (4 agents)
├── tasks.py             # Task definitions (4 tasks)
├── tools_wrapper.py     # Tool implementations + collections
├── crew.py              # Main orchestration class
├── run.py               # CLI entry point
└── README.md            # This file
```

## Development

### Adding New Tools

1. Add tool function to `tools_wrapper.py`:
```python
@tool("Tool Name")
def my_tool(param: str) -> str:
    """Tool description"""
    # Implementation
    return json.dumps(result)
```

2. Add to appropriate tool collection:
```python
def get_lead_scorer_tools():
    return [existing_tools..., my_tool]
```

### Modifying Agent Behavior

Edit agent backstory in `agents.py`:
```python
def create_lead_scorer_agent(tools):
    return Agent(
        backstory=dedent("""
            Your updated backstory here...
        """),
        ...
    )
```

### Customizing Email Templates

Modify `draft_followup_email` tool in `tools_wrapper.py`.

## Troubleshooting

**Import errors:**
```bash
# Ensure you're in the crews directory
cd /home/samson/.openclaw/workspace/projects/ai-voice-caller/crews
python run.py --dry-run
```

**SignalWire call failures:**
- Check `../config/signalwire.json` has valid credentials
- Verify Cold Caller agent ID is correct
- Check rate limits aren't exceeded

**Salesforce errors:**
- Ensure `tools/salesforce-intel/` is accessible
- Check SF credentials in environment

## Future Enhancements

- [ ] Real-time call transcription analysis
- [ ] A/B testing different call scripts
- [ ] Multi-language support
- [ ] SMS follow-up option for no-answer
- [ ] Integration with calendar scheduling
- [ ] Sentiment analysis on call outcomes

## License

Internal Fortinet tool - Not for external distribution

---

**Author:** Samson Cooper  
**Created:** 2026-02-12  
**Version:** 1.0.0
