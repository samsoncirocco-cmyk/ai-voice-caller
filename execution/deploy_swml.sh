#!/bin/bash
# Deploy the SWML endpoint to Google Cloud Functions
# Run this from the ai-voice-caller-fix/ directory
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - Project set: gcloud config set project tatt-pro
#   - functions-framework in requirements.txt

set -e

echo "=== Deploying SWML Outbound Endpoint to GCF ==="
echo "Project: tatt-pro"
echo "Function: swmlOutbound"
echo "Entry point: swml_outbound"
echo ""

gcloud functions deploy swmlOutbound \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source . \
  --entry-point swml_outbound \
  --trigger-http \
  --allow-unauthenticated \
  --memory 256MB \
  --timeout 10s \
  --project tatt-pro

echo ""
echo "=== Deployed! ==="
echo "Endpoint: https://us-central1-tatt-pro.cloudfunctions.net/swmlOutbound"
echo ""
echo "Test with:"
echo "  curl https://us-central1-tatt-pro.cloudfunctions.net/swmlOutbound?agent=cold-caller"
echo ""
echo "Place a test call with:"
echo "  python make_call_v5.py --to +16022950104 --agent cold-caller"
