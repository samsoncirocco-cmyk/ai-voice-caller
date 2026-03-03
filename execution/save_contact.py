#!/usr/bin/env python3
"""
Save IT contact to Firestore (deterministic execution)

Usage:
  python3 save_contact.py --call-sid abc123 --name "John Smith" --phone "+15551234567" --account "Test School"
  python3 save_contact.py --test  # Run test mode
"""
import sys
import argparse
from datetime import datetime
from google.cloud import firestore

def save_contact(call_sid, contact_name, contact_phone, account_name, timestamp=None, test_mode=False):
    """
    Save contact to Firestore with retry logic
    
    Returns: (success: bool, doc_id: str, error: str)
    """
    if test_mode:
        print(f"[TEST MODE] Would save:")
        print(f"  Call SID: {call_sid}")
        print(f"  Name: {contact_name}")
        print(f"  Phone: {contact_phone}")
        print(f"  Account: {account_name}")
        return (True, "test-doc-123", None)
    
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat()
    
    db = firestore.Client(project="tatt-pro")
    
    # Retry logic (3 attempts with exponential backoff)
    for attempt in range(3):
        try:
            doc_ref = db.collection('contacts').add({
                'call_sid': call_sid,
                'name': contact_name,
                'phone': contact_phone,
                'account': account_name,
                'source': 'discovery_call',
                'created_at': timestamp,
                'status': 'new'
            })
            
            doc_id = doc_ref[1].id
            print(f"✅ Contact saved: {doc_id}")
            return (True, doc_id, None)
            
        except Exception as e:
            if attempt < 2:  # Not the last attempt
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s
                print(f"⚠️  Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                import time
                time.sleep(wait_time)
            else:
                # Last attempt failed - write to emergency log
                error_msg = f"Failed after 3 attempts: {e}"
                print(f"❌ {error_msg}")
                
                # Emergency log
                with open('/home/samson/.openclaw/workspace/projects/ai-voice-caller/logs/emergency.log', 'a') as f:
                    f.write(f"{datetime.utcnow().isoformat()} | CONTACT_SAVE_FAILED | {call_sid} | {contact_name} | {contact_phone} | {account_name} | {e}\n")
                
                return (False, None, error_msg)

def main():
    parser = argparse.ArgumentParser(description='Save contact to Firestore')
    parser.add_argument('--call-sid', required=False, help='Call SID from SignalWire')
    parser.add_argument('--name', required=False, help='Contact name')
    parser.add_argument('--phone', required=False, help='Contact phone')
    parser.add_argument('--account', required=False, help='Account name')
    parser.add_argument('--timestamp', help='ISO 8601 timestamp (optional)')
    parser.add_argument('--test', action='store_true', help='Test mode (no actual write)')
    
    args = parser.parse_args()
    
    if args.test:
        # Run in test mode
        success, doc_id, error = save_contact(
            call_sid='test-123',
            contact_name='John Smith',
            contact_phone='+15551234567',
            account_name='Test School District',
            test_mode=True
        )
        sys.exit(0 if success else 1)
    
    # Validate required args
    if not all([args.call_sid, args.name, args.phone, args.account]):
        print("❌ Error: --call-sid, --name, --phone, and --account are required")
        sys.exit(1)
    
    success, doc_id, error = save_contact(
        call_sid=args.call_sid,
        contact_name=args.name,
        contact_phone=args.phone,
        account_name=args.account,
        timestamp=args.timestamp
    )
    
    if success:
        # Output for SWAIG function to parse
        print(f"CONTACT_SAVED:{doc_id}")
        sys.exit(0)
    else:
        print(f"CONTACT_FAILED:{error}")
        sys.exit(1)

if __name__ == "__main__":
    main()
