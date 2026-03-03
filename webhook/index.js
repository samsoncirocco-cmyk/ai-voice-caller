/**
 * SignalWire ↔ Dialogflow CX Bridge Webhook
 * 
 * This Cloud Function receives SignalWire webhook calls and bridges them
 * to Dialogflow CX, enabling natural AI conversations over the phone.
 * 
 * Flow:
 * 1. SignalWire sends transcribed speech
 * 2. We call Dialogflow CX detectIntent API
 * 3. We return TwiML with AI's response
 * 4. SignalWire plays the response and listens for next input
 */

const functions = require('@google-cloud/functions-framework');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
const { Firestore } = require('@google-cloud/firestore');

// Configuration
const PROJECT_ID = process.env.GCP_PROJECT || 'tatt-pro';
const LOCATION = 'us-central1';
const AGENT_ID = '35ba664e-b443-4b8e-bf60-b9c445b31273';
const FLOW_ID = 'a7b89969-6edd-4cc4-850b-9e869b3e06b4'; // Discovery Mode flow
const LANGUAGE_CODE = 'en-US';

// Initialize clients with regional endpoint
const sessionClient = new SessionsClient({
  apiEndpoint: `${LOCATION}-dialogflow.googleapis.com`
});
const firestore = new Firestore();

/**
 * Main webhook handler
 */
functions.http('dialogflowWebhook', async (req, res) => {
  const body = req.body || {};
  const query = req.query || {};

  if (req.method === 'GET') {
    res.status(200).send('ok');
    return;
  }
  if (req.method === 'GET' && (req.path === '/' || req.path === '/health')) {
    res.status(200).send('ok');
    return;
  }
  console.log('📞 Incoming webhook:', {
    method: req.method,
    body: req.body,
    query: req.query
  });

  try {
    // Handle different webhook events
    const callSid = body.CallSid || query.CallSid;
    const speechResult = body.SpeechResult || body.UnstableSpeechResult;
    const callStatus = body.CallStatus;
    
    if (!callSid) {
      res.set('Content-Type', 'text/xml');
      res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><Response></Response>');
      return;
    }

    // If call just started, initiate conversation
    if (!speechResult && callStatus !== 'completed') {
      return handleCallStart(req, res, callSid);
    }
    
    // If call ended, clean up session
    if (callStatus === 'completed') {
      return handleCallEnd(req, res, callSid);
    }
    
    // Normal turn - user spoke, get AI response
    return handleConversationTurn(req, res, callSid, speechResult);
    
  } catch (error) {
    console.error('❌ Webhook error:', error);
    
    // Return graceful error response
    res.set('Content-Type', 'text/xml');
    res.send(`<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">I'm sorry, I'm having technical difficulties. Let me have someone call you back.</Say>
    <Hangup/>
</Response>`);
  }
});

/**
 * Handle call start - send initial greeting
 */
async function handleCallStart(req, res, callSid) {
  console.log('🎬 Starting new call:', callSid);
  
  // Create Dialogflow session
  const sessionId = callSid;
  const sessionPath = sessionClient.projectLocationAgentSessionPath(
    PROJECT_ID,
    LOCATION,
    AGENT_ID,
    sessionId
  );
  
  // Initialize session parameters
  const sessionParams = {
    phone_number: req.body.To || req.body.Called,
    caller_id: req.body.From || req.body.Caller,
    call_sid: callSid,
    call_start_time: new Date().toISOString()
  };
  
  // Store session in Firestore
  await firestore.collection('active_calls').doc(callSid).set({
    session_id: sessionPath,
    session_params: sessionParams,
    started_at: Firestore.Timestamp.now(),
    turn_count: 0
  });
  
  // Call Dialogflow to get initial greeting from entry fulfillment
  const flowPath = `projects/${PROJECT_ID}/locations/${LOCATION}/agents/${AGENT_ID}/flows/${FLOW_ID}`;
  const startPage = `${flowPath}/pages/START_PAGE`;
  
  const request = {
    session: sessionPath,
    queryInput: {
      text: {
        text: '' // Empty input triggers entry fulfillment
      },
      languageCode: LANGUAGE_CODE
    },
    queryParams: {
      parameters: sessionParams,
      currentPage: startPage
    }
  };
  
  const [response] = await sessionClient.detectIntent(request);
  const fulfillmentText = extractFulfillmentText(response);
  
  console.log('🤖 AI response:', fulfillmentText);
  
  // Return TwiML with greeting + speech gathering
  res.set('Content-Type', 'text/xml');
  res.send(buildTwiML(fulfillmentText, callSid));
}

