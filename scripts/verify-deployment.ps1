$ErrorActionPreference = "Stop"

$endpoint = azd env get-value SERVICE_WEB_URI
$health = "$endpoint/health"
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -eq 200) {
            Write-Host "Application is healthy: $endpoint"
            break
        }
    } catch {
        Start-Sleep -Seconds 5
    }
}

if (-not $response -or $response.StatusCode -ne 200) {
    throw "Deployment health check failed: $health"
}

$webIqKey = azd env get-value WEB_IQ_API_KEY 2>$null
if ($LASTEXITCODE -ne 0 -or -not $webIqKey) {
    $managedIdentityClientId = azd env get-value AZURE_MANAGED_IDENTITY_CLIENT_ID 2>$null
    Write-Warning "Web IQ resource is provisioned. In https://webiq.microsoft.ai/profiles, connect the resource to an AppID and bind Managed Identity client ID '$managedIdentityClientId'. This portal approval cannot be automated with ARM/Bicep. Then rerun this verification."
}

