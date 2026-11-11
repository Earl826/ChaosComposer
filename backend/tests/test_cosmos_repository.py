from copy import deepcopy
from unittest.mock import Mock

from azure.core import MatchConditions

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from models import SubmitPatternRequest

from pattern_store import (
    ConflictError,
    CosmosAccessError,
    CosmosChainRepository,
    CosmosConfigurationError,
    CosmosStoreError,
    CosmosUnavailableError,
    InMemoryChainRepository,
    StaleChainError,
    create_chain_document,
    handle_get_assignment_http,
    record_pattern_submission,
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

    persisted = {**chain, "_etag": '"1"'}
    container.read_item.return_value = persisted
    container.query_items.return_value = [persisted]

    repo = CosmosChainRepository(container)

    repo.save_chain(chain)
    container.create_item.assert_called_once_with(body=chain, retry_write=0)

    result = repo.get_chain("DEMO01", "chain_1")

    assert result == persisted
    container.read_item.assert_called_once_with(
        item="chain_1",
        partition_key="DEMO01",
    )

    chains = repo.list_chains_for_session("DEMO01")

    assert chains == [persisted]

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


def test_duplicate_chain_create_cannot_replace_existing_item():
    container = Mock()
    container.create_item.side_effect = CosmosResourceExistsError(status_code=409)
    repo = CosmosChainRepository(container)

    with pytest.raises(ConflictError, match="already exists"):
        create_chain_document(repo, "DEMO01", "chain_1", "Another prompt")

    container.replace_item.assert_not_called()


def test_cosmos_replaces_only_the_matching_revision():
    container = Mock()
    chain = create_chain_document(CosmosChainRepository(container), "DEMO01", "chain_1", "Prompt")

    CosmosChainRepository(container).save_chain({**chain, "_etag": '"1"', "_rid": "metadata"})

    container.replace_item.assert_called_once_with(
        item="chain_1",
        body=chain,
        etag='"1"',
        match_condition=MatchConditions.IfNotModified,
        retry_write=0,
    )


@pytest.fixture
def submission():
    return SubmitPatternRequest.model_validate({
        "chain_id": "chain_1",
        "expected_round": 1,
        "submission_id": "sub_1",
        "pattern": {"tempo": 120, "tracks": [{"instrument": "kick", "steps": [True] * 16}]},
    })


@pytest.mark.parametrize("winning_id", ["sub_1", "another_submission"])
def test_stale_etag_rereads_winner_before_deciding_to_retry(submission, winning_id):
    container = Mock()
    repo = CosmosChainRepository(container)
    chain = create_chain_document(repo, "DEMO01", "chain_1", "Prompt")
    before = {**chain, "_etag": '"1"'}
    container.read_item.return_value = before
    container.replace_item.side_effect = CosmosAccessConditionFailedError(status_code=412)
    winner = {
        "version_id": "chain_1_v1",
        "submission_id": winning_id,
        "round": 1,
        "player_id": "player_1",
        "player_name": "Earl",
        "pattern": submission.pattern.model_dump(),
    }
    container.read_item.side_effect = [deepcopy(before), {**before, "_etag": '"2"', "versions": [winner]}]

    if winning_id == submission.submission_id:
        assert record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission) == winner
    else:
        with pytest.raises(ConflictError, match="already has a submission"):
            record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission)

    assert container.read_item.call_count == 2
    container.replace_item.assert_called_once()


def test_cosmos_retries_only_stale_writes_and_caps_attempts(submission):
    container = Mock()
    repo = CosmosChainRepository(container)
    chain = create_chain_document(repo, "DEMO01", "chain_1", "Prompt")
    container.read_item.side_effect = [
        {**chain, "_etag": '"1"'}, {**chain, "_etag": '"2"'}, {**chain, "_etag": '"3"'},
    ]
    container.replace_item.side_effect = CosmosAccessConditionFailedError(status_code=412)

    with pytest.raises(StaleChainError):
        record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission)

    assert [call.kwargs["etag"] for call in container.replace_item.call_args_list] == ['"1"', '"2"', '"3"']


def test_ambiguous_write_failure_is_not_retried(submission):
    container = Mock()
    repo = CosmosChainRepository(container)
    chain = create_chain_document(repo, "DEMO01", "chain_1", "Prompt")
    container.read_item.return_value = {**chain, "_etag": '"1"'}
    container.replace_item.side_effect = ServiceRequestError("write outcome unknown")

    with pytest.raises(CosmosUnavailableError):
        record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission)

    container.replace_item.assert_called_once()


def test_duplicate_id_on_another_round_conflicts_after_round_advances(submission):
    repo = InMemoryChainRepository()
    create_chain_document(repo, "DEMO01", "chain_1", "Prompt")
    first = record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission)
    second_request = submission.model_copy(update={"expected_round": 2, "submission_id": "sub_2"})
    second = record_pattern_submission(repo, "DEMO01", "player_2", "Barack", second_request)

    assert record_pattern_submission(repo, "DEMO01", "player_1", "Earl", submission) == first
    with pytest.raises(ConflictError, match="Conflicting reuse of submission_id"):
        record_pattern_submission(repo, "DEMO01", "player_2", "Barack", submission)
    with pytest.raises(ConflictError, match="Conflicting reuse of submission_id"):
        reused_id = second_request.model_copy(update={"submission_id": "sub_1"})
        record_pattern_submission(repo, "DEMO01", "player_1", "Earl", reused_id)
    assert repo.get_chain("DEMO01", "chain_1")["versions"] == [first, second]


def test_in_memory_repository_rejects_stale_snapshots():
    repo = InMemoryChainRepository()
    create_chain_document(repo, "DEMO01", "chain_1", "Prompt")
    stale = repo.get_chain("DEMO01", "chain_1")
    current = repo.get_chain("DEMO01", "chain_1")
    current["versions"].append({"version_id": "winner"})
    repo.save_chain(current)

    with pytest.raises(StaleChainError):
        repo.save_chain(stale)

    assert repo.get_chain("DEMO01", "chain_1")["versions"] == [{"version_id": "winner"}]



def test_readiness_accepts_room_partition_without_reading_game_data():
    container = Mock()
    container.read.return_value = {"partitionKey": {"paths": ["/roomId"]}}

    CosmosChainRepository(container).check_ready()

    container.read.assert_called_once_with()
    container.read_item.assert_not_called()
    container.query_items.assert_not_called()


def test_readiness_rejects_wrong_partition():
    container = Mock()
    container.read.return_value = {"partitionKey": {"paths": ["/session_code"]}}

    with pytest.raises(CosmosConfigurationError, match="/roomId"):
        CosmosChainRepository(container).check_ready()
