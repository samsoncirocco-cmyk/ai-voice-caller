/**
 * Lead Scorer Cloud Function
 * 
 * Scores leads based on conversation content, engagement signals,
 * and account attributes. Returns a score 0-10 with reasoning.
 * 
 * @author AI Voice Caller Team
 * @version 1.0.0
 */

const functions = require('@google-cloud/functions-framework');
const { VertexAI } = require('@google-cloud/vertexai');
const { Firestore } = require('@google-cloud/firestore');

// Configuration
const PROJECT_ID = process.env.GCP_PROJECT || 'tatt-pro';
const LOCATION = process.env.GCP_LOCATION || 'us-central1';
const MODEL_ID = process.env.GEMINI_MODEL || 'gemini-1.5-flash';

// Scoring weights
const SCORING_CONFIG = {
  // Engagement signals (conversation quality)
  engagement: {
    multipleQuestions: 2,      // Asked multiple questions
    requestedMoreInfo: 2,      // Asked for more information
    mentionedTimeline: 3,      // Mentioned purchase timeline
    discussedBudget: 3,        // Discussed budget
    longConversation: 1,       // >2 minutes
    shortConversation: -2,     // <30 seconds
  },
  
  // Interest signals (explicit interest)
  interest: {
    expressedInterest: 3,      // Said interested, curious, etc.
    agreedToMeeting: 4,        // Scheduled meeting
    agreedToEmail: 2,          // Agreed to receive info
    askedAboutPricing: 2,      // Price/cost questions
    askedAboutFeatures: 2,     // Feature questions
  },
  
  // Negative signals
  negative: {
    notInterested: -5,         // Explicitly not interested
    alreadyHasVendor: -2,      // Has competing solution
    noDecisionAuthority: -2,   // Not the decision maker
    badTiming: -1,             // Not now but maybe later
    doNotCall: -10,            // Requested DNC
  },
  
  // Account attributes
  account: {
    largeOrg: 2,               // 100+ employees
    mediumOrg: 1,              // 25-99 employees
    legacySystem: 2,           // Old phone system
    activeRfp: 4,              // In RFP process
    recentPurchase: -3,        // Bought recently
  }
};

// Keywords for signal detection
const SIGNAL_PATTERNS = {
  interested: [
    /\binterested\b/i,
    /\bcurious\b/i,
    /\btell me more\b/i,
    /\bsounds good\b/i,
    /\bthat's interesting\b/i,
    /\bi'd like to\b/i
  ],
  notInterested: [
    /\bnot interested\b/i,
    /\bno thanks\b/i,
    /\bremove me\b/i,
    /\bdon't call\b/i,
    /\bbusy\b/i,
    /\bwaste of time\b/i
  ],
  timeline: [
    /\bthis year\b/i,
    /\bnext year\b/i,
    /\bthis quarter\b/i,
    /\bnext month\b/i,
    /\bbudget cycle\b/i,
    /\bplanning\b/i,
    /\bevaluating\b/i
  ],
  budget: [
    /\bbudget\b/i,
    /\bprice\b/i,
    /\bcost\b/i,
    /\bafford\b/i,
    /\bfunding\b/i,
    /\bgrant\b/i,
    /\be-rate\b/i
  ],
  questions: [
    /\?$/m,
    /\bwhat about\b/i,
    /\bhow does\b/i,
    /\bcan you\b/i,
    /\bdo you\b/i
  ],
  competitor: [
    /\bcisco\b/i,
    /\bavaya\b/i,
    /\bmicrosoft teams\b/i,
    /\bzoom phone\b/i,
    /\bring ?central\b/i,
    /\b8x8\b/i,
    /\bgoto\b/i
  ],
  legacy: [
    /\bold system\b/i,
    /\bpbx\b/i,
    /\banalog\b/i,
    /\b(5|6|7|8|9|10)\+ years\b/i,
    /\blegacy\b/i,
    /\bending support\b/i
  ]
};

// Lazy clients
let vertexAI = null;
let firestore = null;

function getVertexAI() {
  if (!vertexAI) {
    vertexAI = new VertexAI({ project: PROJECT_ID, location: LOCATION });
  }
  return vertexAI;
}

function getFirestore() {
  if (!firestore) {
    firestore = new Firestore({ projectId: PROJECT_ID });
  }
  return firestore;
}

/**
 * Validate request
 */
function validateRequest(body) {
  const errors = [];
  
  if (!body) {
    return { valid: false, errors: ['Request body required'] };
  }
  
  if (!body.transcript && !body.sessionId) {
    errors.push('Either transcript or sessionId is required');
  }
  
  return { valid: errors.length === 0, errors };
}

