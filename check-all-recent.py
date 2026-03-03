import requests
import json

with open('config/signalwire.json', 'r') as f:
    config = json.load(f)

project_id = config['project_id']
auth_token = config['auth_token']
space_url = config['space_url']

url = f"https://{space_url}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json"
params = {"PageSize": 10}

response = requests.get(url, auth=(project_id, auth_token), params=params)

if response.status_code == 200:
    data = response.json()
    calls = data.get('calls', [])
    
    print(f"📞 Last {len(calls)} calls:")
    for call in calls:
        sid = call.get('sid')
        status = call.get('status')
        to = call.get('to')
        duration = call.get('duration', 0)
        start = call.get('start_time', '')[:19] if call.get('start_time') else 'N/A'
        
        print(f"  {sid[:8]}... → {to} | {status} | {duration}s | {start}")
else:
    print(f"❌ Error: {response.status_code}")