/**
 * Handle conversation turn - user spoke, get AI response
 */
async function handleConversationTurn(req, res, callSid, speechResult) {
  console.log('💬 Conversation turn:', { callSid, speechResult });
  
  if (!speechResult || speechResult.trim() === '') {
    // No speech detected - ask them to speak
    return res.send(buildTwiML('I didn\'t catch that. Could you say that again?', callSid));
  }
  
  // Get session info
  const callDoc = await firestore.collection('active_calls').doc(callSid).get();
  if (!callDoc.exists) {
    console.error('⚠️ Session not found for call:', callSid);
    return handleCallStart(req, res, callSid);
  }
  
  const callData = callDoc.data();
  const sessionPath = callData.session_id;
  
  // Call Dialogflow with user's speech
  const request = {
    session: sessionPath,
    queryInput: {
      text: {
        text: speechResult
      },
      languageCode: LANGUAGE_CODE
    }
  };
  
  const [response] = await sessionClient.detectIntent(request);
  const fulfillmentText = extractFulfillmentText(response);
  const endInteraction = response.queryResult.responseMessages.some(
    msg => msg.endInteraction
  );
  
  console.log('🤖 AI response:', { fulfillmentText, endInteraction });
  
  // Update turn count
  await callDoc.ref.update({
    turn_count: Firestore.FieldValue.increment(1),
    last_user_input: speechResult,
    last_bot_response: fulfillmentText,
    updated_at: Firestore.Timestamp.now()
  });
  
  // Log conversation to Firestore
  await logConversationTurn(callSid, speechResult, fulfillmentText);
  
  // If conversation ended, hang up
  if (endInteraction) {
    res.set('Content-Type', 'text/xml');
    return res.send(`<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">${escapeXml(fulfillmentText)}</Say>
    <Pause length="1"/>
    <Hangup/>
</Response>`);
  }
  
  // Continue conversation
  res.set('Content-Type', 'text/xml');
  res.send(buildTwiML(fulfillmentText, callSid));
}

/**
 * Handle call end - cleanup and logging
 */
async function handleCallEnd(req, res, callSid) {
  console.log('📴 Call ended:', callSid);
  
  try {
    // Get call data
    const callDoc = await firestore.collection('active_calls').doc(callSid).get();
    if (callDoc.exists) {
      const callData = callDoc.data();
      
      // Move to completed calls
      await firestore.collection('completed_calls').doc(callSid).set({
        ...callData,
        ended_at: Firestore.Timestamp.now(),
        duration_seconds: req.body.CallDuration || 0,
        call_status: req.body.CallStatus
      });
      
      // Delete from active calls
      await callDoc.ref.delete();
    }
  } catch (error) {
    console.error('Error cleaning up call:', error);
  }
  
  res.set('Content-Type', 'text/xml');
  res.send('<?xml version="1.0" encoding="UTF-8"?><Response></Response>');
}

/**
 * Extract fulfillment text from Dialogflow response
 */
function extractFulfillmentText(response) {
  const messages = response.queryResult.responseMessages;
  
  for (const message of messages) {
    if (message.text && message.text.text && message.text.text.length > 0) {
      return message.text.text[0];
    }
  }
  
  return 'I didn\'t understand that. Could you repeat?';
}

/**
 * Build TwiML response for SignalWire
 */
function buildTwiML(text, callSid) {
  const webhookUrl = process.env.FUNCTION_URL || 
    `https://${LOCATION}-${PROJECT_ID}.cloudfunctions.net/dialogflowWebhook`;
  
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew">${escapeXml(text)}</Say>
    <Gather 
        input="speech" 
        action="${webhookUrl}?CallSid=${callSid}"
        speechTimeout="auto"
        speechModel="phone_call"
        enhanced="true"
        profanityFilter="false">
    </Gather>
    <Say voice="Polly.Matthew">I didn't hear anything. Goodbye!</Say>
    <Hangup/>
</Response>`;
}

/**
 * Escape XML special characters
 */
function escapeXml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * Log conversation turn to Firestore
 */
async function logConversationTurn(callSid, userInput, botResponse) {
  await firestore.collection('conversation_logs').add({
    call_sid: callSid,
    timestamp: Firestore.Timestamp.now(),
    user_input: userInput,
    bot_response: botResponse
  });
}