/**
 * Extract text from transcript
 */
function getTranscriptText(transcript) {
  if (typeof transcript === 'string') {
    return transcript;
  }
  
  if (Array.isArray(transcript)) {
    return transcript
      .filter(t => t.role === 'user' || t.role === 'caller')
      .map(t => t.text)
      .join(' ');
  }
  
  return '';
}

/**
 * Count pattern matches in text
 */
function countMatches(text, patterns) {
  let count = 0;
  for (const pattern of patterns) {
    const matches = text.match(pattern);
    if (matches) {
      count += matches.length;
    }
  }
  return count;
}

/**
 * Calculate rule-based score
 */
function calculateRuleScore(transcript, accountData = {}) {
  const text = getTranscriptText(transcript);
  const signals = [];
  let score = 5; // Start at neutral
  
  // Engagement signals
  const questionCount = countMatches(text, SIGNAL_PATTERNS.questions);
  if (questionCount >= 3) {
    score += SCORING_CONFIG.engagement.multipleQuestions;
    signals.push({ signal: 'Multiple questions asked', points: SCORING_CONFIG.engagement.multipleQuestions });
  }
  
  // Interest signals
  if (SIGNAL_PATTERNS.interested.some(p => p.test(text))) {
    score += SCORING_CONFIG.interest.expressedInterest;
    signals.push({ signal: 'Expressed interest', points: SCORING_CONFIG.interest.expressedInterest });
  }
  
  // Timeline mentioned
  if (SIGNAL_PATTERNS.timeline.some(p => p.test(text))) {
    score += SCORING_CONFIG.engagement.mentionedTimeline;
    signals.push({ signal: 'Mentioned timeline', points: SCORING_CONFIG.engagement.mentionedTimeline });
  }
  
  // Budget/pricing mentioned
  if (SIGNAL_PATTERNS.budget.some(p => p.test(text))) {
    score += SCORING_CONFIG.engagement.discussedBudget;
    signals.push({ signal: 'Discussed budget/pricing', points: SCORING_CONFIG.engagement.discussedBudget });
  }
  
  // Legacy system mentioned
  if (SIGNAL_PATTERNS.legacy.some(p => p.test(text))) {
    score += SCORING_CONFIG.account.legacySystem;
    signals.push({ signal: 'Has legacy system', points: SCORING_CONFIG.account.legacySystem });
  }
  
  // Negative signals
  if (SIGNAL_PATTERNS.notInterested.some(p => p.test(text))) {
    score += SCORING_CONFIG.negative.notInterested;
    signals.push({ signal: 'Not interested', points: SCORING_CONFIG.negative.notInterested });
  }
  
  // Competitor mentioned (neutral to slightly negative)
  if (SIGNAL_PATTERNS.competitor.some(p => p.test(text))) {
    score += SCORING_CONFIG.negative.alreadyHasVendor;
    signals.push({ signal: 'Has existing vendor', points: SCORING_CONFIG.negative.alreadyHasVendor });
  }
  
  // Account attributes
  if (accountData.employeeCount >= 100) {
    score += SCORING_CONFIG.account.largeOrg;
    signals.push({ signal: 'Large organization', points: SCORING_CONFIG.account.largeOrg });
  } else if (accountData.employeeCount >= 25) {
    score += SCORING_CONFIG.account.mediumOrg;
    signals.push({ signal: 'Medium organization', points: SCORING_CONFIG.account.mediumOrg });
  }
  
  if (accountData.activeRfp) {
    score += SCORING_CONFIG.account.activeRfp;
    signals.push({ signal: 'Active RFP', points: SCORING_CONFIG.account.activeRfp });
  }
  
  // Clamp score to 0-10
  score = Math.max(0, Math.min(10, score));
  
  return { score, signals };
}

/**
 * Use Gemini for nuanced scoring
 */
