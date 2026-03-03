/**
 * Gemini Responder Cloud Function
 * 
 * Handles intelligent response generation via Vertex AI Gemini
 * for the AI Voice Caller system. This function is called as a
 * Dialogflow CX webhook when the conversation requires dynamic,
 * context-aware responses.
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
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// Rate limiting configuration
const RATE_LIMIT_WINDOW_MS = 60000; // 1 minute
const MAX_REQUESTS_PER_WINDOW = 100;
const requestCounts = new Map();

// Initialize clients lazily
let vertexAI = null;
let firestore = null;

/**
 * Initialize Vertex AI client with lazy loading
 */
function getVertexAI() {
  if (!vertexAI) {
    vertexAI = new VertexAI({
      project: PROJECT_ID,
      location: LOCATION
    });
  }
  return vertexAI;
}

/**
 * Initialize Firestore client with lazy loading
 */
function getFirestore() {
  if (!firestore) {
    firestore = new Firestore({ projectId: PROJECT_ID });
  }
  return firestore;
}

/**
 * Rate limiter - checks if request should be allowed
 * @param {string} sessionId - Unique session identifier
 * @returns {boolean} - True if request is allowed
 */
function checkRateLimit(sessionId) {
  const now = Date.now();
  const key = sessionId || 'global';
  
  // Clean up old entries
  for (const [k, v] of requestCounts.entries()) {
    if (now - v.windowStart > RATE_LIMIT_WINDOW_MS) {
      requestCounts.delete(k);
    }
  }
  
  const entry = requestCounts.get(key);
  if (!entry || now - entry.windowStart > RATE_LIMIT_WINDOW_MS) {
    requestCounts.set(key, { count: 1, windowStart: now });
    return true;
  }
  
  if (entry.count >= MAX_REQUESTS_PER_WINDOW) {
    return false;
  }
  
  entry.count++;
  return true;
}

/**
 * Sleep utility for retry logic
 * @param {number} ms - Milliseconds to sleep
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry wrapper with exponential backoff
 * @param {Function} fn - Function to retry
 * @param {number} maxRetries - Maximum retry attempts
 */
async function withRetry(fn, maxRetries = MAX_RETRIES) {
  let lastError;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      
      // Don't retry on client errors (4xx)
      if (error.code >= 400 && error.code < 500) {
        throw error;
      }
      
      const delay = RETRY_DELAY_MS * Math.pow(2, attempt);
      console.warn(`Attempt ${attempt + 1} failed, retrying in ${delay}ms:`, error.message);
      await sleep(delay);
    }
  }
  
  throw lastError;
}

/**
 * Validate incoming Dialogflow webhook request
 * @param {Object} body - Request body
 * @returns {Object} - Validation result with extracted data
 */
function validateRequest(body) {
  const errors = [];
  
  if (!body) {
    errors.push('Request body is required');
  }
  
  if (!body.sessionInfo) {
    errors.push('sessionInfo is required');
  }
  
  if (!body.text && !body.transcript) {
    errors.push('Either text or transcript is required');
  }
  
  if (errors.length > 0) {
    return { valid: false, errors };
  }
  
  return {
    valid: true,
    data: {
      sessionId: body.sessionInfo?.session || 'unknown',
      text: body.text || body.transcript || '',
      parameters: body.sessionInfo?.parameters || {},
      currentPage: body.pageInfo?.currentPage || 'unknown',
      intentName: body.intentInfo?.displayName || 'unknown'
    }
  };
}

/**
 * Build the Gemini prompt based on conversation context
 * @param {Object} context - Conversation context
 * @returns {string} - Formatted prompt
 */
function buildPrompt(context) {
  const { text, parameters, currentPage, intentName } = context;
  
  // Extract account data
  const accountName = parameters.account_name || 'the prospect';
  const accountType = parameters.account_type || 'organization';
  const currentSystem = parameters.current_system || 'unknown';
  const painPoints = parameters.pain_points || [];
  const conversationHistory = parameters.conversation_history || [];
  const useCase = parameters.use_case || 'cold_calling';
  
  // Build context string
  const historyStr = conversationHistory.length > 0
    ? conversationHistory.slice(-5).map(h => `${h.role}: ${h.text}`).join('\n')
    : 'This is the start of the conversation.';
  
  const painPointsStr = painPoints.length > 0
    ? `Known pain points: ${painPoints.join(', ')}`
    : '';

  return `You are Paul, a Territory Account Manager at Fortinet specializing in voice and network solutions for SLED (State, Local government, Education).

CONTEXT:
- Calling: ${accountName} (${accountType})
- Current phone system: ${currentSystem}
- Current conversation flow: ${useCase}
- Current page: ${currentPage}
- Last detected intent: ${intentName}
${painPointsStr}

CONVERSATION HISTORY:
${historyStr}

CALLER JUST SAID: "${text}"

INSTRUCTIONS:
1. Generate a natural, conversational response
2. Address what they said directly
3. Guide toward booking a meeting OR getting permission to send info
4. Sound human - use contractions, be friendly, match their energy
5. Keep response under 50 words (phone calls need brevity)
6. If they object, acknowledge and pivot gracefully
7. Never be pushy or salesy

RESPONSE:`;
}

