import httpx

from app.fetch.request_spec import RequestSpec
from app.pagination.link_header import LinkHeaderPagination
from app.pagination.next_url_in_body import NextUrlInBodyPagination
from app.pagination.offset_limit import OffsetLimitPagination
from app.pagination.page_number import PageNumberPagination


def _spec(url: str = "https://example.com/api/character") -> RequestSpec:
    return RequestSpec(method="GET", url=url)


def test_next_url_in_body_follows_info_next_until_null():
    strategy = NextUrlInBodyPagination({"next_url_json_path": "info.next", "records_json_path": "results"})
    request = strategy.first_request(_spec())
    assert request.url == "https://example.com/api/character"

    page1 = httpx.Response(200, json={"info": {"next": "https://example.com/api/character?page=2"}, "results": [{"id": 1}, {"id": 2}]})
    assert strategy.extract_records(page1) == [{"id": 1}, {"id": 2}]
    next_request = strategy.next_request(request, page1)
    assert next_request is not None
    assert next_request.url == "https://example.com/api/character?page=2"
    assert next_request.params == {}

    page2 = httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 3}]})
    assert strategy.next_request(next_request, page2) is None


def test_link_header_pagination_follows_rel_next():
    strategy = LinkHeaderPagination({"records_json_path": "$"})
    request = strategy.first_request(_spec("https://api.github.com/repos/x/y/issues"))

    page1 = httpx.Response(
        200,
        json=[{"id": 1}, {"id": 2}],
        headers={"Link": '<https://api.github.com/repos/x/y/issues?page=2>; rel="next"'},
    )
    assert strategy.extract_records(page1) == [{"id": 1}, {"id": 2}]
    next_request = strategy.next_request(request, page1)
    assert next_request is not None
    assert next_request.url == "https://api.github.com/repos/x/y/issues?page=2"

    page2 = httpx.Response(200, json=[{"id": 3}], headers={})
    assert strategy.next_request(next_request, page2) is None


def test_offset_limit_pagination_stops_on_short_page():
    strategy = OffsetLimitPagination({"records_json_path": "items", "limit": 2})
    request = strategy.first_request(_spec())
    assert request.params == {"offset": 0, "limit": 2}

    full_page = httpx.Response(200, json={"items": [{"id": 1}, {"id": 2}]})
    next_request = strategy.next_request(request, full_page)
    assert next_request is not None
    assert next_request.params == {"offset": 2, "limit": 2}

    short_page = httpx.Response(200, json={"items": [{"id": 3}]})
    assert strategy.next_request(next_request, short_page) is None


def test_page_number_pagination_stops_on_empty_page():
    strategy = PageNumberPagination({"records_json_path": "data"})
    request = strategy.first_request(_spec())
    assert request.params == {"page": 1}

    page1 = httpx.Response(200, json={"data": [{"id": 1}]})
    next_request = strategy.next_request(request, page1)
    assert next_request is not None
    assert next_request.params == {"page": 2}

    empty_page = httpx.Response(200, json={"data": []})
    assert strategy.next_request(next_request, empty_page) is None
