#!/usr/bin/env python3
"""
SWAIG Webhook Server - Google Cloud Function
Bridges SignalWire Native AI Agent to deterministic execution scripts.

SignalWire POSTs SWAIG function calls here during live conversations.
We route to the appropriate execution script and return the result.

Deployed as: gcloud functions deploy swaigWebhook --gen2 --runtime=python311 ...
"""
import json
import logging
from datetime import datetime, timedelta

import functions_framework
from google.cloud import firestore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Firestore client (reused across invocations in Cloud Functions)
db = firestore.Client(project="tatt-pro")


# --- SWAIG Function Handlers (Discovery) -----------------------

def handle_save_contact(args, metadata):
    """
    Save IT contact to Firestore.
    Harvested from: agents/discovery_agent.py save_contact()
    """
    contact_name = args.get("name", args.get("contact_name", ""))
    contact_phone = args.get("phone", args.get("phone_number", ""))
    account_name = args.get("account", args.get("organization", ""))
    call_sid = metadata.get("ai_session_id", "unknown")
    caller_number = metadata.get("caller_id_num", "")

    if not contact_name:
        return {"response": "I didn't catch the contact name. Could you repeat that?"}

    doc_data = {
        "call_sid": call_sid,
        "name": contact_name,
        "phone": contact_phone,
        "account": account_name,
        "caller_number": caller_number,
        "source": "discovery_call",
        "created_at": datetime.utcnow().isoformat(),
        "status": "new",
    }

    for attempt in range(3):
        try:
            _, doc_ref = db.collection("contacts").add(doc_data)
            logger.info(f"Contact saved: {doc_ref.id} - {contact_name} at {account_name}")
            return {
                "response": f"Got it. I've saved {contact_name}'s information. Thank you so much for your help!"
            }
        except Exception as e:
            logger.warning(f"save_contact attempt {attempt+1} failed: {e}")
            if attempt == 2:
                try:
                    db.collection("emergency_log").add({
                        "type": "save_contact_failed",
                        "data": doc_data,
                        "error": str(e),
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                except Exception:
                    pass
                logger.error(f"save_contact FAILED after 3 attempts: {e}")
                return {
                    "response": "I've noted that information. Thank you for your help!"
                }


def handle_log_call(args, metadata):
    """
    Log call outcome to Firestore.
    Harvested from: execution/log_call.py
    """
    call_sid = metadata.get("ai_session_id", "unknown")
    caller_number = metadata.get("caller_id_num", "")

    outcome = args.get("outcome", "completed")
    duration = args.get("duration", 0)
    summary = args.get("summary", "")

    doc_data = {
        "call_sid": call_sid,
        "caller_number": caller_number,
        "outcome": outcome,
        "duration": duration,
        "summary": summary,
        "cost": round(duration * 0.00044, 4) if duration else 0,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    try:
        db.collection("call_logs").document(call_sid).set(doc_data)
        logger.info(f"Call logged: {call_sid} - {outcome}")
        return {"response": "Call logged successfully."}
    except Exception as e:
        logger.error(f"log_call failed: {e}")
        return {"response": "Call noted."}


def handle_score_lead(args, metadata):
    """
    Calculate BANT lead score (0-100).
    Harvested from: agents/lead_qualification_agent.py score_lead()
    """
    score = 0
    details = []

    pain_points = args.get("pain_points", [])
    if isinstance(pain_points, str):
        pain_points = [p.strip() for p in pain_points.split(",") if p.strip()]
    pain_score = min(len(pain_points) * 5, 15)
    score += pain_score
    if pain_points:
        details.append(f"Pain points: {len(pain_points)} (+{pain_score})")

    system_age = args.get("system_age", 0)
    if system_age >= 7:
        score += 10
        details.append(f"Legacy system: {system_age}yr (+10)")
    elif system_age >= 5:
        score += 5
        details.append(f"Aging system: {system_age}yr (+5)")

    current_system = (args.get("current_system", "") or "").lower()
    legacy = ["cisco", "avaya", "nortel", "nec", "mitel", "shoretel"]
    if any(v in current_system for v in legacy):
        score += 5
        details.append(f"Legacy vendor: {current_system} (+5)")

    timeline = (args.get("timeline", "") or "").lower()
    timeline_map = {
        "within_3_months": 25, "active_project": 25,
        "within_6_months": 20, "within_12_months": 10,
        "next_year": 5, "no_plans": 0,
    }
    t_score = timeline_map.get(timeline, 0)
    score += t_score
    if t_score:
        details.append(f"Timeline: {timeline} (+{t_score})")

    user_count = args.get("user_count", 0)
    if user_count >= 500:
        score += 15
        details.append(f"Enterprise: {user_count} users (+15)")
    elif user_count >= 100:
        score += 10
        details.append(f"Large: {user_count} users (+10)")
    elif user_count >= 25:
        score += 5
        details.append(f"Medium: {user_count} users (+5)")

    if args.get("erate_eligible"):
        score += 10
        details.append("E-Rate eligible (+10)")

    authority = (args.get("decision_authority", "") or "").lower()
    auth_map = {"decision_maker": 20, "influencer": 10, "recommender": 10, "gatekeeper": 0}
    a_score = auth_map.get(authority, 5)
    score += a_score
    if a_score:
        details.append(f"Authority: {authority} (+{a_score})")

    if score >= 70:
        qualification = "hot"
        action = "Book a meeting"
    elif score >= 40:
        qualification = "warm"
        action = "Send info and schedule follow-up"
    else:
        qualification = "cold"
        action = "Nurture"

    call_sid = metadata.get("ai_session_id", "unknown")
    try:
        db.collection("lead_scores").document(call_sid).set({
            "call_sid": call_sid,
            "score": score,
            "qualification": qualification,
            "details": details,
            "raw_args": args,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        logger.info(f"Lead scored: {call_sid} = {score}/100 ({qualification})")
    except Exception as e:
        logger.error(f"Failed to save lead score: {e}")

    return {
        "response": f"Lead score: {score} out of 100. Qualification: {qualification}. Recommended action: {action}."
    }


# --- SWAIG Function Handlers (Cold Call) -----------------------

def handle_save_lead(args, metadata):
    """
    Save lead with qualification details to Firestore.
    Harvested from: agents/cold_call_agent.py save_lead()
    Collection: cold-call-leads
    """
    contact_name = args.get("contact_name", "")
    outcome = args.get("outcome", "unknown")
    interest_level = args.get("interest_level", "unknown")
    pain_points = args.get("pain_points", "")
    current_system = args.get("current_system", "")
    competitor_mentioned = args.get("competitor_mentioned", "")
    notes = args.get("notes", "")

    call_sid = metadata.get("ai_session_id", "unknown")
    caller_number = metadata.get("caller_id_num", "")

    # Normalize pain_points to list
    if isinstance(pain_points, str):
        pain_points = [p.strip() for p in pain_points.split(",") if p.strip()] if pain_points else []

    if not contact_name:
        return {"response": "I didn't catch the contact name. Could you repeat that?"}

    doc_data = {
        "contact_name": contact_name,
        "outcome": outcome,
        "interest_level": interest_level,
        "pain_points": pain_points,
        "current_system": current_system,
        "competitor_mentioned": competitor_mentioned,
        "notes": notes,
        "phone_number": caller_number,
        "call_sid": call_sid,
        "source": "cold-call-agent",
        "status": "new",
        "follow_up_required": outcome in ["qualified", "callback_requested"],
        "created_at": datetime.utcnow().isoformat(),
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    try:
        _, doc_ref = db.collection("cold-call-leads").add(doc_data)
        logger.info(f"Lead saved: {doc_ref.id} - {contact_name} ({outcome}/{interest_level})")
        return {
            "response": f"Lead saved: {contact_name} - {outcome} ({interest_level})."
        }
    except Exception as e:
        logger.error(f"save_lead failed: {e}")
        return {"response": "I've noted that information. Thank you."}


def handle_schedule_callback(args, metadata):
    """
    Schedule a follow-up callback task in Firestore.
    Harvested from: agents/cold_call_agent.py schedule_callback()
    Collection: callbacks
    """
    contact_name = args.get("contact_name", "")
    callback_datetime_str = args.get("callback_datetime", "")
    reason = args.get("reason", "Follow-up on Fortinet solutions")
    phone_number = args.get("phone_number", "")

    call_sid = metadata.get("ai_session_id", "unknown")
    caller_number = metadata.get("caller_id_num", "")
    if not phone_number:
        phone_number = caller_number

    if not contact_name:
        return {"response": "I didn't catch the contact name. Could you repeat that?"}

    # Parse callback datetime
    try:
        callback_dt = datetime.fromisoformat(callback_datetime_str.replace("Z", "+00:00"))
    except Exception:
        callback_dt = datetime.utcnow() + timedelta(days=1)
        callback_dt = callback_dt.replace(hour=17, minute=0, second=0, microsecond=0)

    doc_data = {
        "contact_name": contact_name,
        "phone_number": phone_number,
        "callback_datetime": callback_dt.isoformat(),
        "reason": reason,
        "status": "pending",
        "call_sid": call_sid,
        "source": "cold-call-agent",
        "type": "callback_task",
        "created_at": datetime.utcnow().isoformat(),
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    try:
        _, doc_ref = db.collection("callbacks").add(doc_data)
        formatted = callback_dt.strftime("%Y-%m-%d at %I:%M %p")
        logger.info(f"Callback scheduled: {doc_ref.id} - {contact_name} on {formatted}")
        return {
            "response": f"Callback scheduled for {contact_name} on {formatted}. Reason: {reason}."
        }
    except Exception as e:
        logger.error(f"schedule_callback failed: {e}")
        return {"response": "I've noted that callback request. Thank you."}


def handle_send_info_email(args, metadata):
    """
    Queue a follow-up email to the prospect.
    Harvested from: agents/cold_call_agent.py send_info_email()
    Collection: email-queue
    """
    contact_name = args.get("contact_name", "")
    email = args.get("email", "")
    info_type = args.get("info_type", "overview")
    specific_topic = args.get("specific_topic", "")

    call_sid = metadata.get("ai_session_id", "unknown")
    caller_number = metadata.get("caller_id_num", "")

    if not contact_name or not email:
        return {"response": "I need the contact name and email address. Could you repeat that?"}

    doc_data = {
        "contact_name": contact_name,
        "email": email,
        "info_type": info_type,
        "specific_topic": specific_topic,
        "phone_number": caller_number,
        "call_sid": call_sid,
        "status": "queued",
        "source": "cold-call-agent",
        "type": "email_task",
        "created_at": datetime.utcnow().isoformat(),
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    try:
        _, doc_ref = db.collection("email-queue").add(doc_data)
        logger.info(f"Email queued: {doc_ref.id} - {info_type} to {email}")
        return {
            "response": f"Email queued: {info_type} about {specific_topic or 'Fortinet solutions'} will be sent to {email}."
        }
    except Exception as e:
        logger.error(f"send_info_email failed: {e}")
        return {"response": "I've noted that email request. Thank you."}


# --- SWAIG Router ----------------------------------------------

SWAIG_FUNCTIONS = {
    "save_contact": handle_save_contact,
    "log_call": handle_log_call,
    "score_lead": handle_score_lead,
    "save_lead": handle_save_lead,
    "schedule_callback": handle_schedule_callback,
    "send_info_email": handle_send_info_email,
}


@functions_framework.http
def swaig_handler(request):
    """
    Main entry point for Google Cloud Function.
    SignalWire sends POST with SWAIG function call data.
    """
    if request.method == "OPTIONS":
        return ("", 204, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    if request.method != "POST":
        return (json.dumps({"error": "POST required"}), 405)

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        return (json.dumps({"error": "Invalid JSON"}), 400)

    logger.info(f"SWAIG request: function={data.get('function')}, session={data.get('ai_session_id', 'n/a')}")

    function_name = data.get("function")
    if not function_name:
        return (json.dumps({"error": "Missing 'function' field"}), 400)

    handler = SWAIG_FUNCTIONS.get(function_name)
    if not handler:
        logger.warning(f"Unknown SWAIG function: {function_name}")
        return (json.dumps({"response": f"Unknown function: {function_name}"}), 200)

    # Extract arguments - SignalWire sends parsed args in argument.parsed[0]
    argument = data.get("argument", {})
    if isinstance(argument, dict):
        parsed = argument.get("parsed", [{}])
        if isinstance(parsed, list) and parsed:
            args = parsed[0] if isinstance(parsed[0], dict) else {}
        else:
            args = {}
        if not args:
            raw = argument.get("raw", "{}")
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                args = {}
    else:
        args = {}

    metadata = {
        "ai_session_id": data.get("ai_session_id", ""),
        "caller_id_num": data.get("caller_id_num", ""),
        "project_id": data.get("project_id", ""),
    }

    try:
        result = handler(args, metadata)
        return (json.dumps(result), 200, {"Content-Type": "application/json"})
    except Exception as e:
        logger.error(f"Handler error for {function_name}: {e}", exc_info=True)
        return (json.dumps({"response": "I've noted that. Thank you."}), 200)
