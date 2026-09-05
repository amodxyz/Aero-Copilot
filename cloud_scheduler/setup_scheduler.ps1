# ==============================================================================
# Google Cloud Scheduler Setup Script (PowerShell) for Personal Productivity Agent
# Creates or updates a Cloud Scheduler Cron Job to trigger daily reports.
# ==============================================================================

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true, HelpMessage = "Google Cloud Project ID")]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$Region = "us-central1",

    [Parameter(Mandatory = $false)]
    [string]$ServiceName = "productivity-agent",

    [Parameter(Mandatory = $false)]
    [string]$JobName = "daily-operations-briefing",

    [Parameter(Mandatory = $false)]
    [string]$Schedule = "0 8 * * *",

    [Parameter(Mandatory = $false)]
    [string]$TimeZone = "America/New_York"
)

$ErrorActionPreference = "Stop"

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Configuring Cloud Scheduler Job: $JobName" -ForegroundColor Cyan
Write-Host " Project: $ProjectId | Region: $Region" -ForegroundColor Cyan
Write-Host " Schedule: $Schedule ($TimeZone)" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

# 1. Retrieve Cloud Run Service URL
$SERVICE_URL = (gcloud run services describe $ServiceName --project=$ProjectId --region=$Region --format="value(status.url)").Trim()

if (-not $SERVICE_URL) {
    Write-Error "Could not find deployed Cloud Run service '$ServiceName'. Please deploy first via .\deploy.ps1"
}

$TARGET_URI = "$SERVICE_URL/api/cron/daily-report"
Write-Host "🎯 Target Cloud Run Endpoint: $TARGET_URI" -ForegroundColor Green

# 2. Service Account for Cloud Scheduler Invocation
$SA_NAME = "cloud-scheduler-invoker"
$SA_EMAIL = "${SA_NAME}@${ProjectId}.iam.gserviceaccount.com"

Write-Host "👤 Verifying Service Account: $SA_EMAIL..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts describe $SA_EMAIL --project=$ProjectId 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating dedicated Service Account '$SA_NAME'..." -ForegroundColor Yellow
    gcloud iam service-accounts create $SA_NAME `
        --project=$ProjectId `
        --display-name="Cloud Scheduler Invoker Service Account"
}

# 3. Grant Cloud Run Invoker role
Write-Host "🔐 Granting 'roles/run.invoker' role to $SA_EMAIL..." -ForegroundColor Yellow
gcloud run services add-iam-policy-binding $ServiceName `
    --project=$ProjectId `
    --region=$Region `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/run.invoker" `
    --quiet

# 4. Create or Update the Cloud Scheduler Cron Job
Write-Host "⏱️ Configuring Cloud Scheduler Cron Job '$JobName'..." -ForegroundColor Yellow
$jobExists = gcloud scheduler jobs describe $JobName --location=$Region --project=$ProjectId 2>&1

$bodyJson = '{"channel":"all","notify":true}'

if ($LASTEXITCODE -eq 0) {
    gcloud scheduler jobs update http $JobName `
        --project=$ProjectId `
        --location=$Region `
        --schedule=$Schedule `
        --time-zone=$TimeZone `
        --uri=$TARGET_URI `
        --http-method="POST" `
        --message-body=$bodyJson `
        --oidc-service-account-email=$SA_EMAIL `
        --oidc-audience=$SERVICE_URL
} else {
    gcloud scheduler jobs create http $JobName `
        --project=$ProjectId `
        --location=$Region `
        --schedule=$Schedule `
        --time-zone=$TimeZone `
        --uri=$TARGET_URI `
        --http-method="POST" `
        --message-body=$bodyJson `
        --oidc-service-account-email=$SA_EMAIL `
        --oidc-audience=$SERVICE_URL
}

Write-Host "=========================================================" -ForegroundColor Green
Write-Host "✅ Cloud Scheduler configured successfully!" -ForegroundColor Green
Write-Host "To test run immediately:" -ForegroundColor Cyan
Write-Host "gcloud scheduler jobs run $JobName --location=$Region --project=$ProjectId" -ForegroundColor White
Write-Host "=========================================================" -ForegroundColor Green
