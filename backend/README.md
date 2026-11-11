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
