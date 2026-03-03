/**
 * Calendar Booking Cloud Function
 * 
 * Books meetings via Google Calendar API during AI voice calls.
 * Checks availability, creates events, and sends invitations.
 * 
 * @author AI Voice Caller Team
 * @version 1.0.0
 */

const functions = require('@google-cloud/functions-framework');
const { google } = require('googleapis');
const { SecretManagerServiceClient } = require('@google-cloud/secret-manager');

// Configuration
const PROJECT_ID = process.env.GCP_PROJECT || 'tatt-pro';
const CALENDAR_ID = process.env.CALENDAR_ID || 'primary';
const DEFAULT_TIMEZONE = process.env.TIMEZONE || 'America/Phoenix';
const MEETING_DURATION_MINUTES = parseInt(process.env.MEETING_DURATION || '30', 10);
const BUFFER_MINUTES = parseInt(process.env.BUFFER_MINUTES || '15', 10);

// Working hours (in local timezone)
const WORK_START_HOUR = 8; // 8 AM
const WORK_END_HOUR = 17;  // 5 PM
const WORK_DAYS = [1, 2, 3, 4, 5]; // Monday-Friday

// Auth client cache
let authClient = null;
let secretClient = null;

/**
 * Get Secret Manager client
 */
function getSecretClient() {
  if (!secretClient) {
    secretClient = new SecretManagerServiceClient();
  }
  return secretClient;
}

/**
 * Retrieve secret from Secret Manager
 */
async function getSecret(secretName) {
  const client = getSecretClient();
  const name = `projects/${PROJECT_ID}/secrets/${secretName}/versions/latest`;
  const [version] = await client.accessSecretVersion({ name });
  return version.payload.data.toString('utf8');
}

/**
 * Get Google OAuth2 client
 */
async function getAuthClient() {
  if (authClient) {
    return authClient;
  }
  
  // Get service account credentials from Secret Manager
  const credentialsJson = await getSecret('calendar-service-account');
  const credentials = JSON.parse(credentialsJson);
  
  authClient = new google.auth.GoogleAuth({
    credentials,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });
  
  return authClient;
}

/**
 * Get Calendar API client
 */
async function getCalendarClient() {
  const auth = await getAuthClient();
  return google.calendar({ version: 'v3', auth });
}

/**
 * Validate request body
 */
function validateRequest(body) {
  const errors = [];
  
  if (!body) {
    return { valid: false, errors: ['Request body required'] };
  }
  
  // For availability check, only need date range
  if (body.action === 'check_availability') {
    if (!body.startDate && !body.preferredDate) {
      errors.push('startDate or preferredDate required for availability check');
    }
    return { valid: errors.length === 0, errors };
  }
  
  // For booking, need more fields
  if (body.action === 'book') {
    if (!body.startTime) {
      errors.push('startTime required for booking');
    }
    if (!body.attendeeEmail) {
      errors.push('attendeeEmail required for booking');
    }
    if (!body.attendeeName) {
      errors.push('attendeeName required for booking');
    }
    if (!body.accountName) {
      errors.push('accountName required for booking');
    }
  }
  
  return { valid: errors.length === 0, errors };
}

/**
 * Check if a time slot is within working hours
 */
function isWithinWorkHours(date) {
  const day = date.getDay();
  const hour = date.getHours();
  
  return WORK_DAYS.includes(day) && 
         hour >= WORK_START_HOUR && 
         hour < WORK_END_HOUR;
}

/**
 * Get next available working time
 */
function getNextWorkingTime(date) {
  const result = new Date(date);
  
  // Move to next working day if weekend
  while (!WORK_DAYS.includes(result.getDay())) {
    result.setDate(result.getDate() + 1);
  }
  
  // Set to work start if before working hours
  if (result.getHours() < WORK_START_HOUR) {
    result.setHours(WORK_START_HOUR, 0, 0, 0);
  }
  
  // Move to next day if after working hours
  if (result.getHours() >= WORK_END_HOUR) {
    result.setDate(result.getDate() + 1);
    while (!WORK_DAYS.includes(result.getDay())) {
      result.setDate(result.getDate() + 1);
    }
    result.setHours(WORK_START_HOUR, 0, 0, 0);
  }
  
  return result;
}

/**
 * Get available time slots for a date range
 */
async function getAvailableSlots(calendar, startDate, endDate, duration) {
  // Query free/busy
  const freeBusy = await calendar.freebusy.query({
    requestBody: {
      timeMin: startDate.toISOString(),
      timeMax: endDate.toISOString(),
      timeZone: DEFAULT_TIMEZONE,
      items: [{ id: CALENDAR_ID }]
    }
  });
  
  const busySlots = freeBusy.data.calendars[CALENDAR_ID]?.busy || [];
  
  // Generate all possible slots
  const slots = [];
  let currentTime = getNextWorkingTime(new Date(startDate));
  const end = new Date(endDate);
  
  while (currentTime < end && slots.length < 10) {
    // Check if within work hours
    if (!isWithinWorkHours(currentTime)) {
      currentTime = getNextWorkingTime(currentTime);
      continue;
    }
    
    const slotEnd = new Date(currentTime.getTime() + duration * 60000);
    
    // Check if slot end is still within work hours
    if (slotEnd.getHours() > WORK_END_HOUR || 
        (slotEnd.getHours() === WORK_END_HOUR && slotEnd.getMinutes() > 0)) {
      currentTime = getNextWorkingTime(slotEnd);
      continue;
    }
    
    // Check for conflicts
    const hasConflict = busySlots.some(busy => {
      const busyStart = new Date(busy.start);
      const busyEnd = new Date(busy.end);
      return currentTime < busyEnd && slotEnd > busyStart;
    });
    
    if (!hasConflict) {
      slots.push({
        start: currentTime.toISOString(),
        end: slotEnd.toISOString(),
        displayTime: formatTimeForSpeech(currentTime)
      });
    }
    
    // Move to next slot
    currentTime = new Date(currentTime.getTime() + (duration + BUFFER_MINUTES) * 60000);
  }
  
  return slots;
}

