#!/bin/bash
# Deploy Salesforce Task Cloud Function
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Salesforce credentials in Secret Manager:
#     - sf-username
#     - sf-password  
#     - sf-security-token
#
# Usage: ./deploy.sh [--dry-run]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="salesforce-task"
RUNTIME="nodejs20"
MEMORY="256MB"
TIMEOUT="120s"
MAX_INSTANCES="50"
MIN_INSTANCES="0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check for dry-run
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true && log_info "Dry run mode"

# Validate environment
log_info "Validating environment..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI not found"
    exit 1
fi

gcloud config set project "$PROJECT_ID" --quiet

# Check secrets exist
log_info "Checking Secret Manager secrets..."
REQUIRED_SECRETS=("sf-username" "sf-password" "sf-security-token")
for secret in "${REQUIRED_SECRETS[@]}"; do
    if ! gcloud secrets describe "$secret" > /dev/null 2>&1; then
        log_error "Secret '$secret' not found in Secret Manager"
        echo "Create it with: gcloud secrets create $secret --data-file=-"
        exit 1
    fi
done

# Build environment variables
ENV_VARS="GCP_PROJECT=$PROJECT_ID,SF_LOGIN_URL=https://login.salesforce.com"

# Get service account email
SA_EMAIL="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Check if service account exists, create if not
if ! gcloud iam service-accounts describe "$SA_EMAIL" > /dev/null 2>&1; then
    log_info "Creating service account..."
    if [[ "$DRY_RUN" == false ]]; then
        gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
            --display-name="Salesforce Task Function SA"
        
        # Grant Secret Manager access
        gcloud secrets add-iam-policy-binding sf-username \
            --member="serviceAccount:$SA_EMAIL" \
            --role="roles/secretmanager.secretAccessor"
        gcloud secrets add-iam-policy-binding sf-password \
            --member="serviceAccount:$SA_EMAIL" \
            --role="roles/secretmanager.secretAccessor"
        gcloud secrets add-iam-policy-binding sf-security-token \
            --member="serviceAccount:$SA_EMAIL" \
            --role="roles/secretmanager.secretAccessor"
    fi
fi

# Deploy
log_info "Deploying $FUNCTION_NAME..."

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=createSalesforceTask \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --max-instances=$MAX_INSTANCES \
    --min-instances=$MIN_INSTANCES \
    --service-account=$SA_EMAIL \
    --set-env-vars=$ENV_VARS \
    --quiet"

if [[ "$DRY_RUN" == true ]]; then
    log_info "Would run: $DEPLOY_CMD"
else
    eval "$DEPLOY_CMD"
    
    FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
    
    log_info "Deployment complete!"
    echo ""
    echo "Function URL: $FUNCTION_URL"
    echo ""
    echo "Test with:"
    echo "  curl -X POST $FUNCTION_URL \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"accountName\": \"Test Account\", \"outcome\": \"interested\", \"callSummary\": \"Test call\"}'"
fi

log_info "Done!"
