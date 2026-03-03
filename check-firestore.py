from google.cloud import firestore
import json

db = firestore.Client(project="tatt-pro")

# Check discovered-contacts collection
print("📊 Checking discovered-contacts...")
contacts = db.collection('discovered-contacts').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(5).stream()
for doc in contacts:
    data = doc.to_dict()
    print(f"\n✅ Contact found:")
    print(f"   ID: {doc.id}")
    print(f"   Name: {data.get('contact_name', 'N/A')}")
    print(f"   Phone: {data.get('contact_phone', 'N/A')}")
    print(f"   Call SID: {data.get('call_sid', 'N/A')}")
    print(f"   Timestamp: {data.get('timestamp', 'N/A')}")
    print(f"   Source: {data.get('source', 'N/A')}")

# Check active_calls collection
print("\n\n📞 Checking active_calls...")
calls = db.collection('active_calls').order_by('started_at', direction=firestore.Query.DESCENDING).limit(5).stream()
for doc in calls:
    data = doc.to_dict()
    print(f"\n✅ Call found:")
    print(f"   Call SID: {doc.id}")
    print(f"   Session ID: {data.get('session_id', 'N/A')}")
    print(f"   Turn count: {data.get('turn_count', 0)}")
    print(f"   Started: {data.get('started_at', 'N/A')}")
