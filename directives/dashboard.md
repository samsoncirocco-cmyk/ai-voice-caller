# Dashboard Directive

## What It Is
Live operations dashboard for Fortinet SLED Voice Caller. Dark-themed Flask web app with Tailwind CSS and Chart.js via CDN. Single-file, no build step.

## How to Run
```bash
cd ~/.openclaw/workspace/projects/ai-voice-caller
.venv/bin/python execution/dashboard.py &
```
Listens on `0.0.0.0:8080`. Access at `http://192.168.0.39:8080`.

## Sections
1. **Header** - Title, phone number, health indicator (green/yellow/red), auto-refresh timestamp
2. **Stats Row** - Total Calls Today, Contacts Captured, Leads Scored, Avg Lead Score
3. **Lead Pipeline** - Kanban columns: HOT (>=70), WARM (40-69), COLD (<40)
4. **Recent Activity** - Timeline of calls, contacts, leads, callbacks sorted by time
5. **Callbacks Queue** - Upcoming callbacks with overdue highlighting
6. **Contacts Table** - All contacts from `contacts` + `cold-call-leads`
7. **Campaign Status** - Progress bars per campaign
8. **Number Health** - Recent call log with outcome, duration, caller

## Firestore Collections Used
- `call_logs` - call outcomes, durations, timestamps
- `contacts` - captured IT contacts
- `lead_scores` - BANT scores with qualification details
- `cold-call-leads` - leads from cold call agent
- `callbacks` - scheduled follow-up calls
- `email-queue` - queued follow-up emails
- `campaign_runs` - campaign metadata
- `campaign_calls` - individual campaign call records

## Customization
- Colors: Fortinet orange `#EE7623`, dark slate background
- Refresh interval: 30 seconds (change in JS `setInterval`)
- Data limits: 500 docs per collection (change `fetch_collection` limit param)
- Add new sections: add Firestore fetch in `/api/data`, add HTML section + JS renderer

## Dependencies
- Flask (installed in `.venv`)
- google-cloud-firestore (installed in `.venv`)
- Tailwind CSS (CDN)
- Chart.js (CDN, available for future charts)
