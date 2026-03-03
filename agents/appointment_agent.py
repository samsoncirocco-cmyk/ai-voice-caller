#!/usr/bin/env python3
"""
Appointment Setting Agent - Schedules meetings with High Point Networks
Uses SignalWire Agents SDK for natural AI conversation
"""
import os
import sys
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from signalwire_agents import AgentBase, SwaigFunctionResult
from google.cloud import firestore
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Configuration
PROJECT_ID = "tatt-pro"
FIRESTORE_COLLECTION = "scheduled-meetings"
PARTNER_NAME = "High Point Networks"
PARTNER_EMAIL = "contact@highpointnetworks.com"  # TODO: Get actual partner email
MEETING_DURATION_MINUTES = 30
TIMEZONE = "America/Phoenix"  # Arizona MST (no DST)

# Calendar configuration
CALENDAR_ID = "primary"  # TODO: Use dedicated calendar if needed
SCOPES = ['https://www.googleapis.com/auth/calendar']


class AppointmentAgent(AgentBase):
    """
    Appointment Setting agent that schedules meetings with partners.
    
    Conversation flow:
    1. Offers to schedule a demo/meeting
    2. Checks partner availability
    3. Proposes time slots based on preference
    4. Handles scheduling conflicts
    5. Confirms meeting details
    6. Sends calendar invite
    7. Logs to Firestore
    """
    
    def __init__(self):
        super().__init__(name="appointment-setting")
        
        # Configure agent personality and behavior
        self.prompt_add_section(
            "Role",
            f"""You are Paul, a friendly and professional scheduling assistant for Fortinet. 
            Your goal is to schedule meetings between potential customers and {PARTNER_NAME}, 
            our technical partner who handles voice system implementations."""
        )
        
        self.prompt_add_section(
            "Task",
            f"""When the customer agrees to a meeting:
            1. Ask about their time preference (morning/afternoon)
            2. Check availability using check_availability function
            3. Propose 2-3 specific time slots
            4. When they confirm a time, collect their email
            5. Book the meeting using book_meeting function
            6. Confirm: "You'll receive a calendar invite at [EMAIL] with a Google Meet link"
            7. Ask if there's anything specific they want to cover
            
            Keep the scheduling process smooth and efficient. Be flexible with times."""
        )
        
        self.prompt_add_section(
            "Guidelines",
            f"""- Always mention this is a meeting with {PARTNER_NAME}, not Fortinet directly
            - Meeting duration is {MEETING_DURATION_MINUTES} minutes
            - If they reject your first options, offer different times
            - After 3 failed attempts, offer to send a scheduling link instead
            - Always confirm the time clearly: "Tuesday the 17th at 9:30 AM Arizona time"
            - Be understanding if they need to reschedule or check their calendar
            - Times are in Arizona time (MST, no daylight saving)"""
        )
        
        # Configure voice and language settings
        self.add_language("English", "en-US", "en-US-Neural2-J")  # Professional male voice
        
        # Initialize Firestore client
        self.db = firestore.Client(project=PROJECT_ID)
        
        # Initialize Google Calendar API
        self.calendar_service = None
        self._init_calendar_service()
    
    def _init_calendar_service(self):
        """Initialize Google Calendar API service."""
        try:
            # Try to use Application Default Credentials first
            credentials = None
            
            # Check for service account key file
            key_file = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            
            if key_file and os.path.exists(key_file):
                credentials = service_account.Credentials.from_service_account_file(
                    key_file, scopes=SCOPES
                )
            else:
                # Use ADC (Application Default Credentials)
                from google.auth import default
                credentials, project = default(scopes=SCOPES)
            
            self.calendar_service = build('calendar', 'v3', credentials=credentials)
            print("✅ Google Calendar API initialized")
            
        except Exception as e:
            print(f"⚠️  Could not initialize Calendar API: {str(e)}")
            print("    Appointment booking will use mock data")
    
    def _get_available_slots(self, time_preference: str = "anytime", days_ahead: int = 7) -> list:
        """
        Get available time slots from Google Calendar.
        
        Args:
            time_preference: "morning", "afternoon", or "anytime"
            days_ahead: Number of days to look ahead
            
        Returns:
            List of available datetime objects
        """
        if not self.calendar_service:
            # Return mock slots if Calendar API not initialized
            return self._get_mock_slots(time_preference, days_ahead)
        
        try:
            now = datetime.now(ZoneInfo(TIMEZONE))
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()
            
            # Query free/busy information
            body = {
                "timeMin": time_min,
                "timeMax": time_max,
                "timeZone": TIMEZONE,
                "items": [{"id": CALENDAR_ID}]
            }
            
            events_result = self.calendar_service.freebusy().query(body=body).execute()
            busy_times = events_result['calendars'][CALENDAR_ID]['busy']
            
            # Generate candidate slots
            slots = []
            current = now + timedelta(hours=24)  # Start tomorrow
            current = current.replace(hour=9, minute=0, second=0, microsecond=0)
            
            while len(slots) < 10 and current < now + timedelta(days=days_ahead):
                # Skip weekends
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                
                # Check time preference
                if time_preference == "morning" and current.hour >= 12:
                    current += timedelta(days=1)
                    current = current.replace(hour=9)
                    continue
                elif time_preference == "afternoon" and current.hour < 12:
                    current = current.replace(hour=13)
                    continue
                
                # Check if slot is free
                slot_end = current + timedelta(minutes=MEETING_DURATION_MINUTES)
                is_free = True
                
                for busy in busy_times:
                    busy_start = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                    busy_end = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
                    
                    if not (slot_end <= busy_start or current >= busy_end):
                        is_free = False
                        break
                
                if is_free:
                    slots.append(current)
                
                # Increment by 30 minutes
                current += timedelta(minutes=30)
                
                # Skip to next day after 5 PM
                if current.hour >= 17:
                    current += timedelta(days=1)
                    current = current.replace(hour=9, minute=0)
            
            return slots[:5]  # Return top 5 slots
            
        except Exception as e:
            print(f"⚠️  Error checking calendar availability: {str(e)}")
            return self._get_mock_slots(time_preference, days_ahead)
    
    def _get_mock_slots(self, time_preference: str, days_ahead: int) -> list:
        """Generate mock available slots for testing."""
        now = datetime.now(ZoneInfo(TIMEZONE))
        slots = []
        
        # Generate slots for next 3 business days
        current = now + timedelta(days=1)
        days_added = 0
        
        while days_added < 3:
            # Skip weekends
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            
            if time_preference == "morning" or time_preference == "anytime":
                morning = current.replace(hour=9, minute=30, second=0, microsecond=0)
                slots.append(morning)
                
                morning2 = current.replace(hour=11, minute=0, second=0, microsecond=0)
                slots.append(morning2)
            
            if time_preference == "afternoon" or time_preference == "anytime":
                afternoon = current.replace(hour=14, minute=0, second=0, microsecond=0)
                slots.append(afternoon)
                
                afternoon2 = current.replace(hour=15, minute=30, second=0, microsecond=0)
                slots.append(afternoon2)
            
            current += timedelta(days=1)
            days_added += 1
        
        return slots[:5]
    
    def _format_slot(self, dt: datetime) -> str:
        """Format a datetime slot for speaking."""
        day_name = dt.strftime("%A")
        day_num = dt.strftime("%-d")  # Day without leading zero
        ordinal = "th"
        if day_num.endswith("1") and day_num != "11":
            ordinal = "st"
        elif day_num.endswith("2") and day_num != "12":
            ordinal = "nd"
        elif day_num.endswith("3") and day_num != "13":
            ordinal = "rd"
        
        time_str = dt.strftime("%-I:%M %p")
        return f"{day_name} the {day_num}{ordinal} at {time_str}"
    
    @AgentBase.tool(description="Check available meeting times based on preference")
    def check_availability(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Check calendar availability and propose meeting times.
        
        Args:
            args: Dictionary containing:
                - time_preference (str): "morning", "afternoon", or "anytime"
                - days_ahead (int, optional): Number of days to look ahead (default 7)
        """
        time_pref = args.get("time_preference", "anytime").lower()
        days_ahead = args.get("days_ahead", 7)
        
        print(f"🔍 Checking availability: {time_pref} preference, {days_ahead} days ahead")
        
        try:
            slots = self._get_available_slots(time_pref, days_ahead)
            
            if not slots:
                return SwaigFunctionResult(
                    "I'm not finding any open slots in the next week. "
                    "Let me send you a scheduling link instead."
                )
            
            # Format top 3 slots for speaking
            slot_descriptions = []
            for i, slot in enumerate(slots[:3]):
                slot_descriptions.append(self._format_slot(slot))
            
            if len(slot_descriptions) == 1:
                message = f"I have {slot_descriptions[0]} available."
            elif len(slot_descriptions) == 2:
                message = f"I have {slot_descriptions[0]} or {slot_descriptions[1]} available."
            else:
                message = f"I have {slot_descriptions[0]}, {slot_descriptions[1]}, or {slot_descriptions[2]} available."
            
            # Store slots in session for later reference
            slot_data = {
                f"slot_{i+1}": slot.isoformat() for i, slot in enumerate(slots[:3])
            }
            
            print(f"✅ Found {len(slots)} available slots")
            
            return SwaigFunctionResult(message)
            
        except Exception as e:
            error_message = f"Error checking availability: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(
                "I'm having trouble checking the calendar right now. "
                "Let me send you a scheduling link instead."
            )
    
    @AgentBase.tool(description="Book a meeting at a specific time")
    def book_meeting(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Book a calendar meeting.
        
        Args:
            args: Dictionary containing:
                - meeting_time (str): ISO format datetime or slot reference (e.g., "slot_1")
                - attendee_email (str): Email of the person to invite
                - attendee_name (str): Name of the person
                - meeting_topics (str, optional): Topics to cover in the meeting
        """
        meeting_time_str = args.get("meeting_time", "")
        attendee_email = args.get("attendee_email", "")
        attendee_name = args.get("attendee_name", "")
        meeting_topics = args.get("meeting_topics", "")
        
        print(f"📅 Booking meeting: {meeting_time_str} with {attendee_email}")
        
        try:
            # Parse meeting time
            if meeting_time_str.startswith("slot_"):
                # Reference to a slot from check_availability
                # This would need to be stored in session data
                return SwaigFunctionResult(
                    "Please provide the full date and time for the meeting."
                )
            
            meeting_dt = datetime.fromisoformat(meeting_time_str)
            meeting_end = meeting_dt + timedelta(minutes=MEETING_DURATION_MINUTES)
            
            # Create calendar event
            event = {
                'summary': f'Demo Call - {attendee_name}',
                'description': f'Technical consultation call with {PARTNER_NAME}.\n\n'
                              f'Attendee: {attendee_name} ({attendee_email})\n'
                              f'Topics: {meeting_topics if meeting_topics else "General overview"}\n\n'
                              f'Scheduled via AI Voice Caller',
                'start': {
                    'dateTime': meeting_dt.isoformat(),
                    'timeZone': TIMEZONE,
                },
                'end': {
                    'dateTime': meeting_end.isoformat(),
                    'timeZone': TIMEZONE,
                },
                'attendees': [
                    {'email': attendee_email, 'displayName': attendee_name},
                    {'email': PARTNER_EMAIL},
                ],
                'conferenceData': {
                    'createRequest': {
                        'requestId': f'meeting-{datetime.now().timestamp()}',
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                        {'method': 'popup', 'minutes': 30},  # 30 min before
                    ],
                },
            }
            
            if self.calendar_service:
                # Create the event
                created_event = self.calendar_service.events().insert(
                    calendarId=CALENDAR_ID,
                    body=event,
                    conferenceDataVersion=1
                ).execute()
                
                event_link = created_event.get('htmlLink')
                meet_link = created_event.get('hangoutLink', 'Will be included in calendar invite')
                
                print(f"✅ Meeting created: {event_link}")
            else:
                # Mock mode
                event_link = "https://calendar.google.com/mock-event"
                meet_link = "https://meet.google.com/mock-link"
                print("✅ Meeting created (mock mode)")
            
            # Log to Firestore
            meeting_doc = {
                'attendee_name': attendee_name,
                'attendee_email': attendee_email,
                'meeting_time': meeting_dt,
                'duration_minutes': MEETING_DURATION_MINUTES,
                'partner': PARTNER_NAME,
                'topics': meeting_topics,
                'calendar_event_link': event_link,
                'meet_link': meet_link,
                'created_at': firestore.SERVER_TIMESTAMP,
                'source': 'appointment-agent',
                'status': 'scheduled'
            }
            
            doc_ref = self.db.collection(FIRESTORE_COLLECTION).add(meeting_doc)
            
            message = (
                f"Perfect! Meeting confirmed for {self._format_slot(meeting_dt)}. "
                f"Calendar invite sent to {attendee_email}."
            )
            
            return SwaigFunctionResult(message)
            
        except Exception as e:
            error_message = f"Failed to book meeting: {str(e)}"
            print(f"❌ {error_message}")
            return SwaigFunctionResult(
                "I'm having trouble creating the calendar event. "
                "Let me send you a scheduling link instead."
            )
    
    @AgentBase.tool(description="Send a calendar invite to the attendee")
    def send_calendar_invite(self, args: dict, raw_data: dict = None) -> SwaigFunctionResult:
        """
        Send a calendar invite (this is handled automatically by book_meeting).
        
        Args:
            args: Dictionary containing:
                - event_id (str): Calendar event ID
                - attendee_email (str): Email to send invite to
        """
        # This is handled automatically by the Calendar API when creating an event
        # This function exists mainly for conversation flow purposes
        
        attendee_email = args.get("attendee_email", "")
        
        return SwaigFunctionResult(
            f"Calendar invite will be sent to {attendee_email} with meeting details and video link."
        )


def main():
    """
    Start the Appointment Setting agent server.
    Listens on port 3001 for incoming SignalWire requests.
    """
    print("="*70)
    print("📅 Appointment Setting Agent Starting")
    print("="*70)
    print("\nThis agent will:")
    print("  1. Check partner calendar availability")
    print("  2. Propose meeting times")
    print("  3. Book meetings with Google Calendar")
    print("  4. Send calendar invites")
    print("  5. Log meetings to Firestore")
    print("\nAgent is ready to schedule meetings!")
    print(f"\nConnect your SignalWire flow to: http://YOUR_PUBLIC_URL:3001/")
    print("="*70)
    
    agent = AppointmentAgent()
    agent.run(host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()
