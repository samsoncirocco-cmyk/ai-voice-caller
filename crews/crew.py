"""
Voice Campaign Crew - Main Orchestration
Uses CrewAI to coordinate lead scoring, calling, follow-up, and CRM logging
"""
from crewai import Crew, Process
from agents import (
    create_lead_scorer_agent,
    create_caller_agent,
    create_followup_agent,
    create_crm_agent
)
from tasks import (
    create_lead_scoring_task,
    create_calling_task,
    create_followup_task,
    create_crm_logging_task
)
from tools_wrapper import (
    get_lead_scorer_tools,
    get_caller_tools,
    get_followup_tools,
    get_crm_tools
)
import json
from datetime import datetime
from pathlib import Path


class VoiceCampaignCrew:
    """Main crew orchestration for voice calling campaigns"""
    
    def __init__(self, account_list, dry_run=True, output_dir=None):
        """
        Initialize Voice Campaign Crew
        
        Args:
            account_list: List of account dictionaries or JSON file path
            dry_run: If True, simulate calls without actually placing them
            output_dir: Directory to save campaign results (default: workspace/output)
        """
        self.dry_run = dry_run
        self.account_list = self._load_account_list(account_list)
        self.output_dir = output_dir or Path.home() / '.openclaw' / 'workspace' / 'output' / 'voice-campaigns'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.campaign_id = f"voice_campaign_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.salesforce_data = None
        
    def _load_account_list(self, account_list):
        """Load account list from file or use provided list"""
        if isinstance(account_list, str):
            # It's a file path
            with open(account_list) as f:
                return json.load(f)
        return account_list
    
    def _fetch_salesforce_data(self):
        """Fetch Salesforce data for all accounts in the list"""
        import sys
        from pathlib import Path
        
        # Add salesforce-intel to path
        workspace_root = Path(__file__).resolve().parent.parent.parent.parent
        sys.path.insert(0, str(workspace_root / 'tools' / 'salesforce-intel'))
        
        account_ids = [acc.get('salesforce_id') for acc in self.account_list if acc.get('salesforce_id')]
        
        if not account_ids:
            return "No Salesforce IDs provided"
        
        try:
            from typed_query import TypedSalesforceQuery
            query = TypedSalesforceQuery()
            results = []
            
            for account_id in account_ids:
                account_data = query.get_account_intelligence(account_id)
                results.append(account_data)
            
            return json.dumps(results, indent=2)
        except ImportError:
            return "Salesforce tools not available - using account list data only"
        except Exception as e:
            return f"Error fetching Salesforce data: {str(e)}"
    
    def create_crew(self):
        """Create and configure the crew"""
        # Fetch Salesforce context
        self.salesforce_data = self._fetch_salesforce_data()
        
        # Create agents with their tools
        lead_scorer = create_lead_scorer_agent(get_lead_scorer_tools())
        caller = create_caller_agent(get_caller_tools())
        followup = create_followup_agent(get_followup_tools())
        crm_agent = create_crm_agent(get_crm_tools())
        
        # Create tasks (these will be populated by crew execution)
        scoring_task = create_lead_scoring_task(
            lead_scorer,
            json.dumps(self.account_list, indent=2),
            self.salesforce_data
        )
        
        # Calling task will receive scored leads from previous task
        calling_task = create_calling_task(
            caller,
            "{{context from scoring_task}}",  # Will be populated by CrewAI
            dry_run=self.dry_run
        )
        
        # Follow-up task receives call log
        followup_task = create_followup_task(
            followup,
            "{{context from calling_task}}"
        )
        
        # CRM logging receives everything
        crm_task = create_crm_logging_task(
            crm_agent,
            "{{context from calling_task}}",
            "{{context from followup_task}}"
        )
        
        # Create crew with sequential process
        crew = Crew(
            agents=[lead_scorer, caller, followup, crm_agent],
            tasks=[scoring_task, calling_task, followup_task, crm_task],
            process=Process.sequential,
            verbose=True
        )
        
        return crew
    
    def run(self):
        """Execute the crew and return results"""
        crew = self.create_crew()
        
        print(f"\n{'='*60}")
        print(f"🎯 Voice Campaign Crew - {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Campaign ID: {self.campaign_id}")
        print(f"Accounts: {len(self.account_list)}")
        print(f"{'='*60}\n")
        
        result = crew.kickoff()
        
        return result
    
    def run_campaign(self, save_results=True):
        """
        Run the complete voice campaign workflow
        
        Args:
            save_results: If True, save outputs to files
        
        Returns:
            Dictionary with campaign results
        """
        result = self.run()
        
        # Format and save results
        campaign_output = self._format_campaign_output(result)
        
        if save_results:
            self._save_campaign_results(campaign_output)
        
        return campaign_output
    
    def _format_campaign_output(self, crew_result):
        """Format crew output as structured campaign results"""
        
        output = {
            "campaign_id": self.campaign_id,
            "timestamp": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "accounts_processed": len(self.account_list),
            "crew_output": str(crew_result),
            "summary": {
                "total_accounts": len(self.account_list),
                "calls_attempted": 0,  # Will be populated from call log
                "emails_drafted": 0,   # Will be populated from follow-up task
                "crm_updates": 0       # Will be populated from CRM task
            }
        }
        
        return output
    
    def _save_campaign_results(self, output):
        """Save campaign results to files"""
        
        # Save main results JSON
        results_file = self.output_dir / f"{self.campaign_id}_results.json"
        with open(results_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\n✅ Campaign results saved to: {results_file}")
        
        # Save markdown report
        report_file = self.output_dir / f"{self.campaign_id}_report.md"
        with open(report_file, 'w') as f:
            f.write(self._generate_markdown_report(output))
        
        print(f"✅ Campaign report saved to: {report_file}")
    
    def _generate_markdown_report(self, output):
        """Generate a markdown campaign report"""
        
        template = f"""# Voice Campaign Report
**Campaign ID:** {output['campaign_id']}  
**Date:** {datetime.fromisoformat(output['timestamp']).strftime('%B %d, %Y at %I:%M %p')}  
**Mode:** {'🧪 DRY RUN (Simulation)' if output['dry_run'] else '📞 LIVE CAMPAIGN'}

---

## 📊 Summary

- **Accounts Processed:** {output['summary']['total_accounts']}
- **Calls Attempted:** {output['summary']['calls_attempted']}
- **Follow-up Emails Drafted:** {output['summary']['emails_drafted']}
- **CRM Updates:** {output['summary']['crm_updates']}

---

## 🤖 Crew Output

```
{output['crew_output']}
```

---

## 📋 Next Steps

1. Review call outcomes and follow-up email drafts
2. Send approved follow-up emails
3. Schedule follow-up calls based on outcomes
4. Update opportunities in Salesforce based on conversations

---

*Generated by Voice Campaign Crew (CrewAI)*
"""
        
        return template


def create_voice_campaign_crew(account_list, dry_run=True, output_dir=None):
    """Factory function to create a voice campaign crew"""
    return VoiceCampaignCrew(account_list, dry_run=dry_run, output_dir=output_dir)


# Quick test function
def test_crew():
    """Test the crew with sample data"""
    sample_accounts = [
        {
            "account_name": "Example School District",
            "salesforce_id": "0011234567890ABC",
            "contact_name": "Jane Doe",
            "phone": "+16025551234",
            "email": "jane.doe@example.edu"
        },
        {
            "account_name": "Test Community College",
            "salesforce_id": "0011234567890DEF",
            "contact_name": "John Smith",
            "phone": "+14805551234",
            "email": "john.smith@testcc.edu"
        }
    ]
    
    crew = create_voice_campaign_crew(sample_accounts, dry_run=True)
    results = crew.run_campaign()
    
    return results


if __name__ == "__main__":
    print("Testing Voice Campaign Crew...")
    test_crew()
