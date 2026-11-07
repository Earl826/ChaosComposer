import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import MusicalPattern, PatternTrack
from pattern_store import validate_musical_pattern, InMemoryChainRepository

def make_track(instrument: str) -> PatternTrack:
    return PatternTrack(instrument=instrument, steps=[True] + [False] * 15)

def test_valid_pattern_passes():
    pattern = MusicalPattern(
        tempo=120.0,
        tracks=[make_track("kick"), make_track("snare"), make_track("synth")],
    )

    validate_musical_pattern(pattern)

def test_unsupported_instrument_raises_error():
    pattern = MusicalPattern(
        tempo=120.0,
        tracks=[make_track("kazoo")],
    )
    with pytest.raises(ValueError, match="Unsupported instrument"):
        validate_musical_pattern(pattern)

def test_duplicate_instrument_raises_error():
    pattern = MusicalPattern(
        tempo=120.0,
        tracks=[make_track("kick"), make_track(" Kick ")],
    )
    with pytest.raises(ValueError, match="Duplicate instrument track"):
        validate_musical_pattern(pattern)

def test_in_memory_repository_save_get_and_list():
    repo = InMemoryChainRepository()

    chain_b = {"id": "chain_2", "session_code": "ROOM1", "versions": []}
    chain_a = {"id": "chain_1", "session_code": "ROOM1", "versions": []}
    other_room_chain = {"id": "chain_1", "session_code": "ROOM2", "versions": []}

    repo.save_chain(chain_b)
    repo.save_chain(chain_a)
    repo.save_chain(other_room_chain)

    assert repo.get_chain("ROOM1", "chain_1") == chain_a
    assert repo.get_chain("ROOM1", "non_existent") is None

    room1_chains = repo.list_chains_for_session("ROOM1")
    assert [c["id"] for c in room1_chains] == ["chain_1", "chain_2"]