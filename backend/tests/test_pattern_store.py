import json
import sys
from pathlib import Path
import azure.functions as func
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import MusicalPattern, PatternTrack, SubmitPatternRequest
from pattern_store import (
    ConflictError,
    InMemoryChainRepository,
    create_chain_document,
    get_chain_assignment_for_round,
    get_session_reveal,
    handle_get_assignment_http,
    handle_reveal_http,
    handle_submit_pattern_http,
    record_pattern_submission,
    validate_musical_pattern,
)

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

def test_submission_preserves_versions_and_hides_prompt_in_later_rounds():
    repo = InMemoryChainRepository()
    create_chain_document(repo, "K7QX", "chain_1", "Upbeat 90s arcade boss battle")

    # Round 1 assignment should return the original prompt
    r1_input = get_chain_assignment_for_round(repo, "K7QX", "chain_1", current_round=1)
    assert r1_input.kind == "prompt"
    assert r1_input.prompt == "Upbeat 90s arcade boss battle"

    # Round 1 submission by Earl (120 BPM)
    p1 = MusicalPattern(tempo=120.0, tracks=[make_track("kick")])
    req1 = SubmitPatternRequest(chain_id="chain_1", expected_round=1, submission_id="sub_1", pattern=p1)
    v1 = record_pattern_submission(repo, "K7QX", "player_2", "Earl", req1)
    assert v1["version_id"] == "chain_1_v1"

    # Round 2 assignment should return ONLY v1's pattern (no prompt)
    r2_input = get_chain_assignment_for_round(repo, "K7QX", "chain_1", current_round=2)
    assert r2_input.kind == "pattern"
    assert r2_input.previous_version_id == "chain_1_v1"
    assert r2_input.pattern.tempo == 120.0

    # Round 2 submission by Barack (140 BPM)
    p2 = MusicalPattern(tempo=140.0, tracks=[make_track("kick"), make_track("snare")])
    req2 = SubmitPatternRequest(chain_id="chain_1", expected_round=2, submission_id="sub_2", pattern=p2)
    v2 = record_pattern_submission(repo, "K7QX", "player_3", "Barack", req2)
    assert v2["version_id"] == "chain_1_v2"

    # Final reveal should contain both versions in order without overwriting
    reveal = get_session_reveal(repo, "K7QX")
    assert len(reveal.chains) == 1
    assert len(reveal.chains[0].stages) == 2
    assert reveal.chains[0].stages[0].pattern.tempo == 120.0
    assert reveal.chains[0].stages[1].pattern.tempo == 140.0
    assert reveal.chains[0].final_version_id == "chain_1_v2"


def test_duplicate_and_out_of_order_submissions_rejected():
    repo = InMemoryChainRepository()
    create_chain_document(repo, "K7QX", "chain_1", "Test prompt")

    pattern = MusicalPattern(tempo=120.0, tracks=[make_track("kick")])
    req1 = SubmitPatternRequest(chain_id="chain_1", expected_round=1, submission_id="sub_1", pattern=pattern)

    # First submission succeeds
    first = record_pattern_submission(repo, "K7QX", "player_2", "Earl", req1)

    # Exact retry with same submission_id is idempotent (returns same version, doesn't duplicate)
    retry = record_pattern_submission(repo, "K7QX", "player_2", "Earl", req1)
    assert retry == first
    assert len(repo.get_chain("K7QX", "chain_1")["versions"]) == 1

    # Second submission for the same round with a different submission_id raises ConflictError
    req_dup_round = SubmitPatternRequest(chain_id="chain_1", expected_round=1, submission_id="sub_new", pattern=pattern)
    with pytest.raises(ConflictError, match="already has a submission"):
        record_pattern_submission(repo, "K7QX", "player_2", "Earl", req_dup_round)

    # Skipping Round 2 and submitting Round 3 raises ConflictError
    req_skip = SubmitPatternRequest(chain_id="chain_1", expected_round=3, submission_id="sub_3", pattern=pattern)
    with pytest.raises(ConflictError, match="Expected round 2"):
        record_pattern_submission(repo, "K7QX", "player_3", "Barack", req_skip)

def test_http_handlers_return_expected_status_codes():
    repo = InMemoryChainRepository()
    create_chain_document(repo, "K7QX", "chain_1", "Cyberpunk synthwave chase")

    # 1. Valid submission -> 200 OK
    valid_body = {
        "chain_id": "chain_1",
        "expected_round": 1,
        "submission_id": "sub_http_1",
        "pattern": {
            "schema_version": "1.0",
            "tempo": 125.0,
            "step_count": 16,
            "tracks": [{"instrument": "synth", "steps": [True] + [False] * 15}],
        },
    }
    req_ok = func.HttpRequest(
        method="POST",
        url="/api/sessions/K7QX/submissions",
        body=json.dumps(valid_body).encode("utf-8"),
    )
    resp_ok = handle_submit_pattern_http(req_ok, repo, "K7QX", "p2", "Earl")
    assert resp_ok.status_code == 200

    # 2. Invalid instrument -> 422 Unprocessable Entity
    invalid_body = {**valid_body, "submission_id": "sub_http_2", "pattern": {
        "schema_version": "1.0",
        "tempo": 125.0,
        "step_count": 16,
        "tracks": [{"instrument": "bagpipes", "steps": [True] + [False] * 15}],
    }}
    req_422 = func.HttpRequest(
        method="POST",
        url="/api/sessions/K7QX/submissions",
        body=json.dumps(invalid_body).encode("utf-8"),
    )
    resp_422 = handle_submit_pattern_http(req_422, repo, "K7QX", "p2", "Earl")
    assert resp_422.status_code == 422

    # 3. Conflicting round submission -> 409 Conflict
    conflict_body = {**valid_body, "submission_id": "sub_http_different"}
    req_409 = func.HttpRequest(
        method="POST",
        url="/api/sessions/K7QX/submissions",
        body=json.dumps(conflict_body).encode("utf-8"),
    )
    resp_409 = handle_submit_pattern_http(req_409, repo, "K7QX", "p2", "Earl")
    assert resp_409.status_code == 409

    # 4. Assignment for Round 2 -> 200 OK with previous pattern
    resp_assign = handle_get_assignment_http(repo, "K7QX", "chain_1", current_round=2)
    assert resp_assign.status_code == 200
    assert json.loads(resp_assign.get_body())["assignment"]["kind"] == "pattern"

    # 5. Reveal -> 200 OK
    resp_reveal = handle_reveal_http(repo, "K7QX")
    assert resp_reveal.status_code == 200
    assert len(json.loads(resp_reveal.get_body())["chains"]) == 1