# ChaosComposer - Azure Setup and Team Handover

> Shared development infrastructure. **Do not commit credentials, Function keys, Cosmos connection strings, or local settings containing secrets.**

## 1. Azure resources

| Resource | Value |
| --- | --- |
| Subscription | `Azure for Students` |
| Resource group | `rg-groupt-chaoscomposer-dev` |
| Function App | `func-groupt-chaoscomposer-dev` |
| Function App hosting | Linux Flex Consumption, Python 3.14, Azure Functions v4 |
| Cosmos DB account | `cosmos-groupt-chaoscomposer-dev` |
| Cosmos DB API / capacity | NoSQL, serverless |
| Cosmos DB database | `chaoscomposer` |
| Cosmos DB container | `gameState` |
| Partition key | `/roomId` |
| Function managed identity | `func-groupt-chaoscomposer-dev-uami` (user-assigned) |
| Resource region | Germany West Central |

The Function App uses its **managed identity** for Cosmos DB access. That identity has the **Cosmos DB Built-in Data Contributor** data-plane role scoped to the `gameState` container. Teammates do **not** need to share or copy the managed identity's credentials.

## 2. API endpoints

**Base URL**

```text
https://func-groupt-chaoscomposer-dev-cke4ctd3aefgfjgq.germanywestcentral-01.azurewebsites.net/api
```

**Public health check**

```text
GET /api/health
```

Expected successful response:

```json
{"status":"ok","service":"ChaosComposer API"}
```

**Cosmos DB readiness check**

```text
GET /api/health/cosmos
```

This endpoint requires an Azure Functions **function key**, supplied securely in the `x-functions-key` header. Do not commit, paste in public chats, or place this key in frontend source code.

Expected successful response (with a valid key):

```json
{"status":"ok","dependency":"cosmos"}
```

The health and Cosmos readiness endpoints have been verified on Azure previously. Other gameplay APIs may still be under implementation; check endpoint behavior before relying on it.

## 3. Backend structure and configuration

The Azure Functions project lives in **`backend/`**, not the repository root.

```text
CloudGroupT/
├── backend/
│   ├── function_app.py
│   ├── host.json
│   ├── requirements.txt
│   ├── pattern_store.py
│   ├── models.py
│   └── .funcignore
├── frontend/
└── docs/
    └── azure-setup.md
```

Cloud Function App settings include these names:

| Setting | Cloud value / meaning |
| --- | --- |
| `COSMOS_AUTH_MODE` | `managed_identity` |
| `COSMOS_ENDPOINT` | `https://cosmos-groupt-chaoscomposer-dev.documents.azure.com` |
| `COSMOS_DATABASE_NAME` | `chaoscomposer` |
| `COSMOS_CHAINS_CONTAINER` | `gameState` |
| `AZURE_CLIENT_ID` | Client ID of the user-assigned managed identity. Retrieve securely from Azure when needed. |

`COSMOS_ENDPOINT` must be a plain HTTPS account URL, **without `:443` or a trailing slash**. Other Function host settings (including storage and monitoring) are managed in Azure. Never overwrite cloud application settings with local development settings during deployment.

For local development, see `backend/local.settings.example.json` and the backend README. Keep any actual `local.settings.json` out of Git. Developers may need their own Azure sign-in and suitable access to test Cosmos DB locally; the cloud Function's managed identity does not automatically give every developer permission.

## 4. Deploying changes

**Team workflow**

1. Develop on a feature branch and open a pull request.
2. Run backend tests and get changes reviewed.
3. Merge into `main` before deployment.
4. Coordinate deployments: there is **one shared development Function App**, and redeploying replaces its application code. Avoid deploying unmerged personal branches.
5. Verify the live health endpoint after deployment.

**VS Code deployment**

- Sign into Azure using the account with appropriate access and select the **Azure for Students** subscription.
- In the Explorer, right-click the **`backend`** folder and select **Deploy to Function App**.
- Select the **existing** `func-groupt-chaoscomposer-dev` app. **Do not create a new Function App.**
- Ensure the deployment ZIP has `host.json` **at its root**, not inside `backend/`.
- Inspect packaging logs. A previous attempt from the repository root included tens of thousands of files (`frontend/node_modules`, `.git`, `.venv`) and failed because `host.json` was not at the package root. Even a backend-only VS Code deployment may spend time packaging local virtual environments, so check the file count/size and `.funcignore` behavior.

**Alternative: clean ZIP from committed backend**

From the **repository root**, in PowerShell:

```powershell
git archive --format=zip --output="../chaoscomposer-backend-deploy.zip" HEAD:backend
```

Upload that ZIP to **Azure Cloud Shell**, then run in Cloud Shell Bash:

```bash
az account set --subscription "Azure for Students"
az functionapp deployment source config-zip \
  --resource-group rg-groupt-chaoscomposer-dev \
  --name func-groupt-chaoscomposer-dev \
  --src ~/chaoscomposer-backend-deploy.zip \
  --build-remote true
```

The ZIP method packages **committed files** in `backend/`. Any uncommitted changes will **not** be included. Confirm that no other deployment is running before starting it.

## 5. Shared data and API contracts

The Cosmos container currently uses `/roomId` as its partition key. For consistent integration, agree across the team on common identifiers:

- `roomId` - room and partition identity
- `playerId` - player identity within a room
- `promptId` - prompt identity
- `chainId` - musical chain identity
- `phase` - game phase
- `roundNumber` - turn/round tracking

**Do not treat these names as a complete, final schema.** Agree on document types, ownership, validation rules, authorization, and endpoint contracts before merging changes to shared models or APIs.

Suggested ownership boundaries from the team plan:

- Room management: room creation, retrieval, capacity
- Player/lobby: joining, leaving, roster, readiness
- Prompts: submission, validation, **initial** prompt/chain assignment and prompt visibility
- Game engine: game phases and **subsequent** round rotations
- Pattern storage: musical contribution persistence and version history

## 6. Access and security

- Team members should use **their own Azure accounts**. Grant only required roles through **Resource group > Access control (IAM)**, subject to subscription permissions.
- Azure resource management permissions and **Cosmos DB data-plane access** are separate. Reader access does not automatically permit reading or writing game data.
- Do not expose Function keys, connection strings, tokens, passwords, or sensitive settings in GitHub, frontend bundles, screenshots, or shared logs.
- Frontend code should use only explicitly public endpoints; backend-only keys and credentials stay server-side.
- Coordinate changes to cloud application settings, Cosmos container settings, and managed-identity permissions.

## 7. Quick verification after a deployment

1. Confirm Azure Activity / deployment output reports success.
2. Open the [public health check](https://func-groupt-chaoscomposer-dev-cke4ctd3aefgfjgq.germanywestcentral-01.azurewebsites.net/api/health).
3. If a backend database change was made, verify Cosmos readiness using a securely obtained Function key and the `x-functions-key` header.
4. Run relevant integration tests and check Azure logs if any endpoint fails.

**Maintainer note:** Update this document when the endpoint hostname, resource names, schema, access model, or deployment procedure changes.
