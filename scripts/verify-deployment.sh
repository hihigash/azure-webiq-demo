#!/usr/bin/env sh
set -eu

endpoint="$(azd env get-value SERVICE_WEB_URI)"
status=""
attempt=1
while [ "$attempt" -le 30 ]; do
  status="$(curl -sS -o /dev/null -w '%{http_code}' "${endpoint}/health" || true)"
  [ "$status" = "200" ] && break
  attempt=$((attempt + 1))
  sleep 5
done
[ "$status" = "200" ] || { echo "Deployment health check failed: ${endpoint}/health" >&2; exit 1; }
echo "Application is healthy: $endpoint"

if [ -z "$(azd env get-value WEB_IQ_API_KEY 2>/dev/null || true)" ]; then
  managed_identity_client_id="$(azd env get-value AZURE_MANAGED_IDENTITY_CLIENT_ID 2>/dev/null || true)"
  echo "Web IQ resource is provisioned. In https://webiq.microsoft.ai/profiles, connect the resource to an AppID and bind Managed Identity client ID '${managed_identity_client_id}'. This portal approval cannot be automated with ARM/Bicep. Then rerun verification." >&2
fi
