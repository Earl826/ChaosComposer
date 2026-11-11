from unittest.mock import Mock

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from pattern_store import (
    CosmosAccessError,
    CosmosChainRepository,
    CosmosStoreError,
    CosmosUnavailableError,
    InMemoryChainRepository,
    create_chain_document,
    handle_get_assignment_http,
)


def test_chain_document_matches_cosmos_partition_key():
    repo = InMemoryChainRepository()

    chain = create_chain_document(
        repo,
        "DEMO01",
        "chain_1",
        "A mysterious forest",
    )

    assert chain["roomId"] == "DEMO01"
    assert chain["session_code"] == "DEMO01"
    assert chain["type"] == "chain"


def test_cosmos_repository_uses_room_id_partition():
    container = Mock()

    chain = {
        "id": "chain_1",
        "roomId": "DEMO01",
        "session_code": "DEMO01",
        "type": "chain",
        "versions": [],
    }

    container.read_item.return_value = chain
    container.query_items.return_value = [chain]

    repo = CosmosChainRepository(container)

    repo.save_chain(chain)
    container.upsert_item.assert_called_once_with(
        body=chain
    )

    result = repo.get_chain("DEMO01", "chain_1")

    assert result == chain
    container.read_item.assert_called_once_with(
        item="chain_1",
        partition_key="DEMO01",
    )

    chains = repo.list_chains_for_session("DEMO01")

    assert chains == [chain]

    kwargs = container.query_items.call_args.kwargs

    assert "c.roomId" in kwargs["query"]
    assert "c.type = 'chain'" in kwargs["query"]
    assert kwargs["partition_key"] == "DEMO01"
    assert kwargs["parameters"] == [{"name": "@roomId", "value": "DEMO01"}]


@pytest.mark.parametrize("document", [{"id": "room", "roomId": "DEMO01", "type": "room"}, None])
def test_non_chain_item_is_absent(document):
    container = Mock()
    if document is None:
        container.read_item.side_effect = CosmosResourceNotFoundError(status_code=404)
    else:
        container.read_item.return_value = document

    assert CosmosChainRepository(container).get_chain("DEMO01", "room") is None


def test_cosmos_rejects_a_mismatched_partition_before_writing():
    container = Mock()
    chain = {"id": "chain_1", "session_code": "DEMO01", "roomId": "WRONG", "type": "chain"}

    with pytest.raises(ValueError, match="roomId matching session_code"):
        CosmosChainRepository(container).save_chain(chain)

    assert not container.mock_calls


def test_cosmos_distinguishes_missing_container_from_missing_chain():
    container = Mock()
    container.read_item.side_effect = CosmosResourceNotFoundError(status_code=404)
    container.read.side_effect = CosmosResourceNotFoundError(status_code=404)

    with pytest.raises(CosmosStoreError, match="configured database and container"):
        CosmosChainRepository(container).get_chain("DEMO01", "chain_1")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CosmosHttpResponseError(status_code=401, message="private details"), CosmosAccessError),
        (CosmosHttpResponseError(status_code=403, message="private details"), CosmosAccessError),
        (CosmosHttpResponseError(status_code=429, message="private details"), CosmosUnavailableError),
        (ServiceRequestError("private details"), CosmosUnavailableError),
    ],
)
def test_cosmos_read_failures_are_sanitized_and_return_503(error, expected):
    container = Mock()
    container.read_item.side_effect = error
    repo = CosmosChainRepository(container)

    with pytest.raises(expected) as caught:
        repo.get_chain("DEMO01", "chain_1")
    assert "private details" not in str(caught.value)

    response = handle_get_assignment_http(repo, "DEMO01", "chain_1", current_round=1)
    assert response.status_code == 503
    assert b"private details" not in response.get_body()


def test_cosmos_handles_failure_during_query_iteration():
    def failed_page():
        yield {"id": "chain_1", "type": "chain"}
        raise ServiceRequestError("private details")

    container = Mock()
    container.query_items.return_value = failed_page()
    with pytest.raises(CosmosUnavailableError, match="connectivity"):
        CosmosChainRepository(container).list_chains_for_session("DEMO01")
