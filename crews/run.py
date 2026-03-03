#!/usr/bin/env python3
"""
Voice Campaign Crew - CLI Entry Point

Usage:
    # Dry run with sample accounts
    python run.py --dry-run
    
    # Dry run with account list file
    python run.py --accounts accounts.json --dry-run
    
    # Live campaign (actually places calls)
    python run.py --accounts accounts.json --live
    
    # Specify output directory
    python run.py --accounts accounts.json --output /path/to/output --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from crew import create_voice_campaign_crew


def load_sample_accounts():
    """Generate sample account data for testing"""
    return [
        {
            "account_name": "Phoenix Union High School District",
            "salesforce_id": "0011234567890ABC",
            "contact_name": "Maria Rodriguez",
            "title": "Director of Technology",
            "phone": "+16025551001",
            "email": "maria.rodriguez@puhsd.org",
            "pipeline_value": 75000,
            "days_since_contact": 21,
            "erate_deadline": "2026-03-15",
            "opportunity_stage": "Proposal",
            "industry": "K-12 Education"
        },
        {
            "account_name": "Maricopa County Community College District",
            "salesforce_id": "0011234567890DEF",
            "contact_name": "James Chen",
            "title": "Chief Information Security Officer",
            "phone": "+14805551002",
            "email": "james.chen@maricopa.edu",
            "pipeline_value": 120000,
            "days_since_contact": 45,
            "erate_deadline": None,
            "opportunity_stage": "Qualification",
            "industry": "Higher Education"
        },
        {
            "account_name": "Tucson Unified School District",
            "salesforce_id": "0011234567890GHI",
            "contact_name": "Sarah Williams",
            "title": "Network Administrator",
            "phone": "+15205551003",
            "email": "sarah.williams@tusd1.org",
            "pipeline_value": 45000,
            "days_since_contact": 8,
            "erate_deadline": "2026-02-28",
            "opportunity_stage": "Quote",
            "industry": "K-12 Education"
        },
        {
            "account_name": "Arizona State Library",
            "salesforce_id": "0011234567890JKL",
            "contact_name": "Robert Martinez",
            "title": "IT Manager",
            "phone": "+16025551004",
            "email": "robert.martinez@azlibrary.gov",
            "pipeline_value": 30000,
            "days_since_contact": 60,
            "erate_deadline": "2026-03-01",
            "opportunity_stage": "Prospecting",
            "industry": "Library"
        },
        {
            "account_name": "Northern Arizona University",
            "salesforce_id": "0011234567890MNO",
            "contact_name": "Emily Johnson",
            "title": "Director of Network Services",
            "phone": "+19285551005",
            "email": "emily.johnson@nau.edu",
            "pipeline_value": 200000,
            "days_since_contact": 15,
            "erate_deadline": None,
            "opportunity_stage": "Proposal",
            "industry": "Higher Education"
        }
    ]


def main():
    parser = argparse.ArgumentParser(
        description='Voice Campaign Crew - Automated calling with CrewAI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with sample accounts (dry run)
  %(prog)s --dry-run
  
  # Use your own account list
  %(prog)s --accounts my_accounts.json --dry-run
  
  # Run live campaign
  %(prog)s --accounts my_accounts.json --live
  
  # Save results to specific directory
  %(prog)s --accounts my_accounts.json --output ~/campaigns --dry-run

Account List Format (JSON):
  [
    {
      "account_name": "Example School",
      "salesforce_id": "0011234567890ABC",
      "contact_name": "Jane Doe",
      "phone": "+14805551234",
      "email": "jane@example.edu",
      "pipeline_value": 50000,
      "days_since_contact": 30,
      "erate_deadline": "2026-03-01",
      "opportunity_stage": "Proposal"
    }
  ]
        """
    )
    
    parser.add_argument(
        '--accounts',
        '-a',
        type=str,
        help='Path to JSON file with account list (uses sample data if not provided)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate calls without actually placing them (default)'
    )
    
    parser.add_argument(
        '--live',
        action='store_true',
        help='Place actual calls (use with caution!)'
    )
    
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        help='Output directory for campaign results'
    )
    
    parser.add_argument(
        '--save-sample',
        type=str,
        help='Save sample account data to specified JSON file and exit'
    )
    
    args = parser.parse_args()
    
    # Handle --save-sample
    if args.save_sample:
        sample_data = load_sample_accounts()
        with open(args.save_sample, 'w') as f:
            json.dump(sample_data, f, indent=2)
        print(f"✅ Sample account data saved to: {args.save_sample}")
        return 0
    
    # Determine dry_run mode
    dry_run = not args.live  # Default to dry-run unless --live is specified
    
    # Load account list
    if args.accounts:
        try:
            with open(args.accounts) as f:
                account_list = json.load(f)
            print(f"📋 Loaded {len(account_list)} accounts from {args.accounts}")
        except FileNotFoundError:
            print(f"❌ Error: Account file not found: {args.accounts}")
            return 1
        except json.JSONDecodeError as e:
            print(f"❌ Error: Invalid JSON in account file: {e}")
            return 1
    else:
        print("📋 Using sample account data (5 accounts)")
        account_list = load_sample_accounts()
    
    # Display mode warning
    if dry_run:
        print("\n🧪 DRY RUN MODE - No actual calls will be placed")
    else:
        print("\n⚠️  LIVE MODE - Real calls will be placed!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return 0
    
    # Create and run crew
    try:
        crew = create_voice_campaign_crew(
            account_list,
            dry_run=dry_run,
            output_dir=args.output
        )
        
        print(f"\n🚀 Starting Voice Campaign Crew...")
        print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        results = crew.run_campaign(save_results=True)
        
        print("\n" + "="*60)
        print("✅ Campaign Complete!")
        print("="*60)
        print(f"\nCampaign ID: {results['campaign_id']}")
        print(f"Accounts Processed: {results['summary']['total_accounts']}")
        print(f"Mode: {'Dry Run' if results['dry_run'] else 'Live'}")
        
        return 0
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Campaign interrupted by user")
        return 130
    
    except Exception as e:
        print(f"\n❌ Error running campaign: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
