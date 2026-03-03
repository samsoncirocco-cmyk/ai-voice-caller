from google.cloud import firestore
db = firestore.Client(project="tatt-pro")

print("🔍 Checking all collections for call b2bd1be1...")

# Check all possible collections
collections = ['discovered-contacts', 'active_calls', 'call_logs', 'conversations', 'ai_agent_calls', 'discovery_calls']

for coll_name in collections:
    try:
        docs = db.collection(coll_name).stream()
        found = False
        for doc in docs:
            data = doc.to_dict()
            # Check if this doc contains our call ID
            doc_str = str(data)
            if 'b2bd1be1' in doc_str or 'b2bd1be1' in doc.id:
                if not found:
                    print(f"\n✅ Found in collection: {coll_name}")
                    found = True
                print(f"\n   Document ID: {doc.id}")
                for key, value in data.items():
                    print(f"   {key}: {value}")
    except Exception as e:
        pass  # Collection doesn't exist

# Also list all collections
print(f"\n\n📚 All Firestore collections:")
for coll in db.collections():
    print(f"   - {coll.id}")
