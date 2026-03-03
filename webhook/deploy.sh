#!/bin/bash
# Deploy the Dialogflow webhook to Google Cloud Functions

set -e

PROJECT_ID="tatt-pro"
REGION="us-central1"
FUNCTION_NAME="dialogflowWebhook"

echo "🚀 Deploying SignalWire ↔ Dialogflow CX webhook..."
echo ""
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Deploy Cloud Function (2nd gen)
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime=nodejs20 \
  --region="$REGION" \
  --source=. \
  --entry-point=dialogflowWebhook \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MB \
  --timeout=60s \
  --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
  --max-instances=10 \
  --min-instances=0

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Webhook URL:"
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
echo "$FUNCTION_URL"
echo ""
echo "📝 Update SignalWire phone number configuration:"
echo "   1. Go to https://6eyes.signalwire.com/phone_numbers"
echo "   2. Click on phone number: +1 (602) 898-5026"
echo "   3. Under 'Voice & Fax' → 'A Call Comes In'"
echo "   4. Select: Webhook"
echo "   5. Enter URL: $FUNCTION_URL"
echo "   6. Method: POST"
echo "   7. Save"
echo ""
echo "🧪 Test the webhook:"
echo "   python3 scripts/make-dialogflow-call.py 6022950104"
