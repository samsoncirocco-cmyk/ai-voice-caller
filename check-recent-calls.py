import requests
import json
from datetime import datetime, timedelta

# Load config
with open('config/signalwire.json', 'r') as f:
    config = json.load(f)

project_id = config['project_id']
auth_token = config['auth_token']
space_url = config['space_url']

# Use Compatibility API to list recent calls
url = f"https://{space_url}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json"

# Get calls from last 10 minutes
now = datetime.utcnow()
ten_min_ago = now - timedelta(minutes=10)

params = {
    "PageSize": 20,
    "StartTime>": ten_min_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
}

response = requests.get(url, auth=(project_id, auth_token), params=params)

if response.status_code == 200:
    data = response.json()
    calls = data.get('calls', [])
    
    print(f"📞 Recent calls (last 10 minutes): {len(calls)}")
    for call in calls:
        sid = call.get('sid')
        status = call.get('status')
        direction = call.get('direction')
        to = call.get('to')
        duration = call.get('duration', 0)
        start_time = call.get('start_time', 'N/A')
        
        print(f"\n✅ Call: {sid}")
        print(f"   Status: {status}")
        print(f"   Direction: {direction}")
        print(f"   To: {to}")
        print(f"   Duration: {duration}s")
        print(f"   Started: {start_time}")
else:
    print(f"❌ Failed to get calls: {response.status_code}")
    print(response.text)
