#!/bin/bash
# Deploy Calendar Booking Cloud Function
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Calendar service account JSON in Secret Manager: calendar-service-account
#   - Domain-wide delegation configured for calendar access
#
# Usage: ./deploy.sh [--dry-run]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="calendar-booking"
RUNTIME="nodejs20"
MEMORY="256MB"
TIMEOUT="30s"
MAX_INSTANCES="50"
MIN_INSTANCES="0"

# Calendar Configuration
CALENDAR_ID="${CALENDAR_ID:-primary}"
TIMEZONE="${TIMEZONE:-America/Phoenix}"
MEETING_DURATION="${MEETING_DURATION:-30}"
BUFFER_MINUTES="${BUFFER_MINUTES:-15}"

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

# Check secret exists
log_info "Checking Secret Manager..."
if ! gcloud secrets describe "calendar-service-account" > /dev/null 2>&1; then
    log_error "Secret 'calendar-service-account' not found"
    echo ""
    echo "Create it with:"
    echo "  1. Create a service account in GCP Console"
    echo "  2. Enable domain-wide delegation"
    echo "  3. Download JSON key"
    echo "  4. gcloud secrets create calendar-service-account --data-file=path/to/key.json"
    exit 1
fi

# Environment variables
ENV_VARS="GCP_PROJECT=$PROJECT_ID,CALENDAR_ID=$CALENDAR_ID,TIMEZONE=$TIMEZONE,MEETING_DURATION=$MEETING_DURATION,BUFFER_MINUTES=$BUFFER_MINUTES"

# Service account
SA_EMAIL="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA_EMAIL" > /dev/null 2>&1; then
    log_info "Creating service account..."
    if [[ "$DRY_RUN" == false ]]; then
        gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
            --display-name="Calendar Booking Function SA"
        
        gcloud secrets add-iam-policy-binding calendar-service-account \
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
    --entry-point=calendarBooking \
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
    echo "Test availability:"
    echo "  curl -X POST $FUNCTION_URL \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"action\": \"check_availability\"}'"
fi

log_info "Done!"
