#!/usr/bin/env python3
"""
Batch Call Script for AI Voice Caller

Initiates batch calls from a CSV file using SignalWire.
Includes rate limiting, retry logic, and progress tracking.

Usage:
    python batch-call.py leads.csv --flow cold-calling --max-concurrent 5
    python batch-call.py leads.csv --dry-run  # Preview without calling

CSV Format:
    phone,name,account,email,state,current_system
    +15551234567,John Smith,Cityville Schools,jsmith@city.edu,AZ,Cisco
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Check for required packages
try:
    from signalwire.rest import Client as SignalWireClient
except ImportError:
    print("Error: signalwire package not installed")
    print("Install with: pip install signalwire")
    sys.exit(1)

try:
    from google.cloud import firestore
except ImportError:
    print("Warning: google-cloud-firestore not installed, call logging disabled")
    firestore = None

# Configuration
DEFAULT_REGION = "us-central1"
DEFAULT_PROJECT = "tatt-pro"
CALLS_PER_MINUTE = 30  # Rate limit
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@dataclass
class Lead:
    """Represents a lead to call."""
    phone: str
    name: str
    account: str
    email: Optional[str] = None
    state: Optional[str] = None
    current_system: Optional[str] = None
    use_case: str = "cold_calling"
    campaign: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CallResult:
    """Result of a call attempt."""
    lead: Lead
    success: bool
    call_sid: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None
    timestamp: Optional[datetime] = None
    duration: int = 0


class BatchCaller:
    """Manages batch calling operations."""
    
    def __init__(
        self,
        signalwire_project: str,
        signalwire_token: str,
        signalwire_space: str,
        from_number: str,
        dialogflow_webhook: str,
        dry_run: bool = False
    ):
        self.dry_run = dry_run
        self.from_number = from_number
        self.dialogflow_webhook = dialogflow_webhook
        self.results: List[CallResult] = []
        self.call_count = 0
        self.success_count = 0
        self.error_count = 0
        
        if not dry_run:
            self.client = SignalWireClient(
                signalwire_project,
                signalwire_token,
                signalwire_space=signalwire_space
            )
        else:
            self.client = None
            logger.info("DRY RUN MODE - No calls will be made")
        
        # Initialize Firestore for logging
        self.db = None
        if firestore and not dry_run:
            try:
                self.db = firestore.Client(project=DEFAULT_PROJECT)
                logger.info("Firestore logging enabled")
            except Exception as e:
                logger.warning(f"Firestore not available: {e}")
    
    def load_leads(self, csv_path: str) -> List[Lead]:
        """Load leads from CSV file."""
        leads = []
        
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Validate phone number
                phone = row.get('phone', '').strip()
                if not phone.startswith('+'):
                    phone = '+1' + phone.replace('-', '').replace(' ', '')
                
                lead = Lead(
                    phone=phone,
                    name=row.get('name', 'Unknown').strip(),
                    account=row.get('account', row.get('account_name', 'Unknown')).strip(),
                    email=row.get('email', '').strip() or None,
                    state=row.get('state', '').strip() or None,
                    current_system=row.get('current_system', '').strip() or None,
                    use_case=row.get('use_case', 'cold_calling').strip(),
                    campaign=row.get('campaign', '').strip() or None
                )
                leads.append(lead)
        
        logger.info(f"Loaded {len(leads)} leads from {csv_path}")
        return leads
    
    def validate_leads(self, leads: List[Lead]) -> List[Lead]:
        """Validate leads and filter out invalid entries."""
        valid_leads = []
        
        for lead in leads:
            # Basic phone validation
            if not lead.phone or len(lead.phone) < 10:
                logger.warning(f"Invalid phone for {lead.name}: {lead.phone}")
                continue
            
            # Check Do Not Call list
            if self.db and self._check_dnc(lead.phone):
                logger.warning(f"Phone on DNC list: {lead.phone}")
                continue
            
            valid_leads.append(lead)
        
        logger.info(f"Validated {len(valid_leads)} of {len(leads)} leads")
        return valid_leads
    
    def _check_dnc(self, phone: str) -> bool:
        """Check if phone is on Do Not Call list."""
        if not self.db:
            return False
        
        try:
            doc = self.db.collection('do_not_call').document(phone).get()
            return doc.exists
        except Exception:
            return False
    
    def make_call(self, lead: Lead, flow: str = "cold-calling") -> CallResult:
        """Make a single call."""
        result = CallResult(
            lead=lead,
            success=False,
            timestamp=datetime.now()
        )
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would call {lead.name} at {lead.phone}")
            result.success = True
            result.status = "dry_run"
            result.call_sid = "dry_run_" + str(time.time())
            return result
        
        # Build session parameters for Dialogflow
        session_params = {
            "contact_name": lead.name,
            "account_name": lead.account,
            "account_type": self._infer_account_type(lead.account),
            "state": lead.state or "Arizona",
            "current_system": lead.current_system or "unknown",
            "email": lead.email or "",
            "use_case": lead.use_case,
            "campaign": lead.campaign or "batch_call"
        }
        
        # Build webhook URL with parameters
        webhook_url = f"{self.dialogflow_webhook}?flow={flow}"
        for key, value in session_params.items():
            webhook_url += f"&{key}={value}"
        
        for attempt in range(RETRY_ATTEMPTS):
            try:
                call = self.client.calls.create(
                    from_=self.from_number,
                    to=lead.phone,
                    url=webhook_url,
                    machine_detection='DetectMessageEnd',
                    machine_detection_timeout=5,
                    timeout=30,
                    status_callback=f"{self.dialogflow_webhook}/status",
                    status_callback_event=['initiated', 'ringing', 'answered', 'completed']
                )
                
                result.success = True
                result.call_sid = call.sid
                result.status = "initiated"
                
                logger.info(f"Call initiated: {lead.name} ({lead.phone}) - SID: {call.sid}")
                
                # Log to Firestore
                self._log_call_start(result, session_params)
                
                return result
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {lead.phone}: {e}")
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                else:
                    result.error = str(e)
                    result.status = "failed"
        
        return result
    
    def _infer_account_type(self, account_name: str) -> str:
        """Infer account type from name."""
        name_lower = account_name.lower()
        
        if 'school' in name_lower or 'district' in name_lower or 'isd' in name_lower:
            return 'K12'
        elif 'university' in name_lower or 'college' in name_lower:
            return 'Higher Ed'
        elif 'city' in name_lower or 'municipal' in name_lower:
            return 'City'
        elif 'county' in name_lower:
            return 'County'
        elif 'state' in name_lower:
            return 'State'
        else:
            return 'SLED'
    
    def _log_call_start(self, result: CallResult, params: Dict):
        """Log call start to Firestore."""
        if not self.db:
            return
        
        try:
            self.db.collection('batch_calls').document(result.call_sid).set({
                'session_id': result.call_sid,
                'lead': result.lead.to_dict(),
                'session_params': params,
                'status': 'initiated',
                'started_at': datetime.now(),
                'batch_run': datetime.now().strftime('%Y%m%d_%H%M%S')
            })
        except Exception as e:
            logger.warning(f"Failed to log call start: {e}")
    
    def run_batch(
        self,
        leads: List[Lead],
        flow: str = "cold-calling",
        max_concurrent: int = 5,
        calls_per_minute: int = CALLS_PER_MINUTE
    ) -> List[CallResult]:
        """Run batch calls with rate limiting and concurrency control."""
        
        logger.info(f"Starting batch: {len(leads)} calls, flow={flow}, "
                   f"concurrency={max_concurrent}, rate={calls_per_minute}/min")
        
        # Calculate delay between calls for rate limiting
        delay = 60.0 / calls_per_minute
        
        start_time = time.time()
        self.results = []
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {}
            
            for i, lead in enumerate(leads):
                # Rate limiting
                if i > 0:
                    time.sleep(delay)
                
                future = executor.submit(self.make_call, lead, flow)
                futures[future] = lead
                
                # Log progress
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{len(leads)} calls submitted")
            
            # Collect results
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                
                if result.success:
                    self.success_count += 1
                else:
                    self.error_count += 1
                
                self.call_count += 1
        
        elapsed = time.time() - start_time
        logger.info(f"Batch complete: {self.call_count} calls in {elapsed:.1f}s "
                   f"({self.success_count} success, {self.error_count} failed)")
        
        return self.results
    
    def save_results(self, output_path: str):
        """Save results to CSV file."""
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'phone', 'name', 'account', 'call_sid', 
                'status', 'success', 'error', 'timestamp'
            ])
            writer.writeheader()
            
            for result in self.results:
                writer.writerow({
                    'phone': result.lead.phone,
                    'name': result.lead.name,
                    'account': result.lead.account,
                    'call_sid': result.call_sid or '',
                    'status': result.status,
                    'success': result.success,
                    'error': result.error or '',
                    'timestamp': result.timestamp.isoformat() if result.timestamp else ''
                })
        
        logger.info(f"Results saved to {output_path}")
    
    def print_summary(self):
        """Print batch summary."""
        print("\n" + "=" * 50)
        print("BATCH CALL SUMMARY")
        print("=" * 50)
        print(f"Total Calls:     {self.call_count}")
        print(f"Successful:      {self.success_count}")
        print(f"Failed:          {self.error_count}")
        print(f"Success Rate:    {(self.success_count / max(1, self.call_count)) * 100:.1f}%")
        print("=" * 50 + "\n")


def get_config_from_secrets() -> Dict:
    """Load configuration from Secret Manager."""
    from google.cloud import secretmanager
    
    client = secretmanager.SecretManagerServiceClient()
    project = DEFAULT_PROJECT
    
    secrets = {}
    secret_names = [
        'signalwire-project-id',
        'signalwire-api-token', 
        'signalwire-space-url'
    ]
    
    for name in secret_names:
        try:
            path = f"projects/{project}/secrets/{name}/versions/latest"
            response = client.access_secret_version(request={"name": path})
            secrets[name] = response.payload.data.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to get secret {name}: {e}")
    
    return secrets


def main():
    parser = argparse.ArgumentParser(
        description="Batch call leads from CSV using AI Voice Caller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic batch call
    python batch-call.py leads.csv
    
    # Specific flow with rate limiting
    python batch-call.py leads.csv --flow follow-up --rate 20
    
    # Dry run to preview
    python batch-call.py leads.csv --dry-run
    
    # With custom output
    python batch-call.py leads.csv -o results.csv
        """
    )
    
    parser.add_argument('csv_file', help='Path to CSV file with leads')
    parser.add_argument('--flow', default='cold-calling',
                       choices=['cold-calling', 'follow-up', 'appointment-setting', 
                               'lead-qualification', 'information-delivery'],
                       help='Dialogflow flow to use')
    parser.add_argument('--max-concurrent', type=int, default=5,
                       help='Maximum concurrent calls (default: 5)')
    parser.add_argument('--rate', type=int, default=CALLS_PER_MINUTE,
                       help=f'Calls per minute rate limit (default: {CALLS_PER_MINUTE})')
    parser.add_argument('--from-number', 
                       help='Caller ID number (E.164 format)')
    parser.add_argument('--webhook-url',
                       help='Dialogflow webhook URL')
    parser.add_argument('-o', '--output', 
                       help='Output file for results (default: results_TIMESTAMP.csv)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview calls without making them')
    parser.add_argument('--use-secrets', action='store_true',
                       help='Load SignalWire credentials from Secret Manager')
    
    args = parser.parse_args()
    
    # Validate CSV file exists
    if not os.path.exists(args.csv_file):
        logger.error(f"CSV file not found: {args.csv_file}")
        sys.exit(1)
    
    # Get configuration
    if args.use_secrets:
        secrets = get_config_from_secrets()
        sw_project = secrets.get('signalwire-project-id', '')
        sw_token = secrets.get('signalwire-api-token', '')
        sw_space = secrets.get('signalwire-space-url', '')
    else:
        sw_project = os.environ.get('SIGNALWIRE_PROJECT_ID', '')
        sw_token = os.environ.get('SIGNALWIRE_API_TOKEN', '')
        sw_space = os.environ.get('SIGNALWIRE_SPACE_URL', '')
    
    from_number = args.from_number or os.environ.get('SIGNALWIRE_FROM_NUMBER', '+15551234567')
    webhook_url = args.webhook_url or os.environ.get('DIALOGFLOW_WEBHOOK_URL', 
                                                     'https://dialogflow.example.com/webhook')
    
    # Validate configuration
    if not args.dry_run:
        if not all([sw_project, sw_token, sw_space]):
            logger.error("Missing SignalWire credentials. Set environment variables or use --use-secrets")
            logger.error("Required: SIGNALWIRE_PROJECT_ID, SIGNALWIRE_API_TOKEN, SIGNALWIRE_SPACE_URL")
            sys.exit(1)
    
    # Initialize caller
    caller = BatchCaller(
        signalwire_project=sw_project,
        signalwire_token=sw_token,
        signalwire_space=sw_space,
        from_number=from_number,
        dialogflow_webhook=webhook_url,
        dry_run=args.dry_run
    )
    
    # Load and validate leads
    leads = caller.load_leads(args.csv_file)
    leads = caller.validate_leads(leads)
    
    if not leads:
        logger.error("No valid leads to call")
        sys.exit(1)
    
    # Confirm before proceeding
    if not args.dry_run:
        print(f"\nAbout to call {len(leads)} leads using flow: {args.flow}")
        print(f"Rate: {args.rate} calls/minute, Max concurrent: {args.max_concurrent}")
        response = input("Proceed? (y/N): ")
        if response.lower() != 'y':
            print("Aborted")
            sys.exit(0)
    
    # Run batch
    caller.run_batch(
        leads=leads,
        flow=args.flow,
        max_concurrent=args.max_concurrent,
        calls_per_minute=args.rate
    )
    
    # Save results
    output_file = args.output or f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    caller.save_results(output_file)
    
    # Print summary
    caller.print_summary()


if __name__ == '__main__':
    main()
