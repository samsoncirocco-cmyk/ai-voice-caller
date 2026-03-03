#!/usr/bin/env python3
"""
skill_fortinet_sled_campaign.py

OpenClaw Skill: Fortinet SLED Voice Campaign

Research-powered batch voice calling with AI conversation for SLED prospect qualification.

This script is designed to run inside OpenClaw sandbox. It handles:
  1. CSV loading + phone normalization
  2. Rate limit enforcement (30s between calls, 20/hr, 100/day)
  3. Per-lead account research (OpenRouter Perplexity Sonar)
  4. SWML building with personalized intel
  5. SignalWire call placement (Compatibility API)
  6. Webhook monitoring for post-call summaries
  7. State persistence for resumability
  8. Comprehensive error logging

Environment Variables:
  SIGNALWIRE_PROJECT_ID          Project ID from SignalWire
  SIGNALWIRE_AUTH_TOKEN          Auth token from SignalWire
  SIGNALWIRE_SPACE_URL           Space URL (e.g., 6eyes.signalwire.com)
  OPENROUTER_API_KEY             API key for OpenRouter (Perplexity Sonar)
  OPENAI_API_KEY                 Fallback OpenAI key (optional)
  WEBHOOK_DOMAIN                 Domain for post-call summaries (default: hooks.6eyes.dev)

Usage:
  python3 skill_fortinet_sled_campaign.py --help
  python3 skill_fortinet_sled_campaign.py \
    --csv-file campaigns/sled-territory-832.csv \
    --campaign-name sled-march \
    --limit 10 \
    --interval-seconds 30 \
    --voice-lane A \
    --business-hours-only
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "campaigns" / ".state"
RESEARCH_CACHE_DIR = BASE_DIR / "campaigns" / ".research_cache"
RESULTS_DIR = BASE_DIR / "campaigns" / ".results"

# Create directories if they don't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# SignalWire Configuration
SIGNALWIRE_PROJECT_ID = os.environ.get("SIGNALWIRE_PROJECT_ID")
SIGNALWIRE_AUTH_TOKEN = os.environ.get("SIGNALWIRE_AUTH_TOKEN")
SIGNALWIRE_SPACE_URL = os.environ.get("SIGNALWIRE_SPACE_URL", "6eyes.signalwire.com")

# API Keys
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Webhook
WEBHOOK_DOMAIN = os.environ.get("WEBHOOK_DOMAIN", "hooks.6eyes.dev")

# Voice Lanes
LANES = {
    "A": {
        "voice": "openai.onyx",
        "from_number": "+16028985026",
        "prompt_file": "prompts/paul.txt",
        "persona": "Municipal/Government"
    },
    "B": {
        "voice": "gcloud.en-US-Casual-K",
        "from_number": "+14806024668",
        "prompt_file": "prompts/cold_outreach.txt",
        "persona": "Cold List"
    }
}

# Rate Limits
MIN_INTERVAL_SECONDS = 30
MAX_CALLS_PER_HOUR = 20
MAX_CALLS_PER_DAY = 100
COOLDOWN_ON_FAILURE_SECONDS = 300
MAX_CONSECUTIVE_FAILURES = 3

# Timeouts
RESEARCH_TIMEOUT = 30
CALL_PLACEMENT_TIMEOUT = 10
WEBHOOK_WAIT_TIMEOUT = 30

# Central Time Zone (for business hours)
BUSINESS_HOURS_START = 8  # 08:00
BUSINESS_HOURS_END = 17   # 17:00
BUSINESS_HOURS_TZ = "America/Chicago"


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING & OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

class Logger:
    """Structured logging with timestamps and levels."""
    
    def __init__(self, name):
        self.name = name
        self.log_file = LOG_DIR / f"{name}.log"
        
    def log(self, level, message, **details):
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            **details
        }
        # Print to console
        print(f"[{timestamp}] {level:8s} {message}")
        if details:
            for k, v in details.items():
                print(f"             {k}: {v}")
        # Append to log file
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def debug(self, msg, **kw): self.log("DEBUG", msg, **kw)
    def info(self, msg, **kw): self.log("INFO", msg, **kw)
    def warn(self, msg, **kw): self.log("WARN", msg, **kw)
    def error(self, msg, **kw): self.log("ERROR", msg, **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_phone(raw):
    """Normalize phone to E.164 format (+1XXXXXXXXXX)."""
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def is_business_hours():
    """Check if current time is within business hours (Central Time)."""
    try:
        import pytz
        tz = pytz.timezone(BUSINESS_HOURS_TZ)
        now = datetime.now(tz)
        return BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END
    except ImportError:
        # Fallback if pytz not available: assume UTC offset of -6 (CST)
        utc_now = datetime.now(timezone.utc)
        cst_now = utc_now - timedelta(hours=6)
        return BUSINESS_HOURS_START <= cst_now.hour < BUSINESS_HOURS_END


def wait_until_business_hours(logger):
    """Block until business hours start."""
    logger.info("Outside business hours, waiting...")
    while not is_business_hours():
        time.sleep(60)
        logger.debug("Checking business hours...")
    logger.info("Business hours started, resuming calls")


# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """State-based rate limiter with cooldown, hourly, and daily limits."""
    
    def __init__(self, campaign_name, logger):
        self.campaign_name = campaign_name
        self.logger = logger
        self.state_file = STATE_DIR / f"{campaign_name}_rate_limit.json"
        self.state = self._load_state()
    
    def _load_state(self):
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {
            "last_call_timestamp": 0,
            "calls_this_hour": 0,
            "calls_this_day": 0,
            "consecutive_failures": 0,
            "cooldown_until": None,
            "hourly_window_reset": int(time.time()),
            "daily_window_reset": int(time.time()),
        }
    
    def _save_state(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)
    
    def check_and_wait(self):
        """Check rate limits and wait if necessary. Return True if OK to proceed, False if skip."""
        now = int(time.time())
        
        # Check cooldown
        if self.state["cooldown_until"] and self.state["cooldown_until"] > now:
            wait_time = self.state["cooldown_until"] - now
            self.logger.warn(
                "Rate limit cooldown active",
                wait_seconds=wait_time,
                reason="3 consecutive failures"
            )
            return False
        
        # Reset hourly/daily counters if windows expired
        if now - self.state["hourly_window_reset"] >= 3600:
            self.state["calls_this_hour"] = 0
            self.state["hourly_window_reset"] = now
        
        if now - self.state["daily_window_reset"] >= 86400:
            self.state["calls_this_day"] = 0
            self.state["daily_window_reset"] = now
        
        # Check daily limit
        if self.state["calls_this_day"] >= MAX_CALLS_PER_DAY:
            self.logger.warn(
                "Daily rate limit reached",
                calls_this_day=self.state["calls_this_day"],
                limit=MAX_CALLS_PER_DAY
            )
            return False
        
        # Check hourly limit (if reached, wait for window to reset)
        if self.state["calls_this_hour"] >= MAX_CALLS_PER_HOUR:
            wait_time = 3600 - (now - self.state["hourly_window_reset"])
            self.logger.info(
                "Hourly rate limit reached, waiting for window reset",
                wait_seconds=wait_time,
                calls_this_hour=self.state["calls_this_hour"]
            )
            time.sleep(wait_time)
            self.state["calls_this_hour"] = 0
            self.state["hourly_window_reset"] = int(time.time())
        
        # Check minimum interval between calls
        since_last = now - self.state["last_call_timestamp"]
        if since_last < MIN_INTERVAL_SECONDS:
            wait_time = MIN_INTERVAL_SECONDS - since_last
            self.logger.debug(
                "Enforcing minimum interval between calls",
                wait_seconds=wait_time
            )
            time.sleep(wait_time)
        
        self._save_state()
        return True
    
    def record_call(self, success):
        """Record a call attempt and update state."""
        now = int(time.time())
        self.state["last_call_timestamp"] = now
        self.state["calls_this_hour"] += 1
        self.state["calls_this_day"] += 1
        
        if success:
            self.state["consecutive_failures"] = 0
            self.logger.debug(
                "Call succeeded, reset failure counter",
                calls_this_hour=self.state["calls_this_hour"],
                calls_this_day=self.state["calls_this_day"]
            )
        else:
            self.state["consecutive_failures"] += 1
            if self.state["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                self.state["cooldown_until"] = now + COOLDOWN_ON_FAILURE_SECONDS
                self.logger.warn(
                    "3 consecutive failures, entering cooldown",
                    cooldown_seconds=COOLDOWN_ON_FAILURE_SECONDS
                )
                self.state["consecutive_failures"] = 0
            self.logger.warn(
                "Call failed",
                consecutive_failures=self.state["consecutive_failures"]
            )
        
        self._save_state()


# ═══════════════════════════════════════════════════════════════════════════════
# RESEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

RESEARCH_PROMPT = """Research the following organization for a cold call about network security:

