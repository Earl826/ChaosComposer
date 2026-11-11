from unittest.mock import Mock

import pytest
from azure.core.exceptions import ClientAuthenticationError

import pattern_store
from pattern_store import CosmosAccessError, CosmosConfigurationError, get_chain_repository


@pytest.fixture(autouse=True)
def cosmos_settings(monkeypatch):
    monkeypatch.setattr(pattern_store, "_cosmos_repository", None)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    for name, value in {
        "COSMOS_ENDPOINT": "https://example.documents.azure.com/",
        "COSMOS_DATABASE_NAME": "chaoscomposer",
        "COSMOS_CHAINS_CONTAINER": "gameState",
        "COSMOS_AUTH_MODE": "managed_identity",
        "AZURE_CLIENT_ID": "12345678-1234-1234-1234-123456789abc",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def sdk(monkeypatch):
    client, identity, cli = Mock(), Mock(), Mock()
    monkeypatch.setattr(pattern_store, "CosmosClient", client)
    monkeypatch.setattr(pattern_store, "ManagedIdentityCredential", identity)
    monkeypatch.setattr(pattern_store, "AzureCliCredential", cli)
    return client, identity, cli


def test_managed_identity_selects_the_configured_container_and_reuses_client(sdk):
    client, identity, cli = sdk
    repo = get_chain_repository()

    assert get_chain_repository() is repo
    identity.assert_called_once_with(client_id="12345678-1234-1234-1234-123456789abc")
    client.assert_called_once_with("https://example.documents.azure.com/", credential=identity.return_value)
    client.return_value.get_database_client.assert_called_once_with("chaoscomposer")
    client.return_value.get_database_client.return_value.get_container_client.assert_called_once_with("gameState")
    cli.assert_not_called()


def test_local_cosmos_can_use_azure_cli_login(monkeypatch, sdk):
    monkeypatch.setenv("COSMOS_AUTH_MODE", "azure_cli")
    monkeypatch.delenv("AZURE_CLIENT_ID")
    client, identity, cli = sdk

    get_chain_repository()

    cli.assert_called_once_with()
    client.assert_called_once_with("https://example.documents.azure.com/", credential=cli.return_value)
    identity.assert_not_called()


@pytest.mark.parametrize(
    "setting",
    ["COSMOS_ENDPOINT", "COSMOS_DATABASE_NAME", "COSMOS_CHAINS_CONTAINER", "COSMOS_AUTH_MODE", "AZURE_CLIENT_ID"],
)
def test_missing_configuration_fails_before_creating_a_client(monkeypatch, sdk, setting):
    monkeypatch.setenv(setting, " ")

    with pytest.raises(CosmosConfigurationError, match=setting):
        get_chain_repository()

    for mock in sdk:
        mock.assert_not_called()


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("COSMOS_ENDPOINT", "http://example.documents.azure.com"),
        ("COSMOS_ENDPOINT", "https://user:private@example.documents.azure.com/"),
        ("COSMOS_ENDPOINT", "https://example.documents.azure.com/?secret=private"),
        ("COSMOS_AUTH_MODE", "connection_string"),
        ("AZURE_CLIENT_ID", "invalid"),
    ],
)
def test_invalid_configuration_fails_without_echoing_value(monkeypatch, sdk, setting, value):
    monkeypatch.setenv(setting, value)

    with pytest.raises(CosmosConfigurationError, match=setting) as caught:
        get_chain_repository()

    assert "private" not in str(caught.value)
    for mock in sdk:
        mock.assert_not_called()


def test_hosted_app_rejects_local_cli_auth(monkeypatch, sdk):
    monkeypatch.setenv("COSMOS_AUTH_MODE", "azure_cli")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "chaoscomposer")

    with pytest.raises(CosmosConfigurationError, match="managed_identity"):
        get_chain_repository()

    for mock in sdk:
        mock.assert_not_called()


def test_failed_initialization_is_sanitized_and_can_be_retried(sdk):
    client, _, _ = sdk
    client.side_effect = [ClientAuthenticationError(message="private details"), client.return_value]

    with pytest.raises(CosmosAccessError, match="configured Entra credential") as caught:
        get_chain_repository()

    assert "private details" not in str(caught.value)
    assert get_chain_repository() is get_chain_repository()
    assert client.call_count == 2