/**
 * Format time for spoken response
 */
function formatTimeForSpeech(date) {
  const options = {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: DEFAULT_TIMEZONE
  };
  
  return new Intl.DateTimeFormat('en-US', options).format(date);
}

/**
 * Book a calendar event
 */
async function bookMeeting(calendar, data) {
  const {
    startTime,
    attendeeEmail,
    attendeeName,
    accountName,
    contactPhone,
    notes
  } = data;
  
  const start = new Date(startTime);
  const end = new Date(start.getTime() + MEETING_DURATION_MINUTES * 60000);
  
  const event = {
    summary: `FortiVoice Demo - ${accountName}`,
    description: [
      `Meeting with ${attendeeName} from ${accountName}`,
      '',
      `Contact: ${attendeeEmail}`,
      contactPhone ? `Phone: ${contactPhone}` : '',
      '',
      'Scheduled by AI Voice Caller',
      '',
      notes ? `Notes: ${notes}` : ''
    ].filter(Boolean).join('\n'),
    start: {
      dateTime: start.toISOString(),
      timeZone: DEFAULT_TIMEZONE
    },
    end: {
      dateTime: end.toISOString(),
      timeZone: DEFAULT_TIMEZONE
    },
    attendees: [
      { email: attendeeEmail, displayName: attendeeName }
    ],
    reminders: {
      useDefault: false,
      overrides: [
        { method: 'email', minutes: 24 * 60 }, // 1 day before
        { method: 'popup', minutes: 30 }
      ]
    },
    conferenceData: {
      createRequest: {
        requestId: `voicecaller-${Date.now()}`,
        conferenceSolutionKey: { type: 'hangoutsMeet' }
      }
    }
  };
  
  const result = await calendar.events.insert({
    calendarId: CALENDAR_ID,
    requestBody: event,
    conferenceDataVersion: 1,
    sendUpdates: 'all' // Send email invites
  });
  
  return {
    eventId: result.data.id,
    htmlLink: result.data.htmlLink,
    meetLink: result.data.conferenceData?.entryPoints?.[0]?.uri,
    start: result.data.start.dateTime,
    end: result.data.end.dateTime
  };
}

/**
 * Main HTTP handler
 */
functions.http('calendarBooking', async (req, res) => {
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
    
    const calendar = await getCalendarClient();
    const action = req.body.action || 'check_availability';
    
    if (action === 'check_availability') {
      // Get available slots for next 5 business days
      const startDate = req.body.startDate 
        ? new Date(req.body.startDate)
        : getNextWorkingTime(new Date());
      
      const endDate = req.body.endDate
        ? new Date(req.body.endDate)
        : new Date(startDate.getTime() + 5 * 24 * 60 * 60 * 1000);
      
      const slots = await getAvailableSlots(
        calendar,
        startDate,
        endDate,
        MEETING_DURATION_MINUTES
      );
      
      if (slots.length === 0) {
        res.json({
          available: false,
          message: 'No available slots in the requested time range',
          suggestion: 'Try a different date range'
        });
        return;
      }
      
      // Format spoken response for Dialogflow
      const spokenSlots = slots.slice(0, 3).map(s => s.displayTime);
      const spokenResponse = slots.length === 1
        ? `I have ${spokenSlots[0]} available.`
        : `I have ${spokenSlots.slice(0, -1).join(', ')}, or ${spokenSlots.slice(-1)} available.`;
      
      res.json({
        available: true,
        slots,
        spokenResponse,
        fulfillmentResponse: {
          messages: [{
            text: { text: [spokenResponse] }
          }]
        }
      });
      
    } else if (action === 'book') {
      const booking = await bookMeeting(calendar, req.body);
      
      const spokenResponse = `Perfect! I've booked the meeting for ${formatTimeForSpeech(new Date(booking.start))}. You'll receive a calendar invite at ${req.body.attendeeEmail} with the video call link.`;
      
      res.json({
        success: true,
        booking,
        spokenResponse,
        fulfillmentResponse: {
          messages: [{
            text: { text: [spokenResponse] }
          }]
        }
      });
      
    } else {
      res.status(400).json({
        error: 'Invalid action',
        validActions: ['check_availability', 'book']
      });
    }
    
  } catch (error) {
    console.error('Calendar booking error:', error);
    
    res.status(500).json({
      error: 'Failed to process calendar request',
      message: error.message
    });
  }
});

// Export for testing
module.exports = {
  validateRequest,
  isWithinWorkHours,
  getNextWorkingTime,
  formatTimeForSpeech
};
