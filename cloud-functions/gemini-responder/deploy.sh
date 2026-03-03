#!/bin/bash
# Deploy Gemini Responder Cloud Function
# 
# Prerequisites:
#   - gcloud CLI authenticated
#   - APIs enabled (see scripts/setup-gcloud.sh)
#   - Environment variables configured
#
# Usage: ./deploy.sh [--dry-run]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="gemini-responder"
RUNTIME="nodejs20"
MEMORY="512MB"
TIMEOUT="60s"
MAX_INSTANCES="100"
MIN_INSTANCES="0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check for dry-run flag
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    log_info "Dry run mode - no changes will be made"
fi

# Validate environment
log_info "Validating environment..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
fi

# Check authentication
if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" | head -n1 > /dev/null 2>&1; then
    log_error "Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID" --quiet

# Check if required APIs are enabled
log_info "Checking required APIs..."
REQUIRED_APIS=("cloudfunctions.googleapis.com" "aiplatform.googleapis.com" "cloudbuild.googleapis.com")
for api in "${REQUIRED_APIS[@]}"; do
    if ! gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        log_warn "API $api not enabled. Enabling..."
        if [[ "$DRY_RUN" == false ]]; then
            gcloud services enable "$api" --quiet
        fi
    fi
done

# Build environment variables string
ENV_VARS="GCP_PROJECT=$PROJECT_ID,GCP_LOCATION=$REGION,GEMINI_MODEL=gemini-1.5-flash"

# Deploy function
log_info "Deploying $FUNCTION_NAME to $REGION..."

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=geminiRespond \
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
    
    # Get function URL
    FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
    
    log_info "Deployment complete!"
    echo ""
    echo "Function URL: $FUNCTION_URL"
    echo ""
    echo "Configure this URL in Dialogflow CX as a webhook:"
    echo "  1. Go to Dialogflow CX Console"
    echo "  2. Select your agent"
    echo "  3. Navigate to Manage > Webhooks"
    echo "  4. Create webhook with URL: $FUNCTION_URL"
fi

log_info "Done!"
