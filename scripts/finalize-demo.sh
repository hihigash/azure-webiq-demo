#!/usr/bin/env sh
set -eu

resource_group="$(azd env get-value AZURE_RESOURCE_GROUP)"
app_name="$(azd env get-value SERVICE_WEB_NAME)"
az containerapp auth update --resource-group "$resource_group" --name "$app_name" --enabled false --action AllowAnonymous --yes --output none
"$(dirname "$0")/verify-deployment.sh"
