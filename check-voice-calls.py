from google.cloud import firestore
db = firestore.Client(project="tatt-pro")

print("📞 Recent voice-calls:")
docs = db.collection('voice-calls').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
for doc in docs:
    data = doc.to_dict()
    print(f"\n✅ Call: {doc.id}")
    for key, value in data.items():
        print(f"   {key}: {value}")
