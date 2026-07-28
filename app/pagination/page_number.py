from __future__ import annotations

from typing import Any

import httpx

from app.fetch.request_spec import RequestSpec
from app.pagination.base import PaginationStrategy
from app.pagination.json_path import get_json_path


class PageNumberPagination(PaginationStrategy):
    """Simple ``?page=N`` pagination; stops on the first empty page.

    Config shape (``pagination.config``):
        records_json_path: str
        page_param: str = "page"
        start_page: int = 1
        page_size_param: str | None = None
        page_size: int | None = None
    """

    def __init__(self, config: dict[str, Any]):
        self.records_json_path: str = config["records_json_path"]
        self.page_param: str = config.get("page_param", "page")
        self.page: int = int(config.get("start_page", 1))
        self.page_size_param: str | None = config.get("page_size_param")
        self.page_size: int | None = config.get("page_size")

    def first_request(self, base_request: RequestSpec) -> RequestSpec:
        params = {**base_request.params, self.page_param: self.page}
        if self.page_size_param and self.page_size is not None:
            params[self.page_size_param] = self.page_size
        return base_request.copy_with(params=params)

    def next_request(self, current_request: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        records = self.extract_records(response)
        if not records:
            return None
        self.page += 1
        params = {**current_request.params, self.page_param: self.page}
        return current_request.copy_with(params=params)

    def extract_records(self, response: httpx.Response) -> list[dict[str, Any]]:
        records = get_json_path(response.json(), self.records_json_path)
        return records if isinstance(records, list) else []
