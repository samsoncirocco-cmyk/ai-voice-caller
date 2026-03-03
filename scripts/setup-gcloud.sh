#!/bin/bash
# Setup Google Cloud for AI Voice Caller
#
# This script enables required APIs, creates service accounts,
# and configures IAM permissions for the voice caller system.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Owner or Editor role on the GCP project
#
# Usage: ./setup-gcloud.sh [--project PROJECT_ID]

set -euo pipefail

# Default configuration
PROJECT_ID="${GCP_PROJECT:-tatt-pro}"
REGION="${GCP_REGION:-us-central1}"

# Service accounts to create
SA_VOICE_CALLER="voice-caller-sa"
SA_DIALOGFLOW="dialogflow-webhook-sa"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--project PROJECT_ID] [--region REGION]"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

log_info "Setting up AI Voice Caller on project: $PROJECT_ID"
log_info "Region: $REGION"
echo ""

# Check gcloud is installed
if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
fi

# Set project
log_step "Setting project..."
gcloud config set project "$PROJECT_ID" --quiet

# Enable required APIs
log_step "Enabling APIs..."

APIS=(
    "dialogflow.googleapis.com"          # Dialogflow CX
    "speech.googleapis.com"              # Speech-to-Text
    "texttospeech.googleapis.com"        # Text-to-Speech
    "aiplatform.googleapis.com"          # Vertex AI (Gemini)
    "cloudfunctions.googleapis.com"      # Cloud Functions
    "cloudbuild.googleapis.com"          # Cloud Build (for deployments)
    "run.googleapis.com"                 # Cloud Run (Gen2 functions)
    "firestore.googleapis.com"           # Firestore
    "bigquery.googleapis.com"            # BigQuery
    "secretmanager.googleapis.com"       # Secret Manager
    "calendar-json.googleapis.com"       # Google Calendar API
)

for api in "${APIS[@]}"; do
    log_info "  Enabling $api..."
    gcloud services enable "$api" --quiet 2>/dev/null || true
done

# Create Firestore database if not exists
log_step "Checking Firestore..."
FIRESTORE_EXISTS=$(gcloud firestore databases describe --format="value(name)" 2>/dev/null || echo "")
if [[ -z "$FIRESTORE_EXISTS" ]]; then
    log_info "Creating Firestore database..."
    gcloud firestore databases create --region="$REGION" --type=firestore-native --quiet 2>/dev/null || true
else
    log_info "Firestore already configured"
fi

# Create service accounts
log_step "Creating service accounts..."

create_service_account() {
    local sa_name=$1
    local display_name=$2
    local sa_email="${sa_name}@${PROJECT_ID}.iam.gserviceaccount.com"
    
    if gcloud iam service-accounts describe "$sa_email" &>/dev/null; then
        log_info "  Service account $sa_name already exists"
    else
        log_info "  Creating $sa_name..."
        gcloud iam service-accounts create "$sa_name" \
            --display-name="$display_name" \
            --quiet
    fi
    echo "$sa_email"
}

VOICE_CALLER_SA=$(create_service_account "$SA_VOICE_CALLER" "AI Voice Caller Service Account")
DIALOGFLOW_SA=$(create_service_account "$SA_DIALOGFLOW" "Dialogflow Webhook Service Account")

# Assign IAM roles
log_step "Assigning IAM roles..."

assign_role() {
    local sa_email=$1
    local role=$2
    log_info "  Assigning $role to $sa_email..."
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$sa_email" \
        --role="$role" \
        --quiet 2>/dev/null || true
}

# Voice Caller SA roles
assign_role "$VOICE_CALLER_SA" "roles/dialogflow.admin"
assign_role "$VOICE_CALLER_SA" "roles/aiplatform.user"
assign_role "$VOICE_CALLER_SA" "roles/datastore.user"
assign_role "$VOICE_CALLER_SA" "roles/bigquery.dataEditor"
assign_role "$VOICE_CALLER_SA" "roles/secretmanager.secretAccessor"

# Dialogflow webhook SA roles
assign_role "$DIALOGFLOW_SA" "roles/cloudfunctions.invoker"
assign_role "$DIALOGFLOW_SA" "roles/run.invoker"
assign_role "$DIALOGFLOW_SA" "roles/aiplatform.user"
assign_role "$DIALOGFLOW_SA" "roles/datastore.user"

