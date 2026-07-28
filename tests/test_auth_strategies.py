from app.auth.api_key import ApiKeyAuth
from app.auth.bearer_token import BearerTokenAuth
from app.auth.none import NoAuth
from app.fetch.request_spec import RequestSpec


def _spec() -> RequestSpec:
    return RequestSpec(method="GET", url="https://example.com/things", headers={"Accept": "application/json"})


def test_no_auth_passes_request_through_unchanged():
    result = NoAuth().apply(_spec())
    assert result.headers == {"Accept": "application/json"}
    assert result.params == {}


def test_api_key_auth_injects_header():
    auth = ApiKeyAuth({"key_name": "X-Api-Key", "value": "secret123", "location": "header"})
    result = auth.apply(_spec())
    assert result.headers["X-Api-Key"] == "secret123"
    assert result.headers["Accept"] == "application/json"


def test_api_key_auth_injects_query_param():
    auth = ApiKeyAuth({"key_name": "api_key", "value": "secret123", "location": "query"})
    result = auth.apply(_spec())
    assert result.params == {"api_key": "secret123"}
    assert "api_key" not in result.headers


def test_bearer_token_auth_injects_authorization_header():
    auth = BearerTokenAuth({"token": "ghp_faketoken"})
    result = auth.apply(_spec())
    assert result.headers["Authorization"] == "Bearer ghp_faketoken"


def test_auth_strategies_do_not_mutate_input_request():
    original = _spec()
    ApiKeyAuth({"key_name": "k", "value": "v", "location": "header"}).apply(original)
    assert "k" not in original.headers
