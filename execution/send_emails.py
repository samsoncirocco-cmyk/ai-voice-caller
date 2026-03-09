#!/usr/bin/env python3
"""
Send Emails - Process queued emails from Firestore email-queue collection.

When the AI agent offers to send info during a call, it queues an email.
This script renders and sends them.

Usage:
  python3 send_emails.py --list      # Show queued emails
  python3 send_emails.py --dry-run   # Preview rendered templates
  python3 send_emails.py --send      # Send all queued emails
"""
import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Paths & Config ---

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "signalwire.json"
TMP_EMAILS_DIR = BASE_DIR / ".tmp" / "emails"


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


CONFIG = load_config()
db = firestore.Client(project="tatt-pro")

SIGNATURE = """
Samson Cirocco
Territory Account Manager | Fortinet | SLED
"""

# --- Email Templates ---

def template_case_study(data):
    segment = data.get("segment", data.get("account_type", "Government"))
    contact_name = data.get("contact_name", "there")
    subject = f"Fortinet Case Study: How {segment} Organizations Modernize IT Security"
    body = f"""Hi {contact_name},

Following up on our conversation earlier -- I wanted to share a relevant case study
that shows how {segment} organizations like yours have modernized their IT security
infrastructure with Fortinet.

Key highlights:
- Consolidated security stack reducing complexity by 60%+
- AI-driven threat detection with sub-second response times
- Full compliance with {segment} regulatory requirements

I would be happy to walk you through the details and discuss how this maps to your
environment. Would you have 20 minutes this week for a quick demo?

Best regards,
{SIGNATURE}"""
    return subject, body


def template_overview(data):
    account_type = data.get("account_type", data.get("segment", "SLED"))
    contact_name = data.get("contact_name", "there")
    subject = f"Fortinet Solutions Overview for {account_type}"
    body = f"""Hi {contact_name},

Following up on our conversation earlier -- here is a quick overview of the Fortinet
solutions most relevant to {account_type} organizations:

1. Unified SASE - Secure access for distributed workforces with a single platform
   combining SD-WAN, ZTNA, and cloud-delivered security.

2. OT Security - Purpose-built protection for operational technology environments
   with network segmentation and real-time threat intelligence.

3. AI-Driven Security Operations - FortiAI and FortiAnalyzer automate threat
   detection and response across your entire security fabric.

Which of these resonates most with your current priorities? I am happy to dive
deeper into any of them.

Best regards,
{SIGNATURE}"""
    return subject, body


def template_technical(data):
    topic = data.get("specific_topic", data.get("topic", "Security Fabric"))
    account_type = data.get("account_type", data.get("segment", "SLED"))
    contact_name = data.get("contact_name", "there")
    subject = f"Technical Brief: Fortinet {topic} for {account_type}"
    body = f"""Hi {contact_name},

Following up on our conversation earlier -- you mentioned interest in the technical
details around Fortinet {topic}.

Here are the key technical points:

- Architecture: Fortinet {topic} integrates natively with the Security Fabric,
  providing single-pane-of-glass visibility across your environment.
- Deployment: Available as hardware appliance, virtual machine, or cloud-native
  service depending on your infrastructure requirements.
- Performance: Purpose-built ASICs deliver industry-leading throughput without
  compromising inspection depth.
- Compliance: Pre-built templates for CJIS, HIPAA, FedRAMP, and StateRAMP
  requirements common in {account_type} environments.

I can arrange a technical deep-dive with our SE team if you would like to see this
in action. Just let me know what works for your schedule.

Best regards,
{SIGNATURE}"""
    return subject, body


def template_demo(data):
    contact_name = data.get("contact_name", "there")
    subject = "Your Fortinet Demo Request"
    body = f"""Hi {contact_name},

Following up on our conversation earlier -- thank you for your interest in seeing
Fortinet in action.

I would love to set up a personalized demo for you. Here are a few time slots that
work on my end:

- This week: Wednesday or Thursday afternoon (MST)
- Next week: Monday through Wednesday, flexible times

The demo typically runs 30-45 minutes and we can tailor it to focus on the areas
most relevant to your environment. I have also looped in our local partner team
at High Point Networks who can support implementation when you are ready.

Just reply with a time that works and I will send over a calendar invite.

Best regards,
{SIGNATURE}"""
    return subject, body


TEMPLATES = {
    "case_study": template_case_study,
    "overview": template_overview,
    "technical": template_technical,
    "demo": template_demo,
}


def render_email(data):
    """Render an email from queue data. Returns (subject, body) or None."""
    info_type = data.get("info_type", "overview")
    template_fn = TEMPLATES.get(info_type)
    if not template_fn:
        return None, None
    return template_fn(data)


# --- Firestore ---

def get_queued_emails():
    """Fetch all emails with status='queued'."""
    docs = db.collection("email-queue").where(filter=FieldFilter("status", "==", "queued")).stream()
    emails = []
    for doc in docs:
        data = doc.to_dict()
        data["_doc_id"] = doc.id
        emails.append(data)
    return emails


# --- Email Sending ---

def get_smtp_creds():
    """Try to find Gmail SMTP credentials."""
    # Check environment
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if user and password:
        return user, password

    # Check .env file
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GMAIL_USER="):
                    user = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("GMAIL_APP_PASSWORD="):
                    password = line.split("=", 1)[1].strip().strip('"').strip("'")
        if user and password:
            return user, password

    return None, None


