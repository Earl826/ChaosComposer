# ChaosComposer backend

Python 3.14 Azure Functions API for the ChaosComposer multiplayer music game.

## Run locally on Windows

Install CPython 3.14, Azure Functions Core Tools v4 with Python 3.14 support,
and Azurite. Run these commands from `backend` in PowerShell.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
if (!(Test-Path local.settings.json)) {
    Copy-Item local.settings.example.json local.settings.json
}
```

Create a fresh environment if `.venv` was created with a different Python
version. Keep `local.settings.json` and any `.env` files out of Git.

Start Azurite in one terminal and the Functions host in a second terminal
with the virtual environment active. Core Tools disables HTTP authorization
by default. Use `--enableAuth` to test protected routes.

```powershell
# Terminal 1, in backend
azurite --location .venv/azurite-data
# Terminal 2, in backend with .venv activated
func start --enableAuth
# Terminal 3
Invoke-RestMethod http://127.0.0.1:7071/api/health
```

Health, API docs and the test suite run without Azure access. To exercise
Cosmos locally, run `az login` and use an Azure CLI identity with a Cosmos DB
for NoSQL data-plane assignment on the target container. A Data Reader role
is sufficient for read-only development. Only run live storage checks
deliberately against the existing Serverless account.

| Setting | Local development | Existing Function App |
| --- | --- | --- |
| `COSMOS_AUTH_MODE` | `azure_cli` | `managed_identity` |
| `COSMOS_ENDPOINT` | Account HTTPS URI from Cosmos DB **Overview** | Account HTTPS URI from Cosmos DB **Overview** |
| `COSMOS_DATABASE_NAME` | `chaoscomposer` | `chaoscomposer` |
| `COSMOS_CHAINS_CONTAINER` | `gameState` | `gameState` |
| `AZURE_CLIENT_ID` | Leave empty | Client ID of `func-groupt-chaoscomposer-dev-uami` |

Leave the Cosmos placeholders empty for liveness-only local development.
The Cosmos repository requires explicit settings and uses Entra ID. Local
host storage uses `UseDevelopmentStorage=true` with Azurite.

## HTTP routes

- `GET /api/health` is public and checks API liveness.
- `GET /api/health/cosmos` requires a function key. It checks access to
  container metadata and verifies the `/roomId` partition. A 503 indicates
  a configuration, permission or storage failure. Operator logs contain the
  diagnostic message.
- `GET /api/docs` and `GET /api/openapi.json` are public. Session and
  negotiate schemas describe the proposed gameplay contract. All gameplay
  routes return 501 while player authentication and game state are unfinished.

The repository handles conditional updates for a single chain. Submission IDs
are scoped to that chain. Keep the same ID, player, round and pattern when
retrying after an ambiguous result. Room membership, phase and assignment
checks, and atomic room-level advancement still need to be implemented.


## Deploy to the existing Azure development app

Run the cloud changes and publishing steps only after the team approves the
deployment. Use the existing Azure for Students subscription, resource group
`rg-groupt-chaoscomposer-dev`, and Linux Flex Consumption Function App
`func-groupt-chaoscomposer-dev` in Germany West Central. Microsoft lists Python
3.14 as generally available for Azure Functions v4 and supported on Flex
Consumption. [Runtime support](https://learn.microsoft.com/azure/azure-functions/functions-versions?pivots=programming-language-python)
[Flex Consumption stacks](https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan#language-runtime-support)

1. **Confirm the app and identity.** In the Azure portal, open **Resource groups**
   → **rg-groupt-chaoscomposer-dev** → **func-groupt-chaoscomposer-dev**.
   Confirm the region, subscription and plan on **Overview**. Under **Settings**
   → **Identity** → **User assigned**, confirm
   `func-groupt-chaoscomposer-dev-uami` is attached. Open that managed identity's
   **Overview** and note its **Client ID** and **Object (principal) ID**.
2. **Assign Cosmos data access.** Use the **Object (principal) ID** for the
   assignment. In the PowerShell example below, substitute the subscription ID
   and run `az login` first. Assign **Cosmos DB Built-in Data Contributor**
   to the existing identity at the `gameState` container scope. Azure resource
   IAM roles and Cosmos SQL data-plane roles are managed separately.
   [Cosmos DB data-plane RBAC](https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control)

   ```powershell
   $subscription = '<Azure for Students subscription ID>'
   $rg = 'rg-groupt-chaoscomposer-dev'
   $app = 'func-groupt-chaoscomposer-dev'
   $account = 'cosmos-groupt-chaoscomposer-dev'
   $principal = '<user-assigned managed identity object ID>'
   $scope = '/dbs/chaoscomposer/colls/gameState'
   $role = '00000000-0000-0000-0000-000000000002'

   az cosmosdb sql role assignment list --subscription $subscription --resource-group $rg --account-name $account --query "[?principalId=='$principal'].{Scope:scope,Role:roleDefinitionId}" -o table
   # Run only if the exact assignment is missing.
   az cosmosdb sql role assignment create --subscription $subscription --resource-group $rg --account-name $account --principal-id $principal --role-definition-id $role --scope $scope
   ```

   Repeat the list command to check the principal, role and scope. Allow time
   for propagation before running the Cosmos smoke check.
3. **Set app settings.** In the Function App, go to **Settings** →
   **Environment variables** → **App settings**. Add the five settings in the
   **Existing Function App** column above. Copy the Cosmos HTTPS URI from
   **cosmos-groupt-chaoscomposer-dev** → **Overview**. Set `AZURE_CLIENT_ID`
   to the **Client ID** from step 1. Keep the app's existing Azure host
   storage and Application Insights configuration.
   [Function App settings](https://learn.microsoft.com/azure/azure-functions/functions-how-to-use-azure-function-app-settings?tabs=portal)
4. **Set Python 3.14 and publish.** From `backend`, with the 3.14 environment
   active, use Azure CLI and Core Tools v4. Confirm Python 3.14 appears in the
   regional runtime listing before changing the stack. The change can restart
   the app. Package source at the ZIP root and use a remote build for the
   Linux dependencies.

   ```powershell
   az functionapp list-flexconsumption-runtimes --subscription $subscription --location germanywestcentral -o table
   az functionapp runtime config set --subscription $subscription --resource-group $rg --name $app --runtime-version 3.14
   az functionapp runtime config show --subscription $subscription --resource-group $rg --name $app

   $env:FUNCTIONS_WORKER_RUNTIME = 'python'
   func pack --no-build --output .venv/chaoscomposer.zip
   az functionapp deployment source config-zip --subscription $subscription --resource-group $rg --name $app --src .venv/chaoscomposer.zip --build-remote true
   ```

   The Flex deployment uses your Azure CLI sign-in and existing deployment
   storage. [Flex runtime configuration](https://learn.microsoft.com/cli/azure/functionapp/runtime/config)
   [Flex ZIP deployment](https://learn.microsoft.com/azure/azure-functions/flex-consumption-how-to#deploy-your-code-project)
5. **Smoke-test the deployment.** In **Overview**, confirm the app is running.
   Use the **Default domain** shown there. Expect health to return
   `{"status":"ok","service":"ChaosComposer API"}`. Calling readiness without
   a key should return 401 or 403. For the authorized check, open
   **Functions** → **cosmos_readiness** → **Function keys** and use that
   function's default key in the `x-functions-key` header. Keep the key out of
   the URL, shell history and logs.
   [Function access keys](https://learn.microsoft.com/azure/azure-functions/function-keys-how-to)

   ```powershell
   $baseUri = 'https://<Default domain from Overview>'
   Invoke-RestMethod "$baseUri/api/health"
   $key = Read-Host 'Cosmos readiness function key' -AsSecureString
   try {
       $headerValue = [Net.NetworkCredential]::new('', $key).Password
       Invoke-RestMethod "$baseUri/api/health/cosmos" -Headers @{ 'x-functions-key' = $headerValue } -MaximumRedirection 0
   } finally {
       Remove-Variable key, headerValue -ErrorAction SilentlyContinue
   }
   ```

   Readiness should return `{"status":"ok","dependency":"cosmos"}`. This
   verifies authenticated access to container metadata. It performs no item
   writes. If it returns 503, check **Monitoring** → **Log stream** or
   Application Insights for the Cosmos readiness message, then verify the
   role assignment and network access.

## Remaining work

- **Azure** — Verify the existing app's runtime, live managed-identity access
  and remote build during the approved deployment. The automated Cosmos tests
  mock Azure SDK calls.
- **Gameplay** — Implement authenticated room membership and authoritative room
  state, assignment and reveal authorization, and atomic round advancement.
- **Real-time updates** — Add room-scoped SignalR notifications after membership
  and state transitions are in place.
- **Audio** — Design Blob Storage access and audio processing if recordings enter
  scope.
- **Performance** — Measure end-to-end latency, cold starts and Cosmos request
  units with representative concurrent rooms before tuning.
