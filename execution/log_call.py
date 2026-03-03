#!/usr/bin/env python3
"""
Log call to Firestore (deterministic execution)

Usage:
  python3 log_call.py --call-sid abc123 --from "+16028985026" --to "+15551234567" --status completed --duration 45 --outcome contact_captured --cost 0.008
  python3 log_call.py --test  # Run test mode
"""
import sys
import argparse
from datetime import datetime
from google.cloud import firestore

VALID_STATUSES = ['initiated', 'answered', 'completed', 'failed']
VALID_OUTCOMES = ['contact_captured', 'refused', 'voicemail', 'no_answer', 'error']

def log_call(call_sid, from_number, to_number, status, duration, outcome, transcript=None, cost=0.0, test_mode=False):
    """
    Log call to Firestore with aggressive retry (this is critical)
    
    Returns: (success: bool, doc_path: str, error: str)
    """
    if test_mode:
        print(f"[TEST MODE] Would log:")
        print(f"  Call SID: {call_sid}")
        print(f"  From: {from_number}")
        print(f"  To: {to_number}")
        print(f"  Status: {status}")
        print(f"  Duration: {duration}s")
        print(f"  Outcome: {outcome}")
        print(f"  Cost: ${cost}")
        return (True, f"call_logs/{call_sid}", None)
    
    # Validate inputs
    if status not in VALID_STATUSES:
        return (False, None, f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    
    if outcome not in VALID_OUTCOMES:
        return (False, None, f"Invalid outcome: {outcome}. Must be one of {VALID_OUTCOMES}")
    
    db = firestore.Client(project="tatt-pro")
    
    # Retry logic (5 attempts - this is critical)
    for attempt in range(5):
        try:
            doc_ref = db.collection('call_logs').document(call_sid)
            doc_ref.set({
                'call_sid': call_sid,
                'from': from_number,
                'to': to_number,
                'status': status,
                'duration': duration,
                'outcome': outcome,
                'transcript': transcript,
                'cost': cost,
                'timestamp': firestore.SERVER_TIMESTAMP
            })
            
            doc_path = f"call_logs/{call_sid}"
            print(f"✅ Call logged: {doc_path}")
            return (True, doc_path, None)
            
        except Exception as e:
            if attempt < 4:  # Not the last attempt
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s, 8s
                print(f"⚠️  Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                import time
                time.sleep(wait_time)
            else:
                # CRITICAL FAILURE - this should never happen
                error_msg = f"CRITICAL: Call logging failed after 5 attempts: {e}"
                print(f"🚨 {error_msg}")
                
                # Emergency log (local file)
                emergency_log = '/home/samson/.openclaw/workspace/projects/ai-voice-caller/logs/emergency.log'
                with open(emergency_log, 'a') as f:
                    f.write(f"{datetime.utcnow().isoformat()} | CALL_LOG_FAILED | {call_sid} | {from_number} | {to_number} | {status} | {duration} | {outcome} | {cost} | {e}\n")
                
                # Alert operations (TODO: implement alerting)
                print(f"🚨 ALERT: Call log failure written to {emergency_log}")
                
                return (False, None, error_msg)

def main():
    parser = argparse.ArgumentParser(description='Log call to Firestore')
    parser.add_argument('--call-sid', required=False, help='Call SID from SignalWire')
    parser.add_argument('--from', dest='from_number', required=False, help='From phone number')
    parser.add_argument('--to', dest='to_number', required=False, help='To phone number')
    parser.add_argument('--status', required=False, choices=VALID_STATUSES, help='Call status')
    parser.add_argument('--duration', type=int, required=False, help='Call duration in seconds')
    parser.add_argument('--outcome', required=False, choices=VALID_OUTCOMES, help='Call outcome')
    parser.add_argument('--transcript', help='Call transcript (optional)')
    parser.add_argument('--cost', type=float, default=0.0, help='Call cost in USD')
    parser.add_argument('--test', action='store_true', help='Test mode (no actual write)')
    
    args = parser.parse_args()
    
    if args.test:
        # Run in test mode
        success, doc_path, error = log_call(
            call_sid='test-123',
            from_number='+16028985026',
            to_number='+15551234567',
            status='completed',
            duration=45,
            outcome='contact_captured',
            cost=0.008,
            test_mode=True
        )
        sys.exit(0 if success else 1)
    
    # Validate required args
    required_args = ['call_sid', 'from_number', 'to_number', 'status', 'duration', 'outcome']
    missing = [arg for arg in required_args if not getattr(args, arg)]
    if missing:
        print(f"❌ Error: Missing required arguments: {', '.join(missing)}")
        sys.exit(1)
    
    success, doc_path, error = log_call(
        call_sid=args.call_sid,
        from_number=args.from_number,
        to_number=args.to_number,
        status=args.status,
        duration=args.duration,
        outcome=args.outcome,
        transcript=args.transcript,
        cost=args.cost
    )
    
    if success:
        # Output for SWAIG function to parse
        print(f"CALL_LOGGED:{doc_path}")
        sys.exit(0)
    else:
        print(f"CALL_LOG_FAILED:{error}")
        sys.exit(1)

if __name__ == "__main__":
    main()
