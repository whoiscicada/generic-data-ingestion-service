from __future__ import annotations

from typing import Any

from app.auth.base import AuthStrategy
from app.fetch.request_spec import RequestSpec


class ApiKeyAuth(AuthStrategy):
    """Injects a static API key as either a header or a query parameter.

    Config shape (``auth.config``):
        key_name: str   -- header or query param name, e.g. "X-Api-Key"
        value: str      -- the key value (may come from an env-substituted config)
        location: str   -- "header" | "query"
    """

    def __init__(self, config: dict[str, Any]):
        self.key_name: str = config["key_name"]
        self.value: str = config["value"]
        self.location: str = config["location"]

    def apply(self, request: RequestSpec) -> RequestSpec:
        if self.location == "header":
            headers = {**request.headers, self.key_name: self.value}
            return request.copy_with(headers=headers)
        params = {**request.params, self.key_name: self.value}
        return request.copy_with(params=params)
