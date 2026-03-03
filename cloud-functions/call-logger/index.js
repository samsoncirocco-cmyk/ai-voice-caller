/**
 * Call Logger Cloud Function
 * 
 * Logs all AI voice calls to Firestore for analytics and auditing.
 * Captures transcripts, outcomes, duration, and metadata.
 * 
 * @author AI Voice Caller Team
 * @version 1.0.0
 */

const functions = require('@google-cloud/functions-framework');
const { Firestore } = require('@google-cloud/firestore');
const { BigQuery } = require('@google-cloud/bigquery');

// Configuration
const PROJECT_ID = process.env.GCP_PROJECT || 'tatt-pro';
const COLLECTION_NAME = process.env.COLLECTION_NAME || 'calls';
const BIGQUERY_DATASET = process.env.BIGQUERY_DATASET || 'voice_caller';
const BIGQUERY_TABLE = process.env.BIGQUERY_TABLE || 'call_logs';
const ENABLE_BIGQUERY = process.env.ENABLE_BIGQUERY === 'true';

// Clients (lazy initialized)
let firestore = null;
let bigquery = null;

/**
 * Get Firestore client
 */
function getFirestore() {
  if (!firestore) {
    firestore = new Firestore({ projectId: PROJECT_ID });
  }
  return firestore;
}

/**
 * Get BigQuery client
 */
function getBigQuery() {
  if (!bigquery) {
    bigquery = new BigQuery({ projectId: PROJECT_ID });
  }
  return bigquery;
}

/**
 * Validate request body
 */
function validateRequest(body) {
  const errors = [];
  
  if (!body) {
    return { valid: false, errors: ['Request body required'] };
  }
  
  if (!body.sessionId) {
    errors.push('sessionId is required');
  }
  
  const validActions = ['start', 'update', 'end'];
  if (body.action && !validActions.includes(body.action)) {
    errors.push(`Invalid action. Must be one of: ${validActions.join(', ')}`);
  }
  
  return { valid: errors.length === 0, errors };
}

/**
 * Sanitize transcript for storage
 */
function sanitizeTranscript(transcript) {
  if (!transcript) return [];
  
  if (typeof transcript === 'string') {
    // Parse string transcript into structured format
    return transcript.split('\n')
      .filter(line => line.trim())
      .map(line => {
        const match = line.match(/^(Bot|User|Caller):\s*(.+)$/i);
        if (match) {
          return { role: match[1].toLowerCase(), text: match[2] };
        }
        return { role: 'unknown', text: line };
      });
  }
  
  if (Array.isArray(transcript)) {
    return transcript.map(turn => ({
      role: turn.role || 'unknown',
      text: turn.text || String(turn),
      timestamp: turn.timestamp || null
    }));
  }
  
  return [];
}

/**
 * Calculate call metrics from transcript
 */
function calculateMetrics(transcript) {
  const turns = sanitizeTranscript(transcript);
  
  const metrics = {
    totalTurns: turns.length,
    userTurns: turns.filter(t => t.role === 'user' || t.role === 'caller').length,
    botTurns: turns.filter(t => t.role === 'bot').length,
    avgUserWordsPerTurn: 0,
    avgBotWordsPerTurn: 0
  };
  
  const userWords = turns
    .filter(t => t.role === 'user' || t.role === 'caller')
    .reduce((sum, t) => sum + (t.text?.split(/\s+/).length || 0), 0);
  
  const botWords = turns
    .filter(t => t.role === 'bot')
    .reduce((sum, t) => sum + (t.text?.split(/\s+/).length || 0), 0);
  
  if (metrics.userTurns > 0) {
    metrics.avgUserWordsPerTurn = Math.round(userWords / metrics.userTurns);
  }
  
  if (metrics.botTurns > 0) {
    metrics.avgBotWordsPerTurn = Math.round(botWords / metrics.botTurns);
  }
  
  return metrics;
}

/**
 * Log call start event
 */
async function logCallStart(data) {
  const db = getFirestore();
  
  const callDoc = {
    sessionId: data.sessionId,
    startTime: Firestore.Timestamp.now(),
    endTime: null,
    status: 'in_progress',
    
    // Caller info
    callerPhone: data.callerPhone || null,
    callerName: data.callerName || null,
    accountName: data.accountName || null,
    accountId: data.accountId || null,
    
    // Call context
    useCase: data.useCase || 'cold_calling',
    campaign: data.campaign || null,
    
    // Will be populated during/after call
    transcript: [],
    outcome: null,
    leadScore: null,
    duration: null,
    
    // Metadata
    metadata: {
      phoneNumber: data.fromNumber || null,
      dialedNumber: data.toNumber || null,
      region: data.region || null,
      timezone: data.timezone || null
    },
    
    createdAt: Firestore.Timestamp.now(),
    updatedAt: Firestore.Timestamp.now()
  };
  
  await db.collection(COLLECTION_NAME).doc(data.sessionId).set(callDoc);
  
  console.log(`Call started: ${data.sessionId}`);
  return { id: data.sessionId, status: 'in_progress' };
}

/**
 * Update call with new transcript entries
 */
async function updateCall(data) {
  const db = getFirestore();
  const docRef = db.collection(COLLECTION_NAME).doc(data.sessionId);
  
  const updateData = {
    updatedAt: Firestore.Timestamp.now()
  };
  
  if (data.transcript) {
    // Append to existing transcript
    updateData.transcript = Firestore.FieldValue.arrayUnion(
      ...sanitizeTranscript(data.transcript)
    );
  }
  
  if (data.currentPage) {
    updateData['metadata.currentPage'] = data.currentPage;
  }
  
  if (data.detectedIntent) {
    updateData['metadata.lastIntent'] = data.detectedIntent;
  }
  
  await docRef.update(updateData);
  
  console.log(`Call updated: ${data.sessionId}`);
  return { id: data.sessionId, status: 'updated' };
}