/**
 * Generate response using Gemini
 * @param {string} prompt - The prompt to send to Gemini
 * @returns {string} - Generated response
 */
async function generateResponse(prompt) {
  const ai = getVertexAI();
  
  const model = ai.getGenerativeModel({
    model: MODEL_ID,
    generationConfig: {
      maxOutputTokens: 150,
      temperature: 0.7,
      topP: 0.9,
      topK: 40
    },
    safetySettings: [
      {
        category: 'HARM_CATEGORY_HARASSMENT',
        threshold: 'BLOCK_MEDIUM_AND_ABOVE'
      },
      {
        category: 'HARM_CATEGORY_HATE_SPEECH',
        threshold: 'BLOCK_MEDIUM_AND_ABOVE'
      }
    ]
  });
  
  const result = await model.generateContent(prompt);
  const response = result.response;
  
  // Extract text from response
  const text = response.candidates?.[0]?.content?.parts?.[0]?.text || '';
  
  // Clean up the response for TTS
  return cleanForTTS(text);
}

/**
 * Clean text for Text-to-Speech output
 * @param {string} text - Raw text
 * @returns {string} - Cleaned text
 */
function cleanForTTS(text) {
  return text
    .replace(/\*+/g, '') // Remove asterisks (markdown bold)
    .replace(/_+/g, '') // Remove underscores
    .replace(/#+/g, '') // Remove headers
    .replace(/`+/g, '') // Remove code ticks
    .replace(/\n+/g, ' ') // Replace newlines with spaces
    .replace(/\s+/g, ' ') // Normalize whitespace
    .replace(/[^\w\s.,!?'-]/g, '') // Remove special characters
    .trim();
}

/**
 * Log interaction to Firestore for analytics
 * @param {Object} data - Interaction data
 */
async function logInteraction(data) {
  try {
    const db = getFirestore();
    await db.collection('gemini_interactions').add({
      timestamp: new Date(),
      sessionId: data.sessionId,
      userText: data.text,
      generatedResponse: data.response,
      latencyMs: data.latencyMs,
      model: MODEL_ID
    });
  } catch (error) {
    // Log but don't fail the request
    console.error('Failed to log interaction:', error);
  }
}

/**
 * Main HTTP Cloud Function handler
 */
functions.http('geminiRespond', async (req, res) => {
  const startTime = Date.now();
  
  // Set CORS headers
  res.set('Access-Control-Allow-Origin', '*');
  res.set('Access-Control-Allow-Methods', 'POST');
  res.set('Access-Control-Allow-Headers', 'Content-Type');
  
  // Handle preflight
  if (req.method === 'OPTIONS') {
    res.status(204).send('');
    return;
  }
  
  // Only accept POST
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }
  
  try {
    // Validate request
    const validation = validateRequest(req.body);
    if (!validation.valid) {
      console.error('Validation failed:', validation.errors);
      res.status(400).json({
        error: 'Invalid request',
        details: validation.errors
      });
      return;
    }
    
    const context = validation.data;
    
    // Check rate limit
    if (!checkRateLimit(context.sessionId)) {
      console.warn('Rate limit exceeded for session:', context.sessionId);
      res.status(429).json({
        error: 'Rate limit exceeded',
        retryAfter: 60
      });
      return;
    }
    
    // Build prompt and generate response with retry
    const prompt = buildPrompt(context);
    
    const response = await withRetry(async () => {
      return await generateResponse(prompt);
    });
    
    const latencyMs = Date.now() - startTime;
    
    // Log interaction asynchronously (don't await)
    logInteraction({
      sessionId: context.sessionId,
      text: context.text,
      response,
      latencyMs
    });
    
    console.log(`Response generated in ${latencyMs}ms for session ${context.sessionId}`);
    
    // Return Dialogflow webhook response format
    res.json({
      fulfillmentResponse: {
        messages: [{
          text: {
            text: [response]
          }
        }]
      },
      sessionInfo: {
        parameters: {
          last_gemini_response: response,
          conversation_history: [
            ...(context.parameters.conversation_history || []),
            { role: 'user', text: context.text },
            { role: 'bot', text: response }
          ].slice(-10) // Keep last 10 turns
        }
      }
    });
    
  } catch (error) {
    const latencyMs = Date.now() - startTime;
    console.error(`Error after ${latencyMs}ms:`, error);
    
    // Return graceful fallback response
    res.json({
      fulfillmentResponse: {
        messages: [{
          text: {
            text: ["I didn't quite catch that. Could you repeat what you just said?"]
          }
        }]
      }
    });
  }
});

// Export for testing
module.exports = {
  validateRequest,
  buildPrompt,
  cleanForTTS,
  checkRateLimit
};