Organization: {account_name}
Location: {state}
Type: {account_type}

Return a JSON object with EXACTLY these fields (no markdown, no backticks, just raw JSON):
{{
  "summary": "2-3 sentence overview of the organization, size, and what they do",
  "contacts": [
    {{
      "name": "Full name if found, else null",
      "title": "Job title (IT Director, Technology Coordinator, Superintendent, etc.)",
      "email": "Email address if publicly available, else null",
      "phone": "Direct phone if publicly available, else null",
      "source_url": "URL where this person was found",
      "confidence": "high | medium | low"
    }}
  ],
  "hook_1": "A specific, personalized opening line referencing something current about this org",
  "hook_2": "A second alternative opening hook using different intel",
  "pain_points": ["list", "of", "likely", "pain", "points"],
  "tech_intel": "Any known technology vendors or current equipment",
  "budget_cycle": "When their fiscal year starts and budget cycle info",
  "conversation_starters": ["2-3", "open-ended", "questions"]
}}

If you cannot find specific information, make reasonable inferences based on the organization type. Be factual."""


def research_account(account_name, state, account_type, logger):
    """Research an organization using OpenRouter Perplexity Sonar."""
    
    # Check cache first
    cache_key = f"{account_name}_{state}_{account_type}".replace(" ", "_").lower()
    cache_file = RESEARCH_CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        logger.debug("Research found in cache", cache_key=cache_key)
        with open(cache_file) as f:
            return json.load(f)
    
    if not OPENROUTER_API_KEY:
        logger.warn("OPENROUTER_API_KEY not set, skipping research", account=account_name)
        return {
            "summary": f"{account_name} in {state}",
            "contacts": [],
            "hook_1": f"Calling {account_name}...",
            "hook_2": f"Reaching out about network security",
            "pain_points": [],
            "tech_intel": "Unknown",
            "budget_cycle": "Unknown",
            "conversation_starters": ["How are you handling network security?"]
        }
    
    logger.info("Researching account via OpenRouter", account=account_name, state=state)
    
    prompt = RESEARCH_PROMPT.format(
        account_name=account_name,
        state=state,
        account_type=account_type
    )
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "perplexity/sonar",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=RESEARCH_TIMEOUT,
        )
        
        if response.status_code != 200:
            logger.warn(
                "Research API error",
                status_code=response.status_code,
                response=response.text[:500]
            )
            # Return minimal response
            return {
                "summary": f"{account_name} in {state}",
                "contacts": [],
                "hook_1": "Calling...",
                "hook_2": "Reaching out about security",
                "pain_points": [],
                "tech_intel": "Unknown",
                "budget_cycle": "Unknown",
                "conversation_starters": ["How are you handling network security?"]
            }
        
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        # Parse JSON response
        try:
            intel = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
            if match:
                intel = json.loads(match.group(1))
            else:
                logger.warn("Could not parse research response as JSON", account=account_name)
                return {
                    "summary": f"{account_name} in {state}",
                    "contacts": [],
                    "hook_1": "Reaching out...",
                    "hook_2": "Contacting about network security",
                    "pain_points": [],
                    "tech_intel": "Unknown",
                    "budget_cycle": "Unknown",
                    "conversation_starters": ["How are you handling IT security?"]
                }
        
        # Cache the result
        with open(cache_file, "w") as f:
            json.dump(intel, f, indent=2)
        
        logger.info("Research completed", account=account_name, contacts_found=len(intel.get("contacts", [])))
        return intel
    
    except requests.Timeout:
        logger.error("Research API timeout", account=account_name)
        return None
    except Exception as e:
        logger.error("Research error", account=account_name, error=str(e), traceback=traceback.format_exc())
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SWML BUILDING
# ═══════════════════════════════════════════════════════════════════════════════

POST_PROMPT_INSTRUCTION = (
    "Summarize the call in this exact format:\n"
    "- Call outcome: [Connected / Left Voicemail / No Answer / Wrong Number / Not Interested / Meeting Booked]\n"
    "- Spoke with: [name or 'unknown']\n"
    "- Role: [title/role]\n"
    "- Organization: [org name]\n"
    "- Current vendor: [if mentioned, else 'unknown']\n"
    "- Current setup: [what they said about their IT/security environment]\n"
    "- Pain points: [frustrations or challenges mentioned]\n"
    "- Interest level: [1-5]\n"
    "- Follow-up: [what was agreed, or 'none']\n"
    "- Meeting booked: [yes/no — if yes, include day and time]\n"
    "- Contact email: [if collected, else 'none']\n"
    "- Contact direct phone: [if collected, else 'none']\n"
    "- Notes: [anything else useful]"
)


def load_prompt_file(prompt_path, logger):
    """Load prompt from file."""
    full_path = BASE_DIR / prompt_path
    if not full_path.exists():
        logger.warn("Prompt file not found", path=prompt_path)
        return "You are an outreach representative for network security solutions. Be conversational and helpful."
    with open(full_path) as f:
        return f.read().strip()


def build_swml(prompt_text, research_intel, voice, account_name, logger):
    """Build SWML with personalized intel from research."""
    
    # Build personalized prompt with research intel
    personalized_prompt = f"""YOU ARE CALLING: {account_name}

