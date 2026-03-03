/**
 * Salesforce Task Creator Cloud Function
 * 
 * Creates Salesforce tasks after AI voice calls complete.
 * Logs call activities, updates lead status, and creates
 * follow-up tasks based on call outcomes.
 * 
 * @author AI Voice Caller Team
 * @version 1.0.0
 */

const functions = require('@google-cloud/functions-framework');
const jsforce = require('jsforce');
const { SecretManagerServiceClient } = require('@google-cloud/secret-manager');

// Configuration
const PROJECT_ID = process.env.GCP_PROJECT || 'tatt-pro';
const SF_LOGIN_URL = process.env.SF_LOGIN_URL || 'https://login.salesforce.com';
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// Connection pool for Salesforce
let sfConnection = null;
let connectionExpiry = 0;
const CONNECTION_TTL_MS = 30 * 60 * 1000; // 30 minutes

// Secret Manager client
let secretClient = null;

/**
 * Get Secret Manager client (lazy initialization)
 */
function getSecretClient() {
  if (!secretClient) {
    secretClient = new SecretManagerServiceClient();
  }
  return secretClient;
}

/**
 * Retrieve secret from Secret Manager
 * @param {string} secretName - Name of the secret
 * @returns {string} - Secret value
 */
async function getSecret(secretName) {
  const client = getSecretClient();
  const name = `projects/${PROJECT_ID}/secrets/${secretName}/versions/latest`;
  
  const [version] = await client.accessSecretVersion({ name });
  return version.payload.data.toString('utf8');
}

/**
 * Get or create Salesforce connection
 * @returns {jsforce.Connection} - Active Salesforce connection
 */
async function getSalesforceConnection() {
  const now = Date.now();
  
  // Return cached connection if valid
  if (sfConnection && now < connectionExpiry) {
    return sfConnection;
  }
  
  console.log('Creating new Salesforce connection...');
  
  // Get credentials from Secret Manager
  const [username, password, securityToken] = await Promise.all([
    getSecret('sf-username'),
    getSecret('sf-password'),
    getSecret('sf-security-token')
  ]);
  
  // Create new connection
  sfConnection = new jsforce.Connection({
    loginUrl: SF_LOGIN_URL
  });
  
  await sfConnection.login(username, password + securityToken);
  connectionExpiry = now + CONNECTION_TTL_MS;
  
  console.log('Salesforce connection established');
  return sfConnection;
}

/**
 * Sleep utility for retry logic
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry wrapper with exponential backoff
 */
async function withRetry(fn, maxRetries = MAX_RETRIES) {
  let lastError;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      
      // Reset connection on auth errors
      if (error.name === 'INVALID_SESSION_ID' || error.errorCode === 'INVALID_SESSION_ID') {
        sfConnection = null;
        connectionExpiry = 0;
      }
      
      const delay = RETRY_DELAY_MS * Math.pow(2, attempt);
      console.warn(`Attempt ${attempt + 1} failed, retrying in ${delay}ms:`, error.message);
      await sleep(delay);
    }
  }
  
  throw lastError;
}

/**
 * Validate incoming request
 * @param {Object} body - Request body
 * @returns {Object} - Validation result
 */
