from unittest.mock import Mock

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosAccessConditionFailedError

from cosmos_room_repository import CosmosRoomRepository
from models import GameStatus, SessionState
from player_service import VersionConflict


@pytest.fixture
def stored_document():
    state = SessionState(
        session_code="K7QX",
        status=GameStatus.lobby,
        state_version=0,
        current_round=0,
        total_rounds=0,
        players=[],
        prompted_player_ids=[],
        submitted_player_ids=[],
    )

    return {
        "id": "room",
        "roomId": "K7QX",
        "type": "room",
        "state": state.model_dump(mode="json"),
        "token_hashes": {},
        "_etag": '"revision1"',
    }


def test_read_room(stored_document):
    container = Mock()
    container.read_item.return_value = stored_document

    room = CosmosRoomRepository(container).get_room("K7QX")

    assert room.state.session_code == "K7QX"
    assert room.etag == '"revision1"'
    container.read_item.assert_called_once_with(
        item="room",
        partition_key="K7QX",
    )


def test_save_uses_conditional_write(stored_document):
    container = Mock()
    container.read_item.return_value = stored_document
    repo = CosmosRoomRepository(container)

    room = repo.get_room("K7QX")
    repo.save_if_unchanged(room)

    kwargs = container.replace_item.call_args.kwargs

    assert kwargs["etag"] == '"revision1"'
    assert kwargs["match_condition"] == MatchConditions.IfNotModified
    assert kwargs["body"]["roomId"] == "K7QX"
    assert kwargs["retry_write"] == 0


def test_stale_write_is_rejected(stored_document):
    container = Mock()
    container.read_item.return_value = stored_document
    container.replace_item.side_effect = (
        CosmosAccessConditionFailedError(status_code=412)
    )
    repo = CosmosRoomRepository(container)

    with pytest.raises(VersionConflict):
        repo.save_if_unchanged(repo.get_room("K7QX"))


def test_delete_uses_conditional_write(stored_document):
    container = Mock()
    container.read_item.return_value = stored_document
    repo = CosmosRoomRepository(container)

    repo.delete_if_unchanged(repo.get_room("K7QX"))

    kwargs = container.delete_item.call_args.kwargs

    assert kwargs["partition_key"] == "K7QX"
    assert kwargs["etag"] == '"revision1"'
    assert kwargs["match_condition"] == MatchConditions.IfNotModified