RESEARCH INTEL:
- Summary: {research_intel.get('summary', 'Unknown')}
- Key contact: {research_intel.get('contacts', [{}])[0].get('name', 'Unknown')}
- Pain points: {', '.join(research_intel.get('pain_points', []))}
- Tech intel: {research_intel.get('tech_intel', 'Unknown')}

PRIMARY HOOK: {research_intel.get('hook_1', 'Reach out about network security')}
BACKUP HOOK: {research_intel.get('hook_2', 'Discuss current setup')}

CONVERSATION STARTERS: {', '.join(research_intel.get('conversation_starters', []))}

---

{prompt_text}"""
    
    default_greeting = (
        f"Hi there! This is Paul calling from Fortinet. "
        f"I'm reaching out to IT leaders about network security solutions. "
        f"Do you have just a minute?"
    )
    
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {
                    "ai": {
                        "languages": [
                            {
                                "name": "English",
                                "code": "en-US",
                                "voice": voice
                            }
                        ],
                        "prompt": {
                            "text": personalized_prompt,
                            "temperature": 0.8
                        },
                        "post_prompt": {
                            "text": POST_PROMPT_INSTRUCTION
                        },
                        "post_prompt_url": f"https://{WEBHOOK_DOMAIN}/voice-caller/post-call",
                        "params": {
                            "direction": "outbound",
                            "wait_for_user": False,
                            "speak_when_spoken_to": False,
                            "start_paused": False,
                            "static_greeting": default_greeting,
                            "outbound_attention_timeout": 30000
                        },
                        "engine": {
                            "asr": {"engine": "deepgram", "model": "nova-3"}
                        }
                    }
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNALWIRE CALLING
# ═══════════════════════════════════════════════════════════════════════════════

def place_call(to_number, from_number, voice, prompt_text, account_name, research_intel, logger):
    """Place call via SignalWire Compatibility API with inline SWML."""
    
    if not SIGNALWIRE_PROJECT_ID or not SIGNALWIRE_AUTH_TOKEN:
        logger.error("SignalWire credentials not configured", missing="PROJECT_ID or AUTH_TOKEN")
        return None, "Missing SignalWire credentials"
    
    swml = build_swml(prompt_text, research_intel, voice, account_name, logger)
    auth_b64 = base64.b64encode(
        f"{SIGNALWIRE_PROJECT_ID}:{SIGNALWIRE_AUTH_TOKEN}".encode()
    ).decode()
    
    payload = {
        "command": "dial",
        "params": {
            "from": from_number,
            "to": to_number,
            "swml": swml
        }
    }
    
    url = f"https://{SIGNALWIRE_SPACE_URL}/api/calling/calls"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_b64}"
    }
    
    logger.info(
        "Placing call",
        to=to_number,
        from_number=from_number,
        voice=voice,
        account=account_name
    )
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=CALL_PLACEMENT_TIMEOUT
        )
        
        logger.debug(
            "SignalWire API response",
            status_code=response.status_code,
            response=response.text[:500]
        )
        
        if response.status_code == 200:
            try:
                result = response.json()
                call_id = result.get("call_sid") or result.get("call_id")
                logger.info("Call initiated successfully", call_id=call_id, to=to_number)
                return call_id, "success"
            except json.JSONDecodeError:
                logger.warn("Could not parse call response JSON", response=response.text[:200])
                return None, f"Call API error: {response.status_code}"
        else:
            logger.warn(
                "Call placement failed",
                status_code=response.status_code,
                response=response.text[:500]
            )
            return None, f"SignalWire API error: {response.status_code}"
    
    except requests.Timeout:
        logger.error("Call placement timeout", to=to_number)
        return None, "Call placement timeout"
    except Exception as e:
        logger.error(
            "Call placement exception",
            to=to_number,
            error=str(e),
            traceback=traceback.format_exc()
        )
        return None, f"Exception: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════════
# CALL LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

class CallLogger:
    """Logs calls to JSONL and CSV."""
    
    def __init__(self, campaign_name):
        self.campaign_name = campaign_name
        self.jsonl_file = LOG_DIR / "call_summaries.jsonl"
        self.csv_file = RESULTS_DIR / f"{campaign_name}_results.csv"
        self._init_csv()
    
    def _init_csv(self):
        """Initialize CSV with headers if it doesn't exist."""
        if not self.csv_file.exists():
            with open(self.csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "phone", "name", "account", "call_status", "call_id",
                    "duration_seconds", "outcome", "timestamp"
                ])
                writer.writeheader()
    
    def log_call(self, phone, name, account, call_id, status, error_msg=None):
        """Log call to CSV."""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        with open(self.csv_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "phone", "name", "account", "call_status", "call_id",
                "duration_seconds", "outcome", "timestamp"
            ])
            writer.writerow({
                "phone": phone,
                "name": name or "",
                "account": account or "",
                "call_status": status,
                "call_id": call_id or "",
                "duration_seconds": "",
                "outcome": error_msg or status,
                "timestamp": timestamp
            })
    
    def log_post_call_summary(self, call_id, summary):
        """Log post-call summary to JSONL."""
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "call_id": call_id,
            "summary": summary
        }
        with open(self.jsonl_file, "a") as f:
            f.write(json.dumps(entry) + "\n")