def send_via_smtp(to_email, subject, body, gmail_user, gmail_password):
    """Send email via Gmail SMTP. Returns (success, error)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Samson Cirocco <{gmail_user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def save_as_html(doc_id, to_email, subject, body):
    """Save rendered email as HTML file in .tmp/emails/."""
    TMP_EMAILS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d_%H%M%S")
    filename = TMP_EMAILS_DIR / f"{timestamp}_{doc_id}.html"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subject}</title></head>
<body>
<p><strong>To:</strong> {to_email}</p>
<p><strong>Subject:</strong> {subject}</p>
<hr>
<pre style="font-family: Arial, sans-serif; white-space: pre-wrap;">{body}</pre>
</body>
</html>"""

    with open(filename, "w") as f:
        f.write(html)
    return str(filename)


# --- Commands ---

def cmd_list():
    """Show queued emails."""
    emails = get_queued_emails()
    if not emails:
        print("No queued emails.")
        return

    print(f"\nQueued emails ({len(emails)}):")
    print(f"{'='*70}")
    print(f"  {'To':<30} {'Type':<14} {'Contact':<20}")
    print(f"  {'-'*28}   {'-'*12}   {'-'*18}")

    for em in emails:
        to = em.get("email", em.get("to_email", "?"))
        info_type = em.get("info_type", "?")
        name = em.get("contact_name", em.get("name", "?"))
        print(f"  {to:<30} {info_type:<14} {name:<20}")

    print(f"{'='*70}")


def cmd_dry_run():
    """Preview rendered templates without sending."""
    emails = get_queued_emails()
    if not emails:
        print("No queued emails.")
        return

    gmail_user, gmail_password = get_smtp_creds()

    print(f"\nDry Run - {len(emails)} email(s)")
    print(f"SMTP: {'configured (' + gmail_user + ')' if gmail_user else 'NOT configured (will save as HTML)'}")
    print(f"{'='*70}")

    for em in emails:
        to = em.get("email", em.get("to_email", "?"))
        subject, body = render_email(em)
        if not subject:
            print(f"\n  [SKIP] Unknown info_type: {em.get('info_type')}")
            continue

        print(f"\n  To: {to}")
        print(f"  Subject: {subject}")
        print(f"  --- Preview ---")
        # Show first 8 lines of body
        lines = body.strip().split("\n")
        for line in lines[:8]:
            print(f"  | {line}")
        if len(lines) > 8:
            print(f"  | ... ({len(lines) - 8} more lines)")
        print(f"  --- End Preview ---")

    print(f"\n  No emails were sent.")
    print(f"{'='*70}")


def cmd_send():
    """Send all queued emails."""
    emails = get_queued_emails()
    if not emails:
        print("No queued emails.")
        return

    # SAFETY 2026-03-09: Require explicit confirmation before sending real emails.
    # AI agents queued these during calls — Samson must approve before they go out.
    print(f"\n⚠️  APPROVAL REQUIRED: {len(emails)} email(s) queued to real contacts.")
    for em in emails:
        print(f"   → {em.get('email', em.get('to_email', 'unknown'))} ({em.get('info_type', '?')})")
    confirm = input("\nType 'YES SEND' to send, anything else to abort: ").strip()
    if confirm != "YES SEND":
        print("Aborted. No emails sent.")
        return

    gmail_user, gmail_password = get_smtp_creds()

    if use_smtp:
        print(f"Sending via Gmail SMTP ({gmail_user})")
    else:
        print(f"No SMTP credentials found. Saving as HTML to {TMP_EMAILS_DIR}")

    print(f"Processing {len(emails)} email(s)...")
    print(f"{'='*70}")

    sent = 0
    rendered = 0
    failed = 0

    for em in emails:
        doc_id = em["_doc_id"]
        to = em.get("email", em.get("to_email", ""))
        subject, body = render_email(em)

        if not subject:
            print(f"  [SKIP] {doc_id}: unknown info_type '{em.get('info_type')}'" )
            continue

        if not to:
            print(f"  [SKIP] {doc_id}: no email address")
            continue

        if use_smtp:
            ok, err = send_via_smtp(to, subject, body, gmail_user, gmail_password)
            if ok:
                db.collection("email-queue").document(doc_id).update({
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    "sent_via": "gmail_smtp",
                })
                print(f"  [SENT] {to} - {subject[:50]}")
                sent += 1
            else:
                db.collection("email-queue").document(doc_id).update({
                    "status": "failed",
                    "failed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    "failure_reason": err,
                })
                print(f"  [FAILED] {to} - {err}")
                failed += 1
        else:
            filepath = save_as_html(doc_id, to, subject, body)
            db.collection("email-queue").document(doc_id).update({
                "status": "rendered",
                "rendered_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "rendered_file": filepath,
            })
            print(f"  [RENDERED] {to} -> {filepath}")
            rendered += 1

    print(f"\n{'='*70}")
    print(f"  Sent: {sent}  Rendered: {rendered}  Failed: {failed}")
    print(f"{'='*70}")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Process queued emails from Firestore")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Show queued emails")
    group.add_argument("--dry-run", action="store_true", help="Preview rendered templates")
    group.add_argument("--send", action="store_true", help="Send all queued emails")

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.dry_run:
        cmd_dry_run()
    elif args.send:
        cmd_send()


if __name__ == "__main__":
    main()
