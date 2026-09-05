#!/usr/bin/env bash
# Deploy Personal Productivity Assistant to Google Cloud Run
# Usage: ./deploy.sh [PROJECT_ID] [REGION]

set -e

PROJECT_ID=${1:-$(gcloud config get-value project 2>/dev/null)}
REGION=${2:-"us-central1"}
SERVICE_NAME="productivity-agent"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Google Cloud Project ID is not set. Provide it as the first argument:"
    echo "   ./deploy.sh <YOUR_PROJECT_ID> [REGION]"
    exit 1
fi

echo "=========================================================="
echo "🚀 Deploying Personal Productivity Agent to Cloud Run"
echo "   Project ID : $PROJECT_ID"
echo "   Region     : $REGION"
echo "   Service    : $SERVICE_NAME"
echo "=========================================================="

# 1. Enable necessary Google Cloud APIs
echo "📦 Ensuring Cloud Run & Artifact Registry APIs are enabled..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com --project "$PROJECT_ID"

# 2. Deploy directly from source to Cloud Run
echo "🚀 Building container image and deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 5 \
    --memory 512Mi \
    --cpu 1 \
    --set-env-vars="APP_ENV=production,GEMINI_MODEL=gemini-2.5-flash"

echo "=========================================================="
echo "✅ Deployment completed successfully!"
echo "   Your Productivity Assistant is live at:"
gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format="value(status.url)"
echo "=========================================================="
