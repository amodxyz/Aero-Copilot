#!/bin/bash
# ==============================================================================
# Google Cloud Scheduler Setup Script for Personal Productivity Agent
# Creates or updates a Cloud Scheduler Cron Job to trigger daily reports.
# ==============================================================================

set -e

PROJECT_ID=${1:-$(gcloud config get-value project)}
REGION=${2:-"us-central1"}
SERVICE_NAME="productivity-agent"
JOB_NAME="daily-operations-briefing"
SCHEDULE="0 8 * * *" # Every day at 8:00 AM
TIME_ZONE="America/New_York"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Google Cloud Project ID is required."
    echo "Usage: ./setup_scheduler.sh <PROJECT_ID> [REGION]"
    exit 1
fi

echo "========================================================="
echo " Configuring Cloud Scheduler Job: $JOB_NAME"
echo " Project: $PROJECT_ID | Region: $REGION"
echo " Schedule: $SCHEDULE ($TIME_ZONE)"
echo "========================================================="

# 1. Retrieve Cloud Run Service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format="value(status.url)")

if [ -z "$SERVICE_URL" ]; then
    echo "❌ Error: Could not find deployed Cloud Run service '$SERVICE_NAME'."
    echo "Please ensure the service is deployed first via ./deploy.sh"
    exit 1
fi

TARGET_URI="${SERVICE_URL}/api/cron/daily-report"
echo "🎯 Target Cloud Run Endpoint: $TARGET_URI"

# 2. Ensure Service Account exists for Cloud Scheduler OIDC invocation
SA_NAME="cloud-scheduler-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
    echo "👤 Creating dedicated Service Account '$SA_NAME'..."
    gcloud iam service-accounts create "$SA_NAME" \
        --project="$PROJECT_ID" \
        --display-name="Cloud Scheduler Invoker Service Account"
fi

# 3. Grant Cloud Run Invoker role to the Service Account
echo "🔐 Granting 'roles/run.invoker' role to $SA_EMAIL..."
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.invoker" \
    --quiet

# 4. Create or Update the Cloud Scheduler Cron Job
echo "⏱️ Creating / Updating Cloud Scheduler Job '$JOB_NAME'..."
if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    gcloud scheduler jobs update http "$JOB_NAME" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIME_ZONE" \
        --uri="$TARGET_URI" \
        --http-method="POST" \
        --message-body='{"channel":"all","notify":true}' \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-audience="$SERVICE_URL"
else
    gcloud scheduler jobs create http "$JOB_NAME" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIME_ZONE" \
        --uri="$TARGET_URI" \
        --http-method="POST" \
        --message-body='{"channel":"all","notify":true}' \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-audience="$SERVICE_URL"
fi

echo "========================================================="
echo "✅ Cloud Scheduler configured successfully!"
echo "To test run the job immediately:"
echo "gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo "========================================================="
