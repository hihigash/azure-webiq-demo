$ErrorActionPreference = "Stop"

$resourceGroup = azd env get-value AZURE_RESOURCE_GROUP
$appName = azd env get-value SERVICE_WEB_NAME

az containerapp auth update --resource-group $resourceGroup --name $appName --enabled false --action AllowAnonymous --yes --output none
& "$PSScriptRoot\verify-deployment.ps1"

