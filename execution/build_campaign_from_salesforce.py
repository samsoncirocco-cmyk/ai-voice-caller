#!/usr/bin/env python3
"""
Build campaign CSV from Salesforce accounts.

Pulls all 832 accounts owned by Samson Cirocco with phone numbers.
Output: campaigns/sled-territory-832.csv (phone, name, account, notes)
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_CSV = BASE_DIR / "campaigns" / "sled-territory-832.csv"

OWNER_ID = "005Hr00000INgbqIAD"  # Samson Cirocco

def run_sf_query(query):
    """Run Salesforce query via sf CLI and return JSON result."""
    cmd = ["sf", "data", "query", "--query", query, "--json", "--target-org", "production"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    if data["status"] != 0:
        raise Exception(f"SF query failed: {data}")
    return data["result"]["records"]

def main():
    print("📞 Pulling accounts from Salesforce...")
    
    # Query accounts with phone numbers
    query = f"""
        SELECT Id, Name, Phone, BillingCity, BillingState, Industry, Website
        FROM Account
        WHERE OwnerId = '{OWNER_ID}'
        AND Phone != null
        ORDER BY Name
    """
    
    accounts = run_sf_query(query)
    print(f"✅ Found {len(accounts)} accounts with phone numbers")
    
    # Build CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["phone", "name", "account", "sf_account_id", "notes"])
        
        for acc in accounts:
            phone = acc["Phone"].strip()
            name = acc["Name"]
            account = acc["Name"]
            sf_account_id = acc.get("Id", "")
            
            # Build notes with context
            notes_parts = []
            if acc.get("BillingCity") and acc.get("BillingState"):
                notes_parts.append(f"{acc['BillingCity']}, {acc['BillingState']}")
            if acc.get("Industry"):
                notes_parts.append(acc["Industry"])
            if acc.get("Website"):
                notes_parts.append(acc["Website"])
            
            notes = " | ".join(notes_parts) if notes_parts else ""
            
            writer.writerow([phone, name, account, sf_account_id, notes])
    
    print(f"✅ Campaign CSV created: {OUTPUT_CSV}")
    print(f"📊 Total targets: {len(accounts)}")
    
    # Show sample
    print("\nSample rows:")
    with open(OUTPUT_CSV, "r") as f:
        for i, line in enumerate(f):
            if i < 4:  # Header + 3 rows
                print(f"  {line.rstrip()}")

if __name__ == "__main__":
    main()