/**
 * Log call end event
 */
async function logCallEnd(data) {
  const db = getFirestore();
  const docRef = db.collection(COLLECTION_NAME).doc(data.sessionId);
  
  // Get existing doc to calculate duration
  const doc = await docRef.get();
  const existingData = doc.exists ? doc.data() : {};
  
  const endTime = Firestore.Timestamp.now();
  const startTime = existingData.startTime || endTime;
  const durationSeconds = Math.round((endTime.toMillis() - startTime.toMillis()) / 1000);
  
  // Merge transcripts
  const fullTranscript = [
    ...(existingData.transcript || []),
    ...sanitizeTranscript(data.transcript)
  ];
  
  const metrics = calculateMetrics(fullTranscript);
  
  const updateData = {
    endTime,
    status: 'completed',
    duration: durationSeconds,
    transcript: fullTranscript,
    outcome: data.outcome || 'unknown',
    leadScore: data.leadScore || null,
    metrics,
    updatedAt: Firestore.Timestamp.now()
  };
  
  if (data.meetingBooked) {
    updateData.meetingBooked = data.meetingBooked;
  }
  
  if (data.emailSent) {
    updateData.emailSent = data.emailSent;
  }
  
  if (data.salesforceTaskId) {
    updateData.salesforceTaskId = data.salesforceTaskId;
  }
  
  await docRef.set(updateData, { merge: true });
  
  // Stream to BigQuery if enabled
  if (ENABLE_BIGQUERY) {
    await streamToBigQuery({
      ...existingData,
      ...updateData,
      sessionId: data.sessionId
    });
  }
  
  console.log(`Call ended: ${data.sessionId}, duration: ${durationSeconds}s, outcome: ${data.outcome}`);
  
  return {
    id: data.sessionId,
    status: 'completed',
    duration: durationSeconds,
    outcome: data.outcome,
    metrics
  };
}

/**
 * Stream call data to BigQuery for analytics
 */
async function streamToBigQuery(data) {
  try {
    const bq = getBigQuery();
    
    const row = {
      session_id: data.sessionId,
      start_time: data.startTime?.toDate?.() || new Date(),
      end_time: data.endTime?.toDate?.() || new Date(),
      duration_seconds: data.duration || 0,
      
      caller_phone: data.callerPhone || null,
      caller_name: data.callerName || null,
      account_name: data.accountName || null,
      account_id: data.accountId || null,
      
      use_case: data.useCase || 'unknown',
      campaign: data.campaign || null,
      outcome: data.outcome || 'unknown',
      lead_score: data.leadScore || 0,
      
      total_turns: data.metrics?.totalTurns || 0,
      user_turns: data.metrics?.userTurns || 0,
      bot_turns: data.metrics?.botTurns || 0,
      
      meeting_booked: data.meetingBooked || false,
      email_sent: data.emailSent || false,
      
      region: data.metadata?.region || null,
      
      inserted_at: new Date()
    };
    
    await bq.dataset(BIGQUERY_DATASET).table(BIGQUERY_TABLE).insert([row]);
    console.log(`Streamed to BigQuery: ${data.sessionId}`);
    
  } catch (error) {
    // Log but don't fail the main operation
    console.error('BigQuery streaming error:', error);
  }
}

/**
 * Get call by session ID
 */
async function getCall(sessionId) {
  const db = getFirestore();
  const doc = await db.collection(COLLECTION_NAME).doc(sessionId).get();
  
  if (!doc.exists) {
    return null;
  }
  
  return { id: doc.id, ...doc.data() };
}

/**
 * Main HTTP handler
 */
functions.http('logCall', async (req, res) => {
  // CORS
  res.set('Access-Control-Allow-Origin', '*');
  res.set('Access-Control-Allow-Methods', 'GET, POST');
  res.set('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.status(204).send('');
    return;
  }
  
  try {
    // GET: Retrieve call by session ID
    if (req.method === 'GET') {
      const sessionId = req.query.sessionId;
      
      if (!sessionId) {
        res.status(400).json({ error: 'sessionId query parameter required' });
        return;
      }
      
      const call = await getCall(sessionId);
      
      if (!call) {
        res.status(404).json({ error: 'Call not found' });
        return;
      }
      
      res.json(call);
      return;
    }
    
    // POST: Log call event
    if (req.method !== 'POST') {
      res.status(405).json({ error: 'Method not allowed' });
      return;
    }
    
    const validation = validateRequest(req.body);
    if (!validation.valid) {
      res.status(400).json({
        error: 'Invalid request',
        details: validation.errors
      });
      return;
    }
    
    const action = req.body.action || 'start';
    let result;
    
    switch (action) {
      case 'start':
        result = await logCallStart(req.body);
        break;
      case 'update':
        result = await updateCall(req.body);
        break;
      case 'end':
        result = await logCallEnd(req.body);
        break;
      default:
        res.status(400).json({ error: `Unknown action: ${action}` });
        return;
    }
    
    res.json({
      success: true,
      ...result
    });
    
  } catch (error) {
    console.error('Call logging error:', error);
    
    res.status(500).json({
      error: 'Failed to log call',
      message: error.message
    });
  }
});

// Export for testing
module.exports = {
  validateRequest,
  sanitizeTranscript,
  calculateMetrics
};