# Create BigQuery dataset
log_step "Setting up BigQuery..."

DATASET_EXISTS=$(bq show --project_id="$PROJECT_ID" "voice_caller" 2>/dev/null || echo "")
if [[ -z "$DATASET_EXISTS" ]]; then
    log_info "Creating BigQuery dataset..."
    bq mk --dataset \
        --location="$REGION" \
        --description="AI Voice Caller analytics data" \
        "$PROJECT_ID:voice_caller" || true
else
    log_info "BigQuery dataset already exists"
fi

# Create call logs table
log_info "Creating BigQuery tables..."
bq query --use_legacy_sql=false --quiet "
CREATE TABLE IF NOT EXISTS \`$PROJECT_ID.voice_caller.call_logs\` (
    session_id STRING,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INT64,
    caller_phone STRING,
    caller_name STRING,
    account_name STRING,
    account_id STRING,
    use_case STRING,
    campaign STRING,
    outcome STRING,
    lead_score INT64,
    total_turns INT64,
    user_turns INT64,
    bot_turns INT64,
    meeting_booked BOOL,
    email_sent BOOL,
    region STRING,
    inserted_at TIMESTAMP
)
PARTITION BY DATE(start_time)
OPTIONS (description='Voice call logs for analytics')
" 2>/dev/null || true

# Create Secret Manager secrets (placeholders)
log_step "Setting up Secret Manager..."

create_secret() {
    local secret_name=$1
    local description=$2
    
    if gcloud secrets describe "$secret_name" &>/dev/null; then
        log_info "  Secret $secret_name already exists"
    else
        log_info "  Creating placeholder secret: $secret_name..."
        echo -n "PLACEHOLDER" | gcloud secrets create "$secret_name" \
            --data-file=- \
            --labels="app=voice-caller" \
            --quiet 2>/dev/null || true
        log_warn "    Remember to update $secret_name with actual value!"
    fi
}

create_secret "sf-username" "Salesforce username"
create_secret "sf-password" "Salesforce password"
create_secret "sf-security-token" "Salesforce security token"
create_secret "signalwire-project-id" "SignalWire project ID"
create_secret "signalwire-api-token" "SignalWire API token"
create_secret "signalwire-space-url" "SignalWire space URL"

# Grant secret access to service accounts
log_info "Granting secret access..."
SECRETS=("sf-username" "sf-password" "sf-security-token" "signalwire-project-id" "signalwire-api-token" "signalwire-space-url")
for secret in "${SECRETS[@]}"; do
    gcloud secrets add-iam-policy-binding "$secret" \
        --member="serviceAccount:$VOICE_CALLER_SA" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet 2>/dev/null || true
done

# Summary
echo ""
echo "============================================"
log_info "Setup complete!"
echo "============================================"
echo ""
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""
echo "Service Accounts:"
echo "  - $VOICE_CALLER_SA"
echo "  - $DIALOGFLOW_SA"
echo ""
echo "Enabled APIs:"
for api in "${APIS[@]}"; do
    echo "  - $api"
done
echo ""
echo "Resources Created:"
echo "  - Firestore database (native mode)"
echo "  - BigQuery dataset: voice_caller"
echo "  - Secret Manager secrets (need values!)"
echo ""
log_warn "ACTION REQUIRED:"
echo "  1. Update Secret Manager secrets with actual values:"
echo "     - sf-username, sf-password, sf-security-token"
echo "     - signalwire-project-id, signalwire-api-token, signalwire-space-url"
echo ""
echo "  2. Create calendar service account:"
echo "     - Create in GCP Console with domain-wide delegation"
echo "     - Upload JSON key to Secret Manager: calendar-service-account"
echo ""
echo "  3. Deploy Cloud Functions:"
echo "     cd cloud-functions/gemini-responder && ./deploy.sh"
echo "     (repeat for each function)"
echo ""
echo "  4. Deploy Dialogflow agent:"
echo "     cd dialogflow-agent && ./deploy-agent.sh --create"
echo ""

log_info "Done!"
