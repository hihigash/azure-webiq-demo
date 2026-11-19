targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string
@description('Primary Azure region.')
param location string
@description('OID of the user running azd, used for deployment-time diagnostics.')
param principalId string = ''
@secure()
@description('Optional runtime Web IQ API key. The resource and model still deploy without it.')
param webIqApiKey string = ''
@description('Web IQ AppID to select when the managed identity is bound to multiple profiles.')
param webIqAppId string = ''
@minValue(1)
@description('GlobalStandard GPT-5.1 deployment capacity. Each unit provides 1,000 TPM and 10 RPM.')
param openAiCapacity int = 3000
@description('Create a Web IQ billing resource. Disable only for subscriptions not enabled for Web IQ.')
param webIqEnabled bool = true

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  application: 'azure-webiq-comparison'
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources-${resourceToken}'
  scope: resourceGroup
  params: {
    environmentName: environmentName
    location: location
    resourceToken: resourceToken
    tags: tags
    principalId: principalId
    webIqApiKey: webIqApiKey
    webIqAppId: webIqAppId
    openAiCapacity: openAiCapacity
    webIqEnabled: webIqEnabled
  }
}

output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.containerRegistryName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.containerRegistryEndpoint
output AZURE_CONTAINER_ENVIRONMENT_NAME string = resources.outputs.containerAppsEnvironmentName
output SERVICE_WEB_RESOURCE_ID string = resources.outputs.containerAppResourceId
output SERVICE_WEB_NAME string = resources.outputs.containerAppName
output SERVICE_WEB_URI string = resources.outputs.containerAppUri
output AZURE_OPENAI_ENDPOINT string = resources.outputs.openAiEndpoint
output AZURE_OPENAI_DEPLOYMENT string = resources.outputs.openAiDeployment
output WEB_IQ_RESOURCE_ID string = resources.outputs.webIqResourceId
output KEY_VAULT_NAME string = resources.outputs.keyVaultName
output AZURE_MANAGED_IDENTITY_CLIENT_ID string = resources.outputs.managedIdentityClientId

