from __future__ import annotations

from typing import Any

import httpx

from app.fetch.request_spec import RequestSpec
from app.pagination.base import PaginationStrategy
from app.pagination.json_path import get_json_path


class LinkHeaderPagination(PaginationStrategy):
    """Follows the RFC 5988 ``Link: <url>; rel="next"`` header (e.g. GitHub).

    Config shape (``pagination.config``):
        records_json_path: str  -- usually "$" since GitHub's list endpoints
                                    return a bare JSON array as the body.

    httpx parses the Link header for us via ``response.links``.
    """

    def __init__(self, config: dict[str, Any]):
        self.records_json_path: str = config["records_json_path"]

    def first_request(self, base_request: RequestSpec) -> RequestSpec:
        return base_request.copy_with()

    def next_request(self, current_request: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        next_link = response.links.get("next")
        if not next_link or "url" not in next_link:
            return None
        return current_request.copy_with(url=next_link["url"], params={})

    def extract_records(self, response: httpx.Response) -> list[dict[str, Any]]:
        records = get_json_path(response.json(), self.records_json_path)
        return records if isinstance(records, list) else []
