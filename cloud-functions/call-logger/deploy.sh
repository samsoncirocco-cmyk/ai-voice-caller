#!/bin/bash
# Deploy Call Logger Cloud Function
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Firestore in Native mode
#   - BigQuery dataset (optional)
#
# Usage: ./deploy.sh [--dry-run]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="call-logger"
RUNTIME="nodejs20"
MEMORY="256MB"
TIMEOUT="30s"
MAX_INSTANCES="100"
MIN_INSTANCES="0"

# Firestore/BigQuery settings
COLLECTION_NAME="${COLLECTION_NAME:-calls}"
BIGQUERY_DATASET="${BIGQUERY_DATASET:-voice_caller}"
BIGQUERY_TABLE="${BIGQUERY_TABLE:-call_logs}"
ENABLE_BIGQUERY="${ENABLE_BIGQUERY:-false}"

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

# Check Firestore
log_info "Checking Firestore..."
FIRESTORE_MODE=$(gcloud firestore databases describe --format="value(type)" 2>/dev/null || echo "none")
if [[ "$FIRESTORE_MODE" == "none" ]]; then
    log_warn "Firestore not configured. Creating in Native mode..."
    if [[ "$DRY_RUN" == false ]]; then
        gcloud firestore databases create --region="$REGION" --type=firestore-native
    fi
elif [[ "$FIRESTORE_MODE" != "FIRESTORE_NATIVE" ]]; then
    log_warn "Firestore is in $FIRESTORE_MODE mode"
fi

# Create BigQuery dataset if enabled
if [[ "$ENABLE_BIGQUERY" == "true" ]]; then
    log_info "Checking BigQuery dataset..."
    if ! bq show --project_id="$PROJECT_ID" "$BIGQUERY_DATASET" > /dev/null 2>&1; then
        log_info "Creating BigQuery dataset..."
        if [[ "$DRY_RUN" == false ]]; then
            bq mk --dataset "$PROJECT_ID:$BIGQUERY_DATASET"
            
            # Create table schema
            bq mk --table "$PROJECT_ID:$BIGQUERY_DATASET.$BIGQUERY_TABLE" \
                session_id:STRING,start_time:TIMESTAMP,end_time:TIMESTAMP,duration_seconds:INTEGER,\
caller_phone:STRING,caller_name:STRING,account_name:STRING,account_id:STRING,\
use_case:STRING,campaign:STRING,outcome:STRING,lead_score:INTEGER,\
total_turns:INTEGER,user_turns:INTEGER,bot_turns:INTEGER,\
meeting_booked:BOOLEAN,email_sent:BOOLEAN,region:STRING,inserted_at:TIMESTAMP
        fi
    fi
fi

# Environment variables
ENV_VARS="GCP_PROJECT=$PROJECT_ID,COLLECTION_NAME=$COLLECTION_NAME,BIGQUERY_DATASET=$BIGQUERY_DATASET,BIGQUERY_TABLE=$BIGQUERY_TABLE,ENABLE_BIGQUERY=$ENABLE_BIGQUERY"

# Deploy
log_info "Deploying $FUNCTION_NAME..."

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=logCall \
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
    echo "Test call start:"
    echo "  curl -X POST $FUNCTION_URL \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"sessionId\": \"test-123\", \"action\": \"start\", \"accountName\": \"Test\"}'"
fi

log_info "Done!"
