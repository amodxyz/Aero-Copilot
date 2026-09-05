# PowerShell Deployment Script for Google Cloud Run
param (
    [string]$ProjectId = "",
    [string]$Region = "us-central1",
    [string]$ServiceName = "productivity-agent"
)

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null).Trim()
}

if (-not $ProjectId) {
    Write-Host "❌ Error: Project ID is required." -ForegroundColor Red
    Write-Host "Usage: .\deploy.ps1 -ProjectId <YOUR_PROJECT_ID> [-Region <REGION>]"
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🚀 Deploying Personal Productivity Agent to Cloud Run" -ForegroundColor Cyan
Write-Host "   Project ID : $ProjectId"
Write-Host "   Region     : $Region"
Write-Host "   Service    : $ServiceName"
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Enable Cloud Run API
Write-Host "📦 Ensuring Cloud Run & Artifact Registry APIs are enabled..." -ForegroundColor Yellow
gcloud services enable run.googleapis.com artifactregistry.googleapis.com --project $ProjectId

# 2. Deploy from source
Write-Host "🚀 Building and deploying service to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --source . `
    --project $ProjectId `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --min-instances 0 `
    --max-instances 5 `
    --memory 512Mi `
    --cpu 1 `
    --set-env-vars="APP_ENV=production,GEMINI_MODEL=gemini-2.5-flash"

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "✅ Deployment Complete!" -ForegroundColor Green
$ServiceUrl = gcloud run services describe $ServiceName --project $ProjectId --region $Region --format="value(status.url)"
Write-Host "   Access URL: $ServiceUrl" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green
