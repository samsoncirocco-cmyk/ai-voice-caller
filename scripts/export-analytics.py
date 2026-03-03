#!/usr/bin/env python3
"""
Export Call Analytics

Export call data from Firestore to CSV or BigQuery for analysis.
Generates summary reports and detailed call logs.

Usage:
    python export-analytics.py --format csv --output calls.csv
    python export-analytics.py --format bigquery
    python export-analytics.py --summary --days 30
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import Counter

try:
    from google.cloud import firestore
    from google.cloud import bigquery
except ImportError:
    print("Error: google-cloud packages not installed")
    print("Install with: pip install google-cloud-firestore google-cloud-bigquery")
    sys.exit(1)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'tatt-pro')
COLLECTION_NAME = 'calls'
BIGQUERY_DATASET = 'voice_caller'
BIGQUERY_TABLE = 'call_logs'


class AnalyticsExporter:
    """Export and analyze call data."""
    
    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.db = firestore.Client(project=project_id)
        self.bq = bigquery.Client(project=project_id)
        
    def fetch_calls(
        self, 
        days: int = 30,
        campaign: Optional[str] = None,
        outcome: Optional[str] = None
    ) -> List[Dict]:
        """Fetch calls from Firestore."""
        cutoff = datetime.now() - timedelta(days=days)
        
        query = self.db.collection(COLLECTION_NAME) \
            .where('startTime', '>=', cutoff)
        
        if campaign:
            query = query.where('campaign', '==', campaign)
        
        if outcome:
            query = query.where('outcome', '==', outcome)
        
        docs = query.stream()
        
        calls = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            # Convert Firestore timestamps
            if 'startTime' in data and data['startTime']:
                data['startTime'] = data['startTime'].isoformat() if hasattr(data['startTime'], 'isoformat') else str(data['startTime'])
            if 'endTime' in data and data['endTime']:
                data['endTime'] = data['endTime'].isoformat() if hasattr(data['endTime'], 'isoformat') else str(data['endTime'])
            calls.append(data)
        
        print(f"Fetched {len(calls)} calls from last {days} days")
        return calls
    
    def export_to_csv(self, calls: List[Dict], output_path: str):
        """Export calls to CSV file."""
        if not calls:
            print("No calls to export")
            return
        
        # Flatten the data
        flattened = []
        for call in calls:
            flat = {
                'session_id': call.get('sessionId', call.get('id', '')),
                'start_time': call.get('startTime', ''),
                'end_time': call.get('endTime', ''),
                'duration_seconds': call.get('duration', 0),
                'caller_phone': call.get('callerPhone', ''),
                'caller_name': call.get('callerName', ''),
                'account_name': call.get('accountName', ''),
                'account_id': call.get('accountId', ''),
                'use_case': call.get('useCase', ''),
                'campaign': call.get('campaign', ''),
                'outcome': call.get('outcome', ''),
                'lead_score': call.get('leadScore', 0),
                'status': call.get('status', ''),
                'meeting_booked': call.get('meetingBooked', False),
                'email_sent': call.get('emailSent', False),
                'total_turns': call.get('metrics', {}).get('totalTurns', 0),
                'user_turns': call.get('metrics', {}).get('userTurns', 0),
                'bot_turns': call.get('metrics', {}).get('botTurns', 0),
            }
            
            # Add transcript as JSON string
            if 'transcript' in call:
                flat['transcript'] = json.dumps(call['transcript'])
            
            flattened.append(flat)
        
        # Write CSV
        fieldnames = list(flattened[0].keys()) if flattened else []
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flattened)
        
        print(f"Exported {len(flattened)} calls to {output_path}")
    
    def export_to_bigquery(self, calls: List[Dict]):
        """Stream calls to BigQuery."""
        if not calls:
            print("No calls to export")
            return
        
        table_ref = f"{self.project_id}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}"
        
        # Prepare rows
        rows = []
        for call in calls:
            row = {
                'session_id': call.get('sessionId', call.get('id', '')),
                'start_time': call.get('startTime'),
                'end_time': call.get('endTime'),
                'duration_seconds': call.get('duration', 0),
                'caller_phone': call.get('callerPhone', ''),
                'caller_name': call.get('callerName', ''),
                'account_name': call.get('accountName', ''),
                'account_id': call.get('accountId', ''),
                'use_case': call.get('useCase', ''),
                'campaign': call.get('campaign', ''),
                'outcome': call.get('outcome', ''),
                'lead_score': call.get('leadScore', 0),
                'total_turns': call.get('metrics', {}).get('totalTurns', 0),
                'user_turns': call.get('metrics', {}).get('userTurns', 0),
                'bot_turns': call.get('metrics', {}).get('botTurns', 0),
                'meeting_booked': call.get('meetingBooked', False),
                'email_sent': call.get('emailSent', False),
                'region': call.get('metadata', {}).get('region', ''),
                'inserted_at': datetime.now().isoformat()
            }
            rows.append(row)
        
        # Insert rows
        errors = self.bq.insert_rows_json(table_ref, rows)
        
        if errors:
            print(f"BigQuery insert errors: {errors}")
        else:
            print(f"Inserted {len(rows)} rows to BigQuery: {table_ref}")
    
    def generate_summary(self, calls: List[Dict]) -> Dict:
        """Generate summary statistics."""
        if not calls:
            return {}
        
        # Basic counts
        total = len(calls)
        completed = [c for c in calls if c.get('status') == 'completed']
        
        # Outcome breakdown
        outcomes = Counter(c.get('outcome', 'unknown') for c in calls)
        
        # Duration stats
        durations = [c.get('duration', 0) for c in calls if c.get('duration')]
        avg_duration = sum(durations) / len(durations) if durations else 0
        max_duration = max(durations) if durations else 0
        min_duration = min(durations) if durations else 0
        
        # Lead scores
        scores = [c.get('leadScore', 0) for c in calls if c.get('leadScore')]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Conversion metrics
        meetings_booked = sum(1 for c in calls if c.get('meetingBooked'))
        emails_sent = sum(1 for c in calls if c.get('emailSent'))
        positive_outcomes = sum(1 for c in completed 
                               if c.get('outcome') in ['interested', 'meeting_booked', 'send_info'])
        
        conversion_rate = (positive_outcomes / len(completed) * 100) if completed else 0
        
        # Campaign breakdown
        campaigns = Counter(c.get('campaign', 'none') for c in calls)
        
        # Use case breakdown
        use_cases = Counter(c.get('useCase', 'unknown') for c in calls)
        
        # By day
        daily = Counter()
        for call in calls:
            start = call.get('startTime', '')
            if isinstance(start, str) and start:
                try:
                    day = start[:10]
                    daily[day] += 1
                except:
                    pass
        
        summary = {
            'total_calls': total,
            'completed_calls': len(completed),
            'completion_rate': len(completed) / total * 100 if total else 0,
            'outcomes': dict(outcomes),
            'avg_duration_seconds': round(avg_duration, 1),
            'min_duration_seconds': min_duration,
            'max_duration_seconds': max_duration,
            'avg_lead_score': round(avg_score, 1),
            'meetings_booked': meetings_booked,
            'emails_sent': emails_sent,
            'conversion_rate': round(conversion_rate, 1),
            'positive_outcomes': positive_outcomes,
            'campaigns': dict(campaigns),
            'use_cases': dict(use_cases),
            'calls_by_day': dict(sorted(daily.items()))
        }
        
        return summary
    
    def print_summary(self, summary: Dict):
        """Print formatted summary report."""
        print("\n" + "=" * 60)
        print("CALL ANALYTICS SUMMARY")
        print("=" * 60)
        
        print(f"\nOVERALL METRICS")
        print(f"  Total Calls:       {summary.get('total_calls', 0)}")
        print(f"  Completed:         {summary.get('completed_calls', 0)}")
        print(f"  Completion Rate:   {summary.get('completion_rate', 0):.1f}%")
        print(f"  Conversion Rate:   {summary.get('conversion_rate', 0):.1f}%")
        
        print(f"\nDURATION")
        print(f"  Average:           {summary.get('avg_duration_seconds', 0):.0f}s")
        print(f"  Minimum:           {summary.get('min_duration_seconds', 0)}s")
        print(f"  Maximum:           {summary.get('max_duration_seconds', 0)}s")
        
        print(f"\nLEAD SCORING")
        print(f"  Average Score:     {summary.get('avg_lead_score', 0):.1f}/10")
        
        print(f"\nCONVERSIONS")
        print(f"  Meetings Booked:   {summary.get('meetings_booked', 0)}")
        print(f"  Emails Sent:       {summary.get('emails_sent', 0)}")
        print(f"  Positive Outcomes: {summary.get('positive_outcomes', 0)}")
        
        print(f"\nOUTCOME BREAKDOWN")
        for outcome, count in sorted(summary.get('outcomes', {}).items(), 
                                     key=lambda x: -x[1]):
            pct = count / summary.get('total_calls', 1) * 100
            print(f"  {outcome:20} {count:5} ({pct:.1f}%)")
        
        print(f"\nUSE CASE BREAKDOWN")
        for use_case, count in sorted(summary.get('use_cases', {}).items(), 
                                      key=lambda x: -x[1]):
            print(f"  {use_case:20} {count}")
        
        if summary.get('campaigns'):
            print(f"\nCAMPAIGN BREAKDOWN")
            for campaign, count in sorted(summary.get('campaigns', {}).items(), 
                                          key=lambda x: -x[1])[:10]:
                print(f"  {campaign:20} {count}")
        
        print(f"\nCALLS BY DAY")
        for day, count in list(summary.get('calls_by_day', {}).items())[-7:]:
            print(f"  {day}  {'█' * min(count, 50)} {count}")
        
        print("\n" + "=" * 60)
    
    def save_summary(self, summary: Dict, output_path: str):
        """Save summary to JSON file."""
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"Summary saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Export and analyze call data")
    parser.add_argument('--format', choices=['csv', 'bigquery', 'json'],
                       default='csv', help='Export format')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--days', type=int, default=30,
                       help='Days of data to export (default: 30)')
    parser.add_argument('--campaign', help='Filter by campaign')
    parser.add_argument('--outcome', help='Filter by outcome')
    parser.add_argument('--summary', action='store_true',
                       help='Generate and print summary report')
    parser.add_argument('--project', default=PROJECT_ID,
                       help='GCP project ID')
    
    args = parser.parse_args()
    
    exporter = AnalyticsExporter(project_id=args.project)
    
    # Fetch calls
    calls = exporter.fetch_calls(
        days=args.days,
        campaign=args.campaign,
        outcome=args.outcome
    )
    
    if not calls:
        print("No calls found matching criteria")
        sys.exit(0)
    
    # Generate summary
    if args.summary:
        summary = exporter.generate_summary(calls)
        exporter.print_summary(summary)
        
        if args.output and args.format == 'json':
            exporter.save_summary(summary, args.output)
    
    # Export data
    if args.format == 'csv':
        output = args.output or f"calls_export_{datetime.now().strftime('%Y%m%d')}.csv"
        exporter.export_to_csv(calls, output)
    
    elif args.format == 'bigquery':
        exporter.export_to_bigquery(calls)
    
    elif args.format == 'json':
        output = args.output or f"calls_export_{datetime.now().strftime('%Y%m%d')}.json"
        with open(output, 'w') as f:
            json.dump(calls, f, indent=2, default=str)
        print(f"Exported {len(calls)} calls to {output}")


if __name__ == '__main__':
    main()
