#!/usr/bin/env python3
"""
Real-Time Call Monitoring Dashboard

Monitors active AI voice calls and displays real-time metrics.
Shows call status, outcomes, and live transcripts.

Usage:
    python monitor-calls.py
    python monitor-calls.py --refresh 5  # Refresh every 5 seconds
    python monitor-calls.py --campaign feb-2024
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import curses
from collections import Counter

try:
    from google.cloud import firestore
except ImportError:
    print("Error: google-cloud-firestore not installed")
    print("Install with: pip install google-cloud-firestore")
    sys.exit(1)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'tatt-pro')
COLLECTION_NAME = 'calls'


class CallMonitor:
    """Real-time call monitoring dashboard."""
    
    def __init__(self, campaign: Optional[str] = None, hours: int = 24):
        self.db = firestore.Client(project=PROJECT_ID)
        self.campaign = campaign
        self.hours = hours
        self.calls = []
        self.active_calls = []
        self.metrics = {}
        
    def fetch_calls(self) -> List[Dict]:
        """Fetch recent calls from Firestore."""
        cutoff = datetime.now() - timedelta(hours=self.hours)
        
        query = self.db.collection(COLLECTION_NAME) \
            .where('startTime', '>=', cutoff) \
            .order_by('startTime', direction=firestore.Query.DESCENDING)
        
        if self.campaign:
            query = query.where('campaign', '==', self.campaign)
        
        docs = query.limit(500).stream()
        
        self.calls = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            self.calls.append(data)
        
        # Separate active calls
        self.active_calls = [c for c in self.calls if c.get('status') == 'in_progress']
        
        return self.calls
    
    def calculate_metrics(self) -> Dict:
        """Calculate call metrics."""
        if not self.calls:
            return {}
        
        outcomes = Counter(c.get('outcome', 'unknown') for c in self.calls)
        statuses = Counter(c.get('status', 'unknown') for c in self.calls)
        
        durations = [c.get('duration', 0) for c in self.calls if c.get('duration')]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        completed_calls = [c for c in self.calls if c.get('status') == 'completed']
        positive_outcomes = sum(1 for c in completed_calls 
                               if c.get('outcome') in ['interested', 'meeting_booked', 'send_info'])
        
        conversion_rate = (positive_outcomes / len(completed_calls) * 100) if completed_calls else 0
        
        self.metrics = {
            'total_calls': len(self.calls),
            'active_calls': len(self.active_calls),
            'completed_calls': len(completed_calls),
            'avg_duration': avg_duration,
            'conversion_rate': conversion_rate,
            'outcomes': dict(outcomes),
            'statuses': dict(statuses),
            'positive_outcomes': positive_outcomes
        }
        
        return self.metrics
    
    def get_recent_transcripts(self, limit: int = 5) -> List[Dict]:
        """Get most recent call transcripts."""
        completed = [c for c in self.calls if c.get('transcript')]
        return completed[:limit]
    
    def run_curses_dashboard(self, stdscr, refresh_interval: int = 10):
        """Run curses-based dashboard."""
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)
        
        stdscr.nodelay(True)
        
        while True:
            try:
                # Check for quit
                key = stdscr.getch()
                if key == ord('q') or key == ord('Q'):
                    break
                
                # Fetch data
                self.fetch_calls()
                self.calculate_metrics()
                
                # Clear and redraw
                stdscr.clear()
                height, width = stdscr.getmaxyx()
                
                # Header
                header = f" AI Voice Caller Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                stdscr.attron(curses.color_pair(5))
                stdscr.addstr(0, 0, header.center(width))
                stdscr.attroff(curses.color_pair(5))
                
                # Metrics section
                row = 2
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(row, 2, "METRICS")
                stdscr.attroff(curses.A_BOLD)
                row += 1
                
                # Draw metrics
                metrics_str = f"Total: {self.metrics.get('total_calls', 0)} | "
                metrics_str += f"Active: {self.metrics.get('active_calls', 0)} | "
                metrics_str += f"Completed: {self.metrics.get('completed_calls', 0)} | "
                metrics_str += f"Avg Duration: {self.metrics.get('avg_duration', 0):.0f}s | "
                metrics_str += f"Conversion: {self.metrics.get('conversion_rate', 0):.1f}%"
                stdscr.addstr(row, 2, metrics_str)
                row += 2
                
                # Outcomes section
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(row, 2, "OUTCOMES")
                stdscr.attroff(curses.A_BOLD)
                row += 1
                
                outcomes = self.metrics.get('outcomes', {})
                outcome_colors = {
                    'meeting_booked': 1,  # Green
                    'interested': 1,
                    'send_info': 2,  # Yellow
                    'callback_requested': 2,
                    'not_interested': 3,  # Red
                    'do_not_call': 3
                }
                
                for outcome, count in sorted(outcomes.items(), key=lambda x: -x[1]):
                    color = outcome_colors.get(outcome, 0)
                    if color:
                        stdscr.attron(curses.color_pair(color))
                    stdscr.addstr(row, 4, f"• {outcome}: {count}")
                    if color:
                        stdscr.attroff(curses.color_pair(color))
                    row += 1
                
                row += 1
                
                # Active calls section
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(row, 2, f"ACTIVE CALLS ({len(self.active_calls)})")
                stdscr.attroff(curses.A_BOLD)
                row += 1
                
                if self.active_calls:
                    for call in self.active_calls[:5]:
                        name = call.get('callerName', 'Unknown')
                        account = call.get('accountName', 'Unknown')
                        start_time = call.get('startTime')
                        if start_time:
                            duration = (datetime.now() - start_time.replace(tzinfo=None)).seconds
                        else:
                            duration = 0
                        
                        stdscr.attron(curses.color_pair(4))
                        stdscr.addstr(row, 4, f"• {name} ({account}) - {duration}s")
                        stdscr.attroff(curses.color_pair(4))
                        row += 1
                else:
                    stdscr.addstr(row, 4, "No active calls")
                    row += 1
                
                row += 1
                
                # Recent completed calls
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(row, 2, "RECENT CALLS")
                stdscr.attroff(curses.A_BOLD)
                row += 1
                
                recent = [c for c in self.calls if c.get('status') == 'completed'][:8]
                for call in recent:
                    name = call.get('callerName', 'Unknown')[:15]
                    outcome = call.get('outcome', 'unknown')
                    duration = call.get('duration', 0)
                    
                    color = outcome_colors.get(outcome, 0)
                    if color:
                        stdscr.attron(curses.color_pair(color))
                    stdscr.addstr(row, 4, f"• {name}: {outcome} ({duration}s)")
                    if color:
                        stdscr.attroff(curses.color_pair(color))
                    row += 1
                
                # Footer
                footer = " Press 'q' to quit | Refreshing every {}s ".format(refresh_interval)
                stdscr.addstr(height - 1, 0, footer.center(width)[:width-1])
                
                stdscr.refresh()
                time.sleep(refresh_interval)
                
            except KeyboardInterrupt:
                break
            except curses.error:
                pass
    
    def run_simple_dashboard(self, refresh_interval: int = 10):
        """Run simple text-based dashboard (no curses)."""
        print("\nAI Voice Caller Monitor")
        print("Press Ctrl+C to exit\n")
        
        try:
            while True:
                # Fetch data
                self.fetch_calls()
                self.calculate_metrics()
                
                # Clear screen
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # Print header
                print("=" * 60)
                print(f"AI Voice Caller Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 60)
                print()
                
                # Metrics
                print("METRICS")
                print(f"  Total Calls: {self.metrics.get('total_calls', 0)}")
                print(f"  Active: {self.metrics.get('active_calls', 0)}")
                print(f"  Completed: {self.metrics.get('completed_calls', 0)}")
                print(f"  Avg Duration: {self.metrics.get('avg_duration', 0):.0f}s")
                print(f"  Conversion Rate: {self.metrics.get('conversion_rate', 0):.1f}%")
                print()
                
                # Outcomes
                print("OUTCOMES")
                for outcome, count in sorted(self.metrics.get('outcomes', {}).items(), 
                                            key=lambda x: -x[1]):
                    print(f"  • {outcome}: {count}")
                print()
                
                # Active calls
                print(f"ACTIVE CALLS ({len(self.active_calls)})")
                if self.active_calls:
                    for call in self.active_calls[:5]:
                        name = call.get('callerName', 'Unknown')
                        account = call.get('accountName', 'Unknown')
                        print(f"  • {name} ({account})")
                else:
                    print("  No active calls")
                print()
                
                # Recent calls
                print("RECENT CALLS")
                recent = [c for c in self.calls if c.get('status') == 'completed'][:5]
                for call in recent:
                    name = call.get('callerName', 'Unknown')
                    outcome = call.get('outcome', 'unknown')
                    duration = call.get('duration', 0)
                    print(f"  • {name}: {outcome} ({duration}s)")
                
                print()
                print(f"Refreshing in {refresh_interval}s... (Ctrl+C to exit)")
                
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print("\nExiting...")


def main():
    parser = argparse.ArgumentParser(description="Monitor AI Voice Calls in real-time")
    parser.add_argument('--refresh', type=int, default=10,
                       help='Refresh interval in seconds (default: 10)')
    parser.add_argument('--campaign', help='Filter by campaign name')
    parser.add_argument('--hours', type=int, default=24,
                       help='Look back hours (default: 24)')
    parser.add_argument('--simple', action='store_true',
                       help='Use simple text mode (no curses)')
    
    args = parser.parse_args()
    
    monitor = CallMonitor(campaign=args.campaign, hours=args.hours)
    
    if args.simple:
        monitor.run_simple_dashboard(refresh_interval=args.refresh)
    else:
        try:
            curses.wrapper(lambda stdscr: monitor.run_curses_dashboard(
                stdscr, refresh_interval=args.refresh
            ))
        except Exception as e:
            print(f"Curses mode failed: {e}")
            print("Falling back to simple mode...")
            monitor.run_simple_dashboard(refresh_interval=args.refresh)


if __name__ == '__main__':
    main()
