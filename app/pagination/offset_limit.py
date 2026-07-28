from __future__ import annotations

from typing import Any

import httpx

from app.fetch.request_spec import RequestSpec
from app.pagination.base import PaginationStrategy
from app.pagination.json_path import get_json_path


class OffsetLimitPagination(PaginationStrategy):
    """Increments offset/limit query params until a short page signals the end.

    Config shape (``pagination.config``):
        records_json_path: str
        limit: int
        offset_param: str = "offset"
        limit_param: str = "limit"
        start_offset: int = 0
    """

    def __init__(self, config: dict[str, Any]):
        self.records_json_path: str = config["records_json_path"]
        self.limit: int = int(config["limit"])
        self.offset_param: str = config.get("offset_param", "offset")
        self.limit_param: str = config.get("limit_param", "limit")
        self.offset: int = int(config.get("start_offset", 0))

    def first_request(self, base_request: RequestSpec) -> RequestSpec:
        params = {**base_request.params, self.offset_param: self.offset, self.limit_param: self.limit}
        return base_request.copy_with(params=params)

    def next_request(self, current_request: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        records = self.extract_records(response)
        if len(records) < self.limit:
            return None
        self.offset += self.limit
        params = {**current_request.params, self.offset_param: self.offset, self.limit_param: self.limit}
        return current_request.copy_with(params=params)

    def extract_records(self, response: httpx.Response) -> list[dict[str, Any]]:
        records = get_json_path(response.json(), self.records_json_path)
        return records if isinstance(records, list) else []
