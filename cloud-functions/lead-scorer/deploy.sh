#!/bin/bash
# Deploy Lead Scorer Cloud Function
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Vertex AI API enabled
#   - Firestore in Native mode
#
# Usage: ./deploy.sh [--dry-run]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="lead-scorer"
RUNTIME="nodejs20"
MEMORY="512MB"
TIMEOUT="60s"
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

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true && log_info "Dry run mode"

log_info "Validating environment..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI not found"
    exit 1
fi

gcloud config set project "$PROJECT_ID" --quiet

# Check required APIs
log_info "Checking required APIs..."
REQUIRED_APIS=("aiplatform.googleapis.com" "firestore.googleapis.com")
for api in "${REQUIRED_APIS[@]}"; do
    if ! gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        log_warn "API $api not enabled. Enabling..."
        if [[ "$DRY_RUN" == false ]]; then
            gcloud services enable "$api" --quiet
        fi
    fi
done

# Environment variables
ENV_VARS="GCP_PROJECT=$PROJECT_ID,GCP_LOCATION=$REGION,GEMINI_MODEL=gemini-1.5-flash"

# Deploy
log_info "Deploying $FUNCTION_NAME..."

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=scoreLead \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --max-instances=$MAX_INSTANCES \
    --min-instances=$MIN_INSTANCES \
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
    echo "Test scoring:"
    echo "  curl -X POST $FUNCTION_URL \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"transcript\": [{\"role\": \"user\", \"text\": \"Tell me more about pricing\"}]}'"
fi

log_info "Done!"
