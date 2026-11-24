# Cosmos DB adapter for player and lobby state
from pattern_store import get_chain_repository
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceNotFoundError,
    CosmosResourceExistsError
)
from pydantic import ValidationError

from models import SessionState
from player_service import StoredRoom, VersionConflict
from pattern_store import ConflictError, CosmosStoreError, cosmos_operation


class CosmosRoomRepository:
    def __init__(self, container):
        self.container = container

    def get_room(self, session_code):
        with cosmos_operation():
            try:
                doc = self.container.read_item(
                    item="room",
                    partition_key=session_code,
                )
            except CosmosResourceNotFoundError:
                # Distinguish a missing room from a missing container.
                self.container.read()
                return None

        if (
            doc.get("type") != "room"
            or doc.get("roomId") != session_code
            or not doc.get("_etag")
        ):
            raise CosmosStoreError("Invalid room document")

        try:
            state = SessionState.model_validate(doc["state"])
            token_hashes = dict(doc["token_hashes"])
        except (ValidationError, KeyError, TypeError, ValueError):
            raise CosmosStoreError("Invalid room state") from None

        return StoredRoom(
            state=state,
            token_hashes=token_hashes,
            etag=doc["_etag"],
        )


    def create_if_absent(self, room):
        """Create a new room; raise ConflictError if the code is taken."""
        body = {
            "id": "room",
            "roomId": room.state.session_code,
            "type": "room",
            "state": room.state.model_dump(mode="json"),
            "token_hashes": room.token_hashes,
        }
        with cosmos_operation():
            try:
                self.container.create_item(body=body, retry_write=0)
            except CosmosResourceExistsError:
                raise ConflictError("A room with this code already exists.") from None
            

    def save_if_unchanged(self, room):
        body = {
            "id": "room",
            "roomId": room.state.session_code,
            "type": "room",
            "state": room.state.model_dump(mode="json"),
            "token_hashes": room.token_hashes,
        }

        with cosmos_operation():
            try:
                self.container.replace_item(
                    item="room",
                    body=body,
                    etag=room.etag,
                    match_condition=MatchConditions.IfNotModified,
                    retry_write=0,
                )
            except (
                CosmosAccessConditionFailedError,
                CosmosResourceNotFoundError,
            ):
                raise VersionConflict() from None

    def delete_if_unchanged(self, room):
        with cosmos_operation():
            try:
                self.container.delete_item(
                    item="room",
                    partition_key=room.state.session_code,
                    etag=room.etag,
                    match_condition=MatchConditions.IfNotModified,
                    retry_write=0,
                )
            except (
                CosmosAccessConditionFailedError,
                CosmosResourceNotFoundError,
            ):
                raise VersionConflict() from None

def get_room_repository() -> CosmosRoomRepository:
    """Reuse the team's existing Cosmos container connection."""
    chain_repository = get_chain_repository()
    return CosmosRoomRepository(chain_repository.container_client)