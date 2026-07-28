from __future__ import annotations

from typing import Any

import httpx

from app.fetch.request_spec import RequestSpec
from app.pagination.base import PaginationStrategy
from app.pagination.json_path import get_json_path


class NextUrlInBodyPagination(PaginationStrategy):
    """Follows a full "next page" URL embedded in the response body.

    Config shape (``pagination.config``):
        next_url_json_path: str   -- e.g. "info.next"
        records_json_path: str    -- e.g. "results"

    Matches the Rick and Morty API's ``info.next`` / ``results`` shape.
    """

    def __init__(self, config: dict[str, Any]):
        self.next_url_json_path: str = config["next_url_json_path"]
        self.records_json_path: str = config["records_json_path"]

    def first_request(self, base_request: RequestSpec) -> RequestSpec:
        return base_request.copy_with()

    def next_request(self, current_request: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        next_url = get_json_path(response.json(), self.next_url_json_path)
        if not next_url:
            return None
        # The next-page URL already carries its own query string, so drop
        # the params we set on the first request rather than merging them.
        return current_request.copy_with(url=next_url, params={})

    def extract_records(self, response: httpx.Response) -> list[dict[str, Any]]:
        records = get_json_path(response.json(), self.records_json_path)
        return records if isinstance(records, list) else []
