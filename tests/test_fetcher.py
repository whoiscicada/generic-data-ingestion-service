import httpx
import pytest
import respx

from app.auth.none import NoAuth
from app.config.schema import SourceConfig
from app.fetch.fetcher import Fetcher
from app.fetch.rate_limiter import TokenBucketRateLimiter
from app.pagination.next_url_in_body import NextUrlInBodyPagination


def _source_config(**overrides) -> SourceConfig:
    data = {
        "source_id": "test_source",
        "base_url": "https://example.com/api",
        "endpoint": {"path": "/character"},
        "auth": {"type": "none"},
        "pagination": {
            "type": "next_url_in_body",
            "config": {"next_url_json_path": "info.next", "records_json_path": "results"},
        },
        "response": {"record_id_field": "id"},
        "retry": {"max_attempts": 3, "backoff_base_seconds": 0.01, "backoff_max_seconds": 0.02},
        "rate_limit": {"requests_per_second": 1000, "burst": 1000},
        "timeout_seconds": 5,
    }
    data.update(overrides)
    return SourceConfig.model_validate(data)


def _make_fetcher(source_config: SourceConfig) -> Fetcher:
    return Fetcher(
        source_config=source_config,
        auth=NoAuth(),
        pagination=NextUrlInBodyPagination(source_config.pagination.config),
        rate_limiter=TokenBucketRateLimiter(requests_per_second=1000, burst=1000),
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetcher_paginates_across_multiple_pages():
    # respx ignores query strings on a route registered without one, so both
    # calls hit the same route object; side_effect returns them in sequence.
    respx.get("https://example.com/api/character").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "info": {"next": "https://example.com/api/character?page=2"},
                    "results": [{"id": 1}, {"id": 2}],
                },
            ),
            httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 3}]}),
        ]
    )

    fetcher = _make_fetcher(_source_config())
    pages = [page async for page in fetcher.fetch_pages()]

    assert len(pages) == 2
    assert all(page.ok for page in pages)
    assert pages[0].records == [{"id": 1}, {"id": 2}]
    assert pages[1].records == [{"id": 3}]


@pytest.mark.asyncio
@respx.mock
async def test_fetcher_preserves_query_string_on_next_page_url():
    # Regression test: httpx silently strips a URL's own embedded query
    # string when params={} is passed alongside it (unlike params=None).
    # That bug made every "next page" request against a real API
    # (next-url-in-body/link-header pagination) silently re-fetch page 1
    # forever. respx's default (query-agnostic) route matching can't catch
    # this, so we inspect the actual outgoing request URL directly.
    seen_urls: list[str] = []

    def _responder(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if "page=2" in str(request.url):
            return httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 3}]})
        return httpx.Response(
            200,
            json={
                "info": {"next": "https://example.com/api/character?page=2"},
                "results": [{"id": 1}, {"id": 2}],
            },
        )

    respx.get("https://example.com/api/character").mock(side_effect=_responder)

    fetcher = _make_fetcher(_source_config())
    pages = [page async for page in fetcher.fetch_pages()]

    assert len(pages) == 2
    assert pages[1].records == [{"id": 3}]
    assert seen_urls == [
        "https://example.com/api/character",
        "https://example.com/api/character?page=2",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_fetcher_retries_on_transient_5xx_then_succeeds():
    route = respx.get("https://example.com/api/character")
    route.side_effect = [
        httpx.Response(503, json={}),
        httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 1}]}),
    ]

    fetcher = _make_fetcher(_source_config())
    pages = [page async for page in fetcher.fetch_pages()]

    assert len(pages) == 1
    assert pages[0].ok
    assert pages[0].records == [{"id": 1}]
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetcher_isolates_page_failure_after_exhausting_retries():
    respx.get("https://example.com/api/character").mock(return_value=httpx.Response(500, json={}))

    fetcher = _make_fetcher(_source_config())
    pages = [page async for page in fetcher.fetch_pages()]

    assert len(pages) == 1
    assert not pages[0].ok
    assert pages[0].error is not None


@pytest.mark.asyncio
@respx.mock
async def test_fetcher_does_not_retry_non_retryable_4xx():
    route = respx.get("https://example.com/api/character").mock(return_value=httpx.Response(404, json={}))

    fetcher = _make_fetcher(_source_config())
    pages = [page async for page in fetcher.fetch_pages()]

    assert len(pages) == 1
    assert not pages[0].ok
    assert route.call_count == 1
