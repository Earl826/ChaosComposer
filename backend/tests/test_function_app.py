import json

import azure.functions as func
import pytest

from function_app import app


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
