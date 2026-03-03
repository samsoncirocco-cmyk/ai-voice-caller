#!/usr/bin/env python3
"""
Salesforce Sync - Push Firestore data to Salesforce CRM

Syncs:
  contacts   -> SF Contact + Task (matched to existing Account only)
  call_logs  -> SF Event (Type: Call)
  lead_scores -> SF Task (priority based on score)
# Sync: cold-call-leads -> SF Lead (only if company matches existing Account)
  callbacks  -> SF Task (follow-up)

Usage:
  python3 execution/sync_salesforce.py                         # full sync
  python3 execution/sync_salesforce.py --dry-run               # preview only
  python3 execution/sync_salesforce.py --since 2026-02-10      # date filter
  python3 execution/sync_salesforce.py --collection contacts   # single collection
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone

from google.cloud import firestore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('sf-sync')

PROJECT = 'tatt-pro'
COLLECTIONS = ['contacts', 'call_logs', 'lead_scores', 'cold-call-leads', 'callbacks']


# ---------------------------------------------------------------------------
# Salesforce auth
# ---------------------------------------------------------------------------
def get_secret(name):
    """Fetch secret from GCP Secret Manager, fallback to env var."""
    env_key = name.upper().replace('-', '_')
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        resp = client.access_secret_version(
            request={'name': f'projects/{PROJECT}/secrets/{name}/versions/latest'}
        )
        return resp.payload.data.decode('utf-8')
    except Exception as e:
        raise RuntimeError(f'Cannot fetch secret {name}: {e}. Set env var {env_key} as fallback.')


def get_sf_client():
    """Return an authenticated simple_salesforce.Salesforce client."""
    from simple_salesforce import Salesforce
    username = get_secret('sf-username')
    password = get_secret('sf-password')
    token = get_secret('sf-security-token')
    sf = Salesforce(username=username, password=password, security_token=token)
    log.info('Connected to Salesforce as %s', username)
    return sf


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------
def get_db():
    return firestore.Client(project=PROJECT)


def query_collection(db, name, since=None):
    """Read docs from a Firestore collection, optionally filtered by date."""
    ref = db.collection(name)
    if since:
        for field in ('created_at', 'timestamp', 'scored_at', 'created'):
            try:
                q = ref.where(field, '>=', since).stream()
                docs = list(q)
                if docs:
                    return docs
            except Exception:
                pass
        return list(ref.stream())
    return list(ref.stream())


def _esc(s):
    """Escape single quotes for SOQL."""
    if not s:
        return ''
    return str(s).replace("'", "\\'")


# ---------------------------------------------------------------------------
# Sync: contacts -> SF Account + Contact + Task
# ---------------------------------------------------------------------------
def sync_contacts(sf, db, docs, dry_run=False):
    stats = {'synced': 0, 'skipped': 0, 'errors': 0}
    for doc in docs:
        d = doc.to_dict()
        if d.get('status') == 'synced_to_sf':
            stats['skipped'] += 1
            continue

        account_name = d.get('account', 'Unknown')
        contact_name = d.get('name', 'Unknown')
        phone = d.get('phone', '')

        parts = contact_name.strip().split(' ', 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ''

        if dry_run:
            log.info('[DRY-RUN] Would sync contact %s (%s) -> Account: %s', contact_name, phone, account_name)
            stats['synced'] += 1
            continue

        try:
            # Search existing accounts (exact match, then fuzzy)
            soql = "SELECT Id, Name FROM Account WHERE Name = '{}' LIMIT 1".format(_esc(account_name))
            result = sf.query(soql)
            if result['totalSize'] == 0:
                # Try fuzzy match
                soql = "SELECT Id, Name FROM Account WHERE Name LIKE '%{}%' LIMIT 5".format(_esc(account_name))
                result = sf.query(soql)
            if result['totalSize'] > 0:
                acct_id = result['records'][0]['Id']
                matched_name = result['records'][0].get('Name', account_name)
                log.info('Matched Account: %s -> %s (%s)', account_name, matched_name, acct_id)
            else:
                log.info('SKIPPED: No matching SF Account for "%s" (contact: %s)', account_name, contact_name)
                stats['skipped'] += 1
                continue
                acct_id = acct['id']
                log.info('Created Account: %s (%s)', account_name, acct_id)

            soql = "SELECT Id FROM Contact WHERE AccountId = '{}' AND FirstName = '{}' AND LastName = '{}' LIMIT 1".format(
                acct_id, _esc(first), _esc(last)
            )
            result = sf.query(soql)
            if result['totalSize'] > 0:
                contact_id = result['records'][0]['Id']
                sf.Contact.update(contact_id, {'Phone': phone})
                log.info('Updated Contact: %s (%s)', contact_name, contact_id)
            else:
                con = sf.Contact.create({
                    'AccountId': acct_id,
                    'FirstName': first,
                    'LastName': last or '(Unknown)',
                    'Phone': phone,
                    'LeadSource': 'AI Outbound Call'
                })
                contact_id = con['id']
                log.info('Created Contact: %s (%s)', contact_name, contact_id)

            sf.Task.create({
                'WhoId': contact_id,
                'WhatId': acct_id,
                'Subject': 'AI Discovery Call - Contact Captured',
                'Status': 'Completed',
                'Priority': 'Normal',
                'Description': 'Contact captured via AI outbound call.\nCall SID: {}\nPhone: {}'.format(
                    d.get('call_sid', 'N/A'), phone
                ),
                'ActivityDate': datetime.utcnow().strftime('%Y-%m-%d')
            })

            db.collection('contacts').document(doc.id).update({
                'status': 'synced_to_sf',
                'sf_account_id': acct_id,
                'sf_contact_id': contact_id,
                'synced_at': datetime.utcnow().isoformat()
            })
            stats['synced'] += 1

        except Exception as e:
            log.error('Failed to sync contact %s: %s', doc.id, e)
            stats['errors'] += 1

    return stats


# ---------------------------------------------------------------------------
# Sync: call_logs -> SF Event (Type: Call)
# ---------------------------------------------------------------------------
def sync_call_logs(sf, db, docs, dry_run=False):
    stats = {'synced': 0, 'skipped': 0, 'errors': 0}
    for doc in docs:
        d = doc.to_dict()
        if d.get('synced_to_sf'):
            stats['skipped'] += 1
            continue

        call_sid = d.get('call_sid', doc.id)
        outcome = d.get('outcome', 'unknown')
        duration = d.get('duration', 0)
        to_number = d.get('to', '')
        status = d.get('status', '')

        if dry_run:
            log.info('[DRY-RUN] Would sync call_log %s: %s -> %s (%ss, %s)',
                     call_sid, d.get('from', ''), to_number, duration, outcome)
            stats['synced'] += 1
            continue

        try:
            acct_id = None
            if to_number:
                soql = "SELECT AccountId FROM Contact WHERE Phone = '{}' LIMIT 1".format(_esc(to_number))
                result = sf.query(soql)
                if result['totalSize'] > 0:
                    acct_id = result['records'][0]['AccountId']

            transcript = d.get('transcript', 'No transcript')
            if transcript and len(transcript) > 500:
                transcript = transcript[:500]

            event_data = {
                'Subject': 'AI Call - {}'.format(outcome),
                'Type': 'Call',
                'DurationInMinutes': max(1, (duration or 0) // 60),
                'Description': 'Call SID: {}\nOutcome: {}\nDuration: {}s\nStatus: {}\nSummary: {}'.format(
                    call_sid, outcome, duration, status, transcript
                ),
                'StartDateTime': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
                'EndDateTime': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if acct_id:
                event_data['WhatId'] = acct_id

            sf.Event.create(event_data)

            db.collection('call_logs').document(doc.id).update({
                'synced_to_sf': True,
                'synced_at': datetime.utcnow().isoformat()
            })
            stats['synced'] += 1

        except Exception as e:
            log.error('Failed to sync call_log %s: %s', doc.id, e)
            stats['errors'] += 1

    return stats


# ---------------------------------------------------------------------------
# Sync: lead_scores -> SF Task (priority by score)
# ---------------------------------------------------------------------------
def sync_lead_scores(sf, db, docs, dry_run=False):
    stats = {'synced': 0, 'skipped': 0, 'errors': 0}
    for doc in docs:
        d = doc.to_dict()
        if d.get('synced_to_sf'):
            stats['skipped'] += 1
            continue

        score = d.get('score', 0)
        phone = d.get('phone', '')
        name = d.get('name', d.get('contact_name', 'Unknown'))

        if score < 40:
            log.info('Lead %s score=%d (cold) - skipping SF task', name, score)
            stats['skipped'] += 1
            continue

        if score >= 70:
            priority = 'High'
            subject = 'Schedule demo - {} (score: {})'.format(name, score)
        else:
            priority = 'Normal'
            subject = 'Send info - {} (score: {})'.format(name, score)

        if dry_run:
            log.info('[DRY-RUN] Would create %s-priority task: %s', priority, subject)
            stats['synced'] += 1
            continue

        try:
            who_id = None
            what_id = None
            if phone:
                soql = "SELECT Id, AccountId FROM Contact WHERE Phone = '{}' LIMIT 1".format(_esc(phone))
                result = sf.query(soql)
                if result['totalSize'] > 0:
                    who_id = result['records'][0]['Id']
                    what_id = result['records'][0]['AccountId']

            task_data = {
                'Subject': subject,
                'Priority': priority,
                'Status': 'Not Started',
                'Description': 'AI Lead Score: {}\nPhone: {}\nScoring factors: {}'.format(
                    score, phone, json.dumps(d.get('factors', {}), indent=2)
                ),
                'ActivityDate': datetime.utcnow().strftime('%Y-%m-%d')
            }
            if who_id:
                task_data['WhoId'] = who_id
            if what_id:
                task_data['WhatId'] = what_id

            sf.Task.create(task_data)

            db.collection('lead_scores').document(doc.id).update({
                'synced_to_sf': True,
                'synced_at': datetime.utcnow().isoformat()
            })
            stats['synced'] += 1

        except Exception as e:
            log.error('Failed to sync lead_score %s: %s', doc.id, e)
            stats['errors'] += 1

    return stats


# ---------------------------------------------------------------------------
# Sync: cold-call-leads -> SF Lead (only if company matches existing Account)
# ---------------------------------------------------------------------------
def sync_cold_call_leads(sf, db, docs, dry_run=False):
    stats = {'synced': 0, 'skipped': 0, 'errors': 0}
    for doc in docs:
        d = doc.to_dict()
        if d.get('synced_to_sf'):
            stats['skipped'] += 1
            continue

        name = d.get('name', d.get('contact_name', 'Unknown'))
        company = d.get('company', d.get('account', d.get('organization', 'Unknown')))
        phone = d.get('phone', '')
        email = d.get('email', '')

        parts = name.strip().split(' ', 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else '(Unknown)'

        if dry_run:
            log.info('[DRY-RUN] Would create SF Lead: %s at %s', name, company)
            stats['synced'] += 1
            continue

        try:
            # Only create Lead if company matches an existing Account
            if company and company != 'Unknown':
                soql = "SELECT Id FROM Account WHERE Name LIKE '%{}%' LIMIT 1".format(_esc(company))
                acct_result = sf.query(soql)
                if acct_result['totalSize'] == 0:
                    log.info('SKIPPED: No matching SF Account for lead "%s" at "%s"', name, company)
                    stats['skipped'] += 1
                    continue
            else:
                log.info('SKIPPED: No company for lead "%s"', name)
                stats['skipped'] += 1
                continue

            lead = sf.Lead.create({
                'FirstName': first,
                'LastName': last,
                'Company': company,
                'Phone': phone,
                'Email': email,
                'LeadSource': 'AI Cold Call',
                'Status': 'New',
                'Description': 'Imported from AI voice caller cold-call-leads.\nFirestore doc: {}'.format(doc.id)
            })

            db.collection('cold-call-leads').document(doc.id).update({
                'synced_to_sf': True,
                'sf_lead_id': lead['id'],
                'synced_at': datetime.utcnow().isoformat()
            })
            stats['synced'] += 1

        except Exception as e:
            log.error('Failed to sync cold-call-lead %s: %s', doc.id, e)
            stats['errors'] += 1

    return stats


# ---------------------------------------------------------------------------
# Sync: callbacks -> SF Task (follow-up)
# ---------------------------------------------------------------------------
def sync_callbacks(sf, db, docs, dry_run=False):
    stats = {'synced': 0, 'skipped': 0, 'errors': 0}
    for doc in docs:
        d = doc.to_dict()
        if d.get('synced_to_sf'):
            stats['skipped'] += 1
            continue

        phone = d.get('phone', '')
        name = d.get('name', d.get('contact_name', 'Unknown'))
        reason = d.get('reason', d.get('notes', 'Follow-up call requested'))
        callback_time = d.get('callback_time', d.get('scheduled_at', ''))

        if dry_run:
            log.info('[DRY-RUN] Would create SF follow-up task: %s (%s)', name, reason)
            stats['synced'] += 1
            continue

        try:
            who_id = None
            what_id = None
            if phone:
                soql = "SELECT Id, AccountId FROM Contact WHERE Phone = '{}' LIMIT 1".format(_esc(phone))
                result = sf.query(soql)
                if result['totalSize'] > 0:
                    who_id = result['records'][0]['Id']
                    what_id = result['records'][0]['AccountId']

            activity_date = datetime.utcnow().strftime('%Y-%m-%d')
            if callback_time:
                try:
                    if isinstance(callback_time, str):
                        activity_date = callback_time[:10]
                    else:
                        activity_date = callback_time.strftime('%Y-%m-%d')
                except Exception:
                    pass

            task_data = {
                'Subject': 'Callback - {}'.format(name),
                'Priority': 'High',
                'Status': 'Not Started',
                'Description': 'Callback requested during AI call.\nReason: {}\nPhone: {}'.format(reason, phone),
                'ActivityDate': activity_date
            }
            if who_id:
                task_data['WhoId'] = who_id
            if what_id:
                task_data['WhatId'] = what_id

            sf.Task.create(task_data)

            db.collection('callbacks').document(doc.id).update({
                'synced_to_sf': True,
                'synced_at': datetime.utcnow().isoformat()
            })
            stats['synced'] += 1

        except Exception as e:
            log.error('Failed to sync callback %s: %s', doc.id, e)
            stats['errors'] += 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
SYNC_MAP = {
    'contacts': sync_contacts,
    'call_logs': sync_call_logs,
    'lead_scores': sync_lead_scores,
    'cold-call-leads': sync_cold_call_leads,
    'callbacks': sync_callbacks,
}


def main():
    parser = argparse.ArgumentParser(description='Sync Firestore data to Salesforce')
    parser.add_argument('--dry-run', action='store_true', help='Preview what would sync (no SF writes)')
    parser.add_argument('--since', help='Only sync docs created after this date (YYYY-MM-DD)')
    parser.add_argument('--collection', choices=COLLECTIONS, help='Sync a single collection')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info('=== Salesforce Sync Started ===')
    log.info('Mode: %s', 'DRY-RUN' if args.dry_run else 'LIVE')

    since = None
    if args.since:
        since = args.since
        log.info('Filtering docs since: %s', since)

    db = get_db()
    log.info('Connected to Firestore (project: %s)', PROJECT)

    sf = None
    if not args.dry_run:
        try:
            sf = get_sf_client()
        except Exception as e:
            log.error('Failed to connect to Salesforce: %s', e)
            log.error('Run with --dry-run to test Firestore reads without SF credentials.')
            sys.exit(1)

    targets = [args.collection] if args.collection else COLLECTIONS

    total_stats = {'synced': 0, 'skipped': 0, 'errors': 0}

    for coll_name in targets:
        log.info('--- Syncing: %s ---', coll_name)
        docs = query_collection(db, coll_name, since=since)
        log.info('Found %d docs in %s', len(docs), coll_name)

        if not docs:
            continue

        sync_fn = SYNC_MAP[coll_name]
        stats = sync_fn(sf, db, docs, dry_run=args.dry_run)

        for k in total_stats:
            total_stats[k] += stats[k]

        log.info('%s: synced=%d, skipped=%d, errors=%d',
                 coll_name, stats['synced'], stats['skipped'], stats['errors'])

    log.info('=== Sync Complete ===')
    log.info('Total: synced=%d, skipped=%d, errors=%d',
             total_stats['synced'], total_stats['skipped'], total_stats['errors'])

    if total_stats['errors'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
