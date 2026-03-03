# DIRECTIVE: Follow-Up Automation

**Purpose:** Automatically process callbacks and send follow-up emails queued by the AI agent during calls.

**Updated:** 2026-02-11

---

## Scripts

### process_callbacks.py

Reads the Firestore `callbacks` collection and auto-dials when scheduled time arrives.

```
python3 execution/process_callbacks.py --list        # Show pending callbacks
python3 execution/process_callbacks.py --dry-run     # Preview what would process
python3 execution/process_callbacks.py --process     # Dial due callbacks
```

**Flow:**
1. Query `callbacks` where status = `pending`
2. If `callback_datetime` <= now: place call via Compatibility API
3. Respects `call_rate/state` rate limits (shared with make_call_v4, campaign_runner)
4. Updates callback doc: status -> `called` (with call_sid) or `failed` (with reason)
5. Future callbacks shown as upcoming, not processed

**Firestore collection:** `callbacks`
| Field | Type | Description |
|-------|------|-------------|
| phone | string | Phone number to call back |
| contact_name | string | Contact name |
| callback_datetime | timestamp/string | When to call |
| status | string | pending / called / failed |
| call_sid | string | Set after call placed |
| reason | string | Why they requested callback |

### send_emails.py

Reads the Firestore `email-queue` collection and sends follow-up emails.

```
python3 execution/send_emails.py --list      # Show queued emails
python3 execution/send_emails.py --dry-run   # Preview rendered templates
python3 execution/send_emails.py --send      # Send queued emails
```

**Flow:**
1. Query `email-queue` where status = `queued`
2. Render email from template based on `info_type`
3. If SMTP configured: send via Gmail, mark `sent`
4. If no SMTP: save as HTML in `.tmp/emails/`, mark `rendered`
5. Failed sends marked `failed` with reason

**Firestore collection:** `email-queue`
| Field | Type | Description |
|-------|------|-------------|
| email | string | Recipient email address |
| contact_name | string | Contact name |
| info_type | string | case_study / overview / technical / demo |
| account_type | string | E.g. K-12, Higher Ed, State Gov |
| segment | string | Market segment |
| specific_topic | string | For technical type |
| status | string | queued / sent / rendered / failed |

## Email Templates

Four templates keyed by `info_type`:

- **case_study** - Shares relevant case study for their segment, offers demo
- **overview** - Covers Unified SASE, OT Security, AI-Driven SecOps
- **technical** - Deep-dive on specific topic they asked about
- **demo** - Confirms demo interest, proposes times, mentions High Point Networks partner

All emails: written from Samson's perspective, reference the phone call, include CTA, use signature block.

## Email Setup

To enable SMTP sending, set environment variables or create `.env` at project root:

```
GMAIL_USER=samson.cirocco@gmail.com
GMAIL_APP_PASSWORD=<app-password-from-google>
```

Generate app password: Google Account > Security > 2-Step Verification > App passwords.

Without credentials, emails are saved as HTML files in `.tmp/emails/` for manual sending.

## Dependencies

Uses same packages as the rest of the project:
- `google-cloud-firestore` (Firestore access)
- `requests` (SignalWire API for callbacks)

No additional pip installs needed.

## Self-Anneal Notes

- Callback datetime parsing handles strings, timestamps, and None gracefully
- Rate limit logic mirrors make_call_v4.py exactly (shared Firestore state)
- Email templates are plain text (not HTML) for deliverability
- SWAIG functions `schedule_callback` and `send_info_email` write to these collections
