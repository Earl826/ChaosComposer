import json
from unittest.mock import Mock

import azure.functions as func
import pytest

import function_app
from function_app import app
from pattern_store import CosmosAccessError


@pytest.fixture(scope="module")
def functions():
    return {function.get_function_name(): function for function in app.get_functions()}


def test_health_is_registered_as_anonymous_get(functions):
    route = functions["health"].get_trigger().get_dict_repr()
    assert route["route"] == "health"
    assert route["authLevel"] == func.AuthLevel.ANONYMOUS
    assert route["methods"] == [func.HttpMethod.GET]


def test_health_reports_api_liveness(functions):
    handler = functions["health"].get_user_function()
    request = func.HttpRequest(method="GET", url="/api/health", body=b"")

    response = handler(request)

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert json.loads(response.get_body()) == {
        "status": "ok",
        "service": "ChaosComposer API",
    }



@pytest.mark.parametrize("name", ["get_assignment", "submit_pattern", "reveal"])
def test_prototype_gameplay_routes_return_only_501(functions, name):
    function = functions[name]
    trigger = function.get_trigger().get_dict_repr()
    request = func.HttpRequest(
        method=trigger["methods"][0].value,
        url="/api/" + trigger["route"].format(session_code="K7QX"),
        headers={"X-Player-Token": "example", "X-Player-Name": "Example"},
        route_params={"session_code": "K7QX"},
        body=b"",
    )

    response = function.get_user_function()(request)

    assert response.status_code == 501
    assert json.loads(response.get_body()) == {"code": "not_implemented", "detail": name}



def test_readiness_is_registered_as_function_key_protected_get(functions):
    route = functions["cosmos_readiness"].get_trigger().get_dict_repr()
    assert route["route"] == "health/cosmos"
    assert route["authLevel"] == func.AuthLevel.FUNCTION
    assert route["methods"] == [func.HttpMethod.GET]


def test_health_does_not_initialize_cosmos(functions, monkeypatch):
    repo_factory = Mock(side_effect=AssertionError("Health should not access Cosmos"))
    monkeypatch.setattr(function_app, "get_chain_repository", repo_factory)
    request = func.HttpRequest(method="GET", url="/api/health", body=b"")

    assert functions["health"].get_user_function()(request).status_code == 200
    repo_factory.assert_not_called()


def test_readiness_calls_repository_check(functions, monkeypatch):
    repo = Mock()
    monkeypatch.setattr(function_app, "get_chain_repository", lambda: repo)
    request = func.HttpRequest(method="GET", url="/api/health/cosmos", body=b"")

    response = functions["cosmos_readiness"].get_user_function()(request)

    repo.check_ready.assert_called_once_with()
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {"status": "ok", "dependency": "cosmos"}


def test_readiness_returns_safe_error_for_failed_credentials(functions, monkeypatch, caplog):
    detail = "Cosmos access denied. Check the Cosmos DB for NoSQL data-plane role."
    monkeypatch.setattr(function_app, "get_chain_repository", Mock(side_effect=CosmosAccessError(detail)))
    request = func.HttpRequest(method="GET", url="/api/health/cosmos", body=b"")

    response = functions["cosmos_readiness"].get_user_function()(request)

    assert response.status_code == 503
    assert detail in caplog.text
    assert json.loads(response.get_body()) == {
        "code": "storage_unavailable",
        "detail": "Game storage is unavailable.",
    }



def test_openapi_lists_health_and_marks_gameplay_as_planned(functions):
    request = func.HttpRequest(method="GET", url="/api/openapi.json", body=b"")

    response = functions["openapi_json"].get_user_function()(request)
    spec = json.loads(response.get_body())

    assert response.status_code == 200
    assert "200" in spec["paths"]["/api/health"]["get"]["responses"]
    assert "501" in spec["paths"]["/api/sessions"]["post"]["responses"]
    assert "return 501" in spec["info"]["description"]