# ═════════════════════════════════════════════════════════════════════════════════
# CAMPAIGN STATE MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════════

class CampaignState:
    """Tracks which leads have been processed for resumability."""
    
    def __init__(self, campaign_name):
        self.campaign_name = campaign_name
        self.state_file = STATE_DIR / f"{campaign_name}_campaign.json"
        self.state = self._load()
    
    def _load(self):
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {
            "campaign_name": self.campaign_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resumed_at": None,
            "processed_indices": [],
            "skipped_indices": [],
            "failed_indices": [],
            "calls_placed": 0,
        }
    
    def _save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)
    
    def is_processed(self, index):
        return index in self.state["processed_indices"]
    
    def mark_processed(self, index):
        if index not in self.state["processed_indices"]:
            self.state["processed_indices"].append(index)
        self._save()
    
    def mark_skipped(self, index):
        if index not in self.state["skipped_indices"]:
            self.state["skipped_indices"].append(index)
        self._save()
    
    def mark_failed(self, index):
        if index not in self.state["failed_indices"]:
            self.state["failed_indices"].append(index)
        self._save()
    
    def increment_calls(self):
        self.state["calls_placed"] += 1
        self._save()


# ═════════════════════════════════════════════════════════════════════════════════
# MAIN SKILL EXECUTION
# ═════════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw Skill: Fortinet SLED Voice Campaign"
    )
    parser.add_argument("--csv-file", required=True, help="Path to CSV file with leads")
    parser.add_argument("--campaign-name", required=True, help="Unique campaign identifier")
    parser.add_argument("--limit", type=int, default=None, help="Max calls to place (default: all)")
    parser.add_argument("--interval-seconds", type=int, default=30, help="Min seconds between calls")
    parser.add_argument("--voice-lane", choices=["A", "B"], default="A", help="Voice lane (A or B)")
    parser.add_argument("--business-hours-only", action="store_true", help="Pause outside 8am-5pm CT")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted campaign")
    parser.add_argument("--dry-run", action="store_true", help="Research only, no calls")
    
    args = parser.parse_args()
    
    campaign_name = args.campaign_name
    logger = Logger(f"campaign_{campaign_name}")
    
    logger.info(
        "Campaign started",
        campaign_name=campaign_name,
        csv_file=args.csv_file,
        limit=args.limit,
        voice_lane=args.voice_lane,
        dry_run=args.dry_run,
        resume=args.resume
    )
    
    # Validate inputs
    if not Path(args.csv_file).exists():
        logger.error("CSV file not found", path=args.csv_file)
        return {"status": "failed", "error": f"CSV file not found: {args.csv_file}"}
    
    # Load CSV
    leads = []
    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            phone_raw = row.get("phone", "").strip()
            phone = normalize_phone(phone_raw)
            if not phone:
                logger.warn("Invalid phone number, skipping", phone_raw=phone_raw, row=i)
                continue
            leads.append({
                "index": i,
                "phone": phone,
                "name": row.get("name", "").strip() or None,
                "account": row.get("account", "").strip() or None,
                "notes": row.get("notes", "").strip() or None
            })
    
    logger.info("Loaded leads from CSV", total_leads=len(leads))
    
    # Initialize components
    rate_limiter = RateLimiter(campaign_name, logger)
    call_logger = CallLogger(campaign_name)
    campaign_state = CampaignState(campaign_name)
    lane_config = LANES[args.voice_lane]
    prompt_text = load_prompt_file(lane_config["prompt_file"], logger)
    
    # Resume logic
    if args.resume:
        logger.info("Resuming campaign", already_processed=len(campaign_state.state["processed_indices"]))
        campaign_state.state["resumed_at"] = datetime.now(timezone.utc).isoformat()
        campaign_state._save()
    
    # Execute campaign
    calls_attempted = 0
    calls_placed = 0
    calls_failed = 0
    
    for lead in leads:
        # Check resume
        if args.resume and campaign_state.is_processed(lead["index"]):
            logger.debug("Skipping already-processed lead", phone=lead["phone"])
            continue
        
        # Check business hours
        if args.business_hours_only and not is_business_hours():
            logger.info("Outside business hours, pausing...")
            wait_until_business_hours(logger)
        
        # Check rate limits
        if not rate_limiter.check_and_wait():
            logger.warn("Rate limit preventing call", phone=lead["phone"])
            campaign_state.mark_skipped(lead["index"])
            call_logger.log_call(
                lead["phone"], lead["name"], lead["account"],
                None, "skipped", "Rate limited"
            )
            calls_attempted += 1
            continue
        
        calls_attempted += 1
        
        # Research
        logger.info("Processing lead", phone=lead["phone"], account=lead["account"])
        
        research_intel = research_account(
            lead["account"] or lead["phone"],
            "Unknown",
            "SLED",
            logger
        )
        
        if research_intel is None:
            logger.error("Research failed, skipping call", phone=lead["phone"])
            campaign_state.mark_failed(lead["index"])
            call_logger.log_call(
                lead["phone"], lead["name"], lead["account"],
                None, "failed", "Research error"
            )
            calls_failed += 1
            rate_limiter.record_call(False)
            continue
        
        # Build and place call
        if args.dry_run:
            logger.info("DRY RUN: Would place call", phone=lead["phone"], account=lead["account"])
            campaign_state.mark_processed(lead["index"])
            call_logger.log_call(
                lead["phone"], lead["name"], lead["account"],
                None, "dry_run_skipped", "Dry run mode"
            )
            continue
        
        call_id, status = place_call(
            lead["phone"],
            lane_config["from_number"],
            lane_config["voice"],
            prompt_text,
            lead["account"] or lead["phone"],
            research_intel,
            logger
        )
        
        if call_id:
            calls_placed += 1
            rate_limiter.record_call(True)
            campaign_state.increment_calls()
            campaign_state.mark_processed(lead["index"])
            call_logger.log_call(
                lead["phone"], lead["name"], lead["account"],
                call_id, "initiated", None
            )
            logger.info("Call placed successfully", call_id=call_id, phone=lead["phone"])
        else:
            calls_failed += 1
            rate_limiter.record_call(False)
            campaign_state.mark_failed(lead["index"])
            call_logger.log_call(
                lead["phone"], lead["name"], lead["account"],
                None, "failed", status
            )
            logger.error("Call placement failed", phone=lead["phone"], reason=status)
        
        # Apply interval limit
        if args.limit and calls_placed >= args.limit:
            logger.info("Reached call limit, stopping campaign", limit=args.limit)
            break
    
    # Summary
    summary = {
        "status": "success" if calls_placed > 0 else ("partial_success" if calls_attempted > 0 else "failed"),
        "campaign_name": campaign_name,
        "leads_total": len(leads),
        "calls_attempted": calls_attempted,
        "calls_placed": calls_placed,
        "calls_failed": calls_failed,
        "calls_skipped": calls_attempted - calls_placed - calls_failed,
        "results_csv": str(call_logger.csv_file),
        "call_log_jsonl": str(call_logger.jsonl_file),
        "campaign_state": str(campaign_state.state_file),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    logger.info("Campaign completed", **summary)
    print("\n" + "="*80)
    print("CAMPAIGN SUMMARY")
    print("="*80)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("="*80)
    
    return summary


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result.get("status") in ["success", "partial_success"] else 1)
