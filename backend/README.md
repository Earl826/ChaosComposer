
# ChaosComposer Backend

Python Azure Functions backend for the ChaosComposer
multiplayer music game.

## Azure resources

- Function App: func-groupt-chaoscomposer-dev
- Cosmos DB: cosmos-groupt-chaoscomposer-dev
- Database: chaoscomposer
- Container: gameState
- Partition key: /roomId
- Region: Germany West Central

## Local configuration

Copy local.settings.example.json to local.settings.json.

The real local.settings.json must never be committed.

The Cosmos connection string is optional for initial
in-memory testing. When enabled, it must refer to the
ChaosComposer Cosmos DB account.

Azure Functions requires local host storage.
Use Azurite with UseDevelopmentStorage=true.

## Running locally

Use Python 3.12 and Azure Functions Core Tools v4.

Create a virtual environment, install requirements.txt,
start Azurite, then run:

    func start

## Tests

    python -m pytest -q

## Current limitations

Several gameplay endpoints remain unimplemented.

Player authentication and concurrent Cosmos DB writes
are not yet production-ready.

Do not treat the in-memory repository as durable storage.