function validateRequest(body) {
  const errors = [];
  const requiredFields = ['accountName', 'outcome'];
  
  for (const field of requiredFields) {
    if (!body[field]) {
      errors.push(`${field} is required`);
    }
  }
  
  const validOutcomes = [
    'interested',
    'send_info',
    'meeting_booked',
    'not_interested',
    'callback_requested',
    'voicemail',
    'wrong_number',
    'no_answer'
  ];
  
  if (body.outcome && !validOutcomes.includes(body.outcome)) {
    errors.push(`Invalid outcome. Must be one of: ${validOutcomes.join(', ')}`);
  }
  
  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Find Salesforce Account by name
 * @param {jsforce.Connection} conn - Salesforce connection
 * @param {string} accountName - Account name to search
 * @returns {Object|null} - Account record or null
 */
async function findAccount(conn, accountName) {
  // Try exact match first
  let records = await conn.sobject('Account')
    .find({ Name: accountName })
    .limit(1)
    .execute();
  
  if (records.length > 0) {
    return records[0];
  }
  
  // Try LIKE match
  const query = `SELECT Id, Name, OwnerId FROM Account WHERE Name LIKE '%${accountName.replace(/'/g, "\\'")}%' LIMIT 5`;
  const result = await conn.query(query);
  
  if (result.records.length > 0) {
    // Return best match (shortest name that contains search term)
    return result.records.sort((a, b) => a.Name.length - b.Name.length)[0];
  }
  
  return null;
}

/**
 * Map call outcome to task configuration
 * @param {string} outcome - Call outcome
 * @returns {Object} - Task configuration
 */
function getTaskConfig(outcome) {
  const configs = {
    interested: {
      subject: 'AI Call - Interested, Schedule Follow-up',
      priority: 'High',
      status: 'Not Started',
      daysUntilDue: 1
    },
    send_info: {
      subject: 'AI Call - Send Requested Information',
      priority: 'Normal',
      status: 'Not Started',
      daysUntilDue: 0
    },
    meeting_booked: {
      subject: 'AI Call - Meeting Booked',
      priority: 'High',
      status: 'Completed',
      daysUntilDue: 0
    },
    not_interested: {
      subject: 'AI Call - Not Interested',
      priority: 'Low',
      status: 'Completed',
      daysUntilDue: 0
    },
    callback_requested: {
      subject: 'AI Call - Callback Requested',
      priority: 'High',
      status: 'Not Started',
      daysUntilDue: 1
    },
    voicemail: {
      subject: 'AI Call - Left Voicemail',
      priority: 'Normal',
      status: 'Completed',
      daysUntilDue: 0
    },
    wrong_number: {
      subject: 'AI Call - Wrong Number',
      priority: 'Low',
      status: 'Completed',
      daysUntilDue: 0
    },
    no_answer: {
      subject: 'AI Call - No Answer',
      priority: 'Normal',
      status: 'Not Started',
      daysUntilDue: 1
    }
  };
  
  return configs[outcome] || configs.no_answer;
}

/**
 * Create Salesforce Task
 * @param {jsforce.Connection} conn - Salesforce connection
 * @param {Object} data - Task data
 * @returns {Object} - Created task
 */
async function createTask(conn, data) {
  const { account, outcome, callSummary, transcript, leadScore, contactName, callDuration } = data;
  
  const taskConfig = getTaskConfig(outcome);
  const dueDate = new Date();
  dueDate.setDate(dueDate.getDate() + taskConfig.daysUntilDue);
  
  // Build description
  const descriptionParts = [
    `Call Outcome: ${outcome.replace(/_/g, ' ').toUpperCase()}`,
    `Contact: ${contactName || 'Unknown'}`,
    `Duration: ${callDuration ? `${callDuration} seconds` : 'N/A'}`,
    `Lead Score: ${leadScore || 'N/A'}`,
    '',
    'Summary:',
    callSummary || 'No summary available',
    '',
    'Transcript:',
    transcript || 'No transcript available'
  ];
  
  const task = {
    Subject: taskConfig.subject,
    Description: descriptionParts.join('\n').slice(0, 32000), // SF limit
    WhatId: account.Id,
    OwnerId: account.OwnerId,
    Status: taskConfig.status,
    Priority: taskConfig.priority,
    ActivityDate: dueDate.toISOString().split('T')[0],
    Type: 'Call'
  };
  
  const result = await conn.sobject('Task').create(task);
  
  if (!result.success) {
    throw new Error(`Failed to create task: ${JSON.stringify(result.errors)}`);
  }
  
  return {
    id: result.id,
    ...task
  };
}

/**
 * Log call activity
 * @param {jsforce.Connection} conn - Salesforce connection  
 * @param {Object} data - Call data
 * @returns {Object} - Created activity
 */
async function logCallActivity(conn, data) {
  const { account, outcome, callSummary, callDuration, contactName } = data;
  
  const event = {
    Subject: `AI Voice Call - ${outcome.replace(/_/g, ' ')}`,
    Description: callSummary || 'AI voice call completed',
    WhatId: account.Id,
    DurationInMinutes: callDuration ? Math.ceil(callDuration / 60) : 1,
    ActivityDateTime: new Date().toISOString(),
    Type: 'Call'
  };
  
  // Note: Using Event for call logging - some orgs may use Task instead
  try {
    const result = await conn.sobject('Event').create(event);
    return { id: result.id, type: 'Event' };
  } catch (error) {
    // Fall back to just the task if Event creation fails
    console.warn('Failed to create Event, using Task only:', error.message);
    return { type: 'Task only' };
  }
}

/**
 * Main HTTP Cloud Function handler
 */
functions.http('createSalesforceTask', async (req, res) => {
  // Set CORS headers
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
    // Validate request
    const validation = validateRequest(req.body);
    if (!validation.valid) {
      res.status(400).json({
        error: 'Invalid request',
        details: validation.errors
      });
      return;
    }
    
    const {
      accountName,
      outcome,
      callSummary,
      transcript,
      leadScore,
      contactName,
      callDuration,
      sessionId
    } = req.body;
    
    // Get Salesforce connection with retry
    const conn = await withRetry(() => getSalesforceConnection());
    
    // Find account
    const account = await withRetry(() => findAccount(conn, accountName));
    
    if (!account) {
      res.status(404).json({
        error: 'Account not found',
        searchedName: accountName,
        suggestion: 'Verify account name matches Salesforce exactly'
      });
      return;
    }
    
    const data = {
      account,
      outcome,
      callSummary,
      transcript,
      leadScore,
      contactName,
      callDuration
    };
    
    // Create task and log activity in parallel
    const [task, activity] = await Promise.all([
      withRetry(() => createTask(conn, data)),
      withRetry(() => logCallActivity(conn, data))
    ]);
    
    console.log(`Created task ${task.id} for account ${account.Name}`);
    
    res.json({
      success: true,
      task: {
        id: task.id,
        subject: task.Subject,
        priority: task.Priority,
        status: task.Status
      },
      activity,
      account: {
        id: account.Id,
        name: account.Name
      }
    });
    
  } catch (error) {
    console.error('Error creating Salesforce task:', error);
    
    res.status(500).json({
      error: 'Failed to create Salesforce task',
      message: error.message
    });
  }
});

// Export for testing
module.exports = {
  validateRequest,
  getTaskConfig
};
