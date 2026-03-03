# Lead Scorer Cloud Function

Scores leads 0-10 based on conversation content, engagement signals, and account attributes.

## Overview

This function combines rule-based scoring with AI analysis to qualify leads from voice calls:
- **Rule-based**: Fast, consistent, based on keyword patterns
- **AI-enhanced**: Nuanced understanding via Gemini

## Scoring System

### Score Categories

| Score | Category | Next Action |
|-------|----------|-------------|
| 9-10 | Hot | Schedule demo immediately |
| 7-8 | Warm | Send follow-up email |
| 5-6 | Qualified | Add to nurture campaign |
| 3-4 | Neutral | Follow up in 90 days |
| 1-2 | Cool | Low priority nurture |
| 0 | Cold | Do not contact |

### Signal Detection

**Positive Signals:**
- Expressed interest (+3)
- Asked multiple questions (+2)
- Mentioned timeline (+3)
- Discussed budget (+3)
- Has legacy system (+2)
- Large organization (+2)

**Negative Signals:**
- Not interested (-5)
- Has existing vendor (-2)
- No decision authority (-2)
- Requested DNC (-10)

## API Usage

### Score from Transcript

```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": [
      {"role": "bot", "text": "What phone system are you using?"},
      {"role": "user", "text": "We have an old Cisco system, probably 8 years old. We are looking to replace it next year."}
    ],
    "accountData": {
      "accountName": "Cityville School District",
      "accountType": "K12",
      "employeeCount": 150
    }
  }'
```

### Score by Session ID

```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "call-123"
  }'
```

### Disable AI Scoring

```bash
curl -X POST https://FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": [...],
    "useAI": false
  }'
```

## Response Format

```json
{
  "success": true,
  "score": 8,
  "category": "warm",
  "signals": [
    "Mentioned timeline",
    "Has legacy system",
    "Large organization"
  ],
  "nextAction": "Send follow-up email with case study",
  "reasoning": "Contact mentioned timeline for next year replacement and has old Cisco system. Large K12 district indicates good potential deal size.",
  "ruleBasedScore": {
    "score": 7,
    "signals": [...]
  },
  "aiEnhanced": true
}
```

## Customizing Scoring

### Add New Signals

Edit `SIGNAL_PATTERNS` in `index.js`:

```javascript
const SIGNAL_PATTERNS = {
  // Add new pattern
  urgency: [
    /\bimmediate\b/i,
    /\basap\b/i,
    /\bright away\b/i
  ]
};
```

### Adjust Weights

Edit `SCORING_CONFIG` in `index.js`:

```javascript
const SCORING_CONFIG = {
  engagement: {
    multipleQuestions: 3,  // Increase weight
    // ...
  }
};
```

## Deployment

```bash
./deploy.sh
```

## Dialogflow Integration

Call at end of conversation:

```json
{
  "sessionId": "$session.params.session_id",
  "accountData": {
    "accountName": "$session.params.account_name",
    "employeeCount": "$session.params.employee_count"
  }
}
```

Use the score to:
- Route to different end pages
- Trigger appropriate follow-up actions
- Update Salesforce lead status

## Analytics Queries

```sql
-- Score distribution
SELECT 
  category,
  COUNT(*) as count,
  AVG(score) as avg_score
FROM `tatt-pro.voice_caller.lead_scores`
GROUP BY category;

-- Top signals
SELECT 
  signal,
  COUNT(*) as frequency
FROM `tatt-pro.voice_caller.lead_scores`,
UNNEST(signals) as signal
GROUP BY signal
ORDER BY frequency DESC;
```

## Troubleshooting

### Low AI accuracy
- Check transcript quality
- Provide more account context
- Consider training custom model

### Scoring too high/low
- Adjust `SCORING_CONFIG` weights
- Add more signal patterns
- Review false positives/negatives

## License

MIT