async function calculateAIScore(transcript, accountData = {}) {
  const ai = getVertexAI();
  const model = ai.getGenerativeModel({
    model: MODEL_ID,
    generationConfig: {
      maxOutputTokens: 500,
      temperature: 0.3
    }
  });
  
  const text = getTranscriptText(transcript);
  
  const prompt = `You are a sales qualification expert. Score this lead 0-10 based on the conversation.

ACCOUNT INFO:
- Name: ${accountData.accountName || 'Unknown'}
- Type: ${accountData.accountType || 'Unknown'}
- Size: ${accountData.employeeCount || 'Unknown'} employees
- Current System: ${accountData.currentSystem || 'Unknown'}

CONVERSATION TRANSCRIPT:
${text}

SCORING CRITERIA:
10: Hot lead - Explicitly interested, asked for meeting, has budget and timeline
8-9: Warm lead - Positive signals, engaged, asked questions
6-7: Qualified - Some interest, worth following up
4-5: Neutral - Not much signal either way
2-3: Cool lead - Some negative signals but not closed
0-1: Cold/Dead - Explicitly not interested, do not call

Respond in JSON format:
{
  "score": <number 0-10>,
  "category": "<hot|warm|qualified|neutral|cool|cold>",
  "signals": ["<positive or negative signal>", ...],
  "nextAction": "<recommended next action>",
  "reasoning": "<brief explanation>"
}`;

  try {
    const result = await model.generateContent(prompt);
    const responseText = result.response.candidates?.[0]?.content?.parts?.[0]?.text || '';
    
    // Extract JSON from response
    const jsonMatch = responseText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      return JSON.parse(jsonMatch[0]);
    }
  } catch (error) {
    console.error('AI scoring error:', error);
  }
  
  return null;
}

/**
 * Get conversation from Firestore by session ID
 */
async function getConversation(sessionId) {
  const db = getFirestore();
  const doc = await db.collection('calls').doc(sessionId).get();
  
  if (!doc.exists) {
    return null;
  }
  
  return doc.data();
}

/**
 * Store score in Firestore
 */
async function storeScore(sessionId, scoreData) {
  const db = getFirestore();
  await db.collection('lead_scores').doc(sessionId).set({
    ...scoreData,
    sessionId,
    timestamp: new Date()
  });
  
  // Also update the call record
  await db.collection('calls').doc(sessionId).update({
    leadScore: scoreData.score,
    leadCategory: scoreData.category
  });
}

/**
 * Main HTTP handler
 */
functions.http('scoreLead', async (req, res) => {
  // CORS
  res.set('Access-Control-Allow-Origin', '*');
  res.set('Access-Control-Allow-Methods', 'POST');
  res.set('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.status(204).send('');
    return;
  }
  
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }
  
  try {
    const validation = validateRequest(req.body);
    if (!validation.valid) {
      res.status(400).json({
        error: 'Invalid request',
        details: validation.errors
      });
      return;
    }
    
    let transcript = req.body.transcript;
    let accountData = req.body.accountData || {};
    const sessionId = req.body.sessionId;
    const useAI = req.body.useAI !== false; // Default to true
    
    // If session ID provided, fetch from Firestore
    if (sessionId && !transcript) {
      const callData = await getConversation(sessionId);
      if (!callData) {
        res.status(404).json({ error: 'Session not found' });
        return;
      }
      transcript = callData.transcript;
      accountData = {
        accountName: callData.accountName,
        accountType: callData.metadata?.accountType,
        ...accountData
      };
    }
    
    // Calculate rule-based score
    const ruleScore = calculateRuleScore(transcript, accountData);
    
    // Optionally get AI score
    let aiScore = null;
    if (useAI) {
      aiScore = await calculateAIScore(transcript, accountData);
    }
    
    // Combine scores (prefer AI if available)
    const finalScore = aiScore || {
      score: ruleScore.score,
      category: getCategory(ruleScore.score),
      signals: ruleScore.signals.map(s => s.signal),
      nextAction: getNextAction(ruleScore.score),
      reasoning: `Rule-based scoring with ${ruleScore.signals.length} signals detected`
    };
    
    // Store score if session ID provided
    if (sessionId) {
      await storeScore(sessionId, finalScore);
    }
    
    console.log(`Lead scored: ${finalScore.score}/10 (${finalScore.category})`);
    
    res.json({
      success: true,
      ...finalScore,
      ruleBasedScore: ruleScore,
      aiEnhanced: !!aiScore
    });
    
  } catch (error) {
    console.error('Lead scoring error:', error);
    
    res.status(500).json({
      error: 'Failed to score lead',
      message: error.message
    });
  }
});

/**
 * Map score to category
 */
function getCategory(score) {
  if (score >= 9) return 'hot';
  if (score >= 7) return 'warm';
  if (score >= 5) return 'qualified';
  if (score >= 3) return 'neutral';
  if (score >= 1) return 'cool';
  return 'cold';
}

/**
 * Get recommended next action
 */
function getNextAction(score) {
  if (score >= 8) return 'Schedule demo immediately';
  if (score >= 6) return 'Send follow-up email with case study';
  if (score >= 4) return 'Add to nurture campaign';
  if (score >= 2) return 'Follow up in 90 days';
  return 'Add to do-not-call list';
}

// Export for testing
module.exports = {
  validateRequest,
  getTranscriptText,
  calculateRuleScore,
  getCategory,
  getNextAction,
  SCORING_CONFIG,
  SIGNAL_PATTERNS
};
