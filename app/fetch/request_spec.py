"""RequestSpec: the value object AuthStrategy and PaginationStrategy operate on.

Keeping this as a plain, immutable-by-convention dataclass (rather than
handing strategies a live httpx.Request) is what lets AuthStrategy inject
headers/params and PaginationStrategy compute the next page independently of
each other and of the HTTP client itself.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestSpec:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None

    def copy_with(
        self,
        *,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> "RequestSpec":
        return RequestSpec(
            method=self.method,
            url=url if url is not None else self.url,
            headers=deepcopy(headers) if headers is not None else deepcopy(self.headers),
            params=deepcopy(params) if params is not None else deepcopy(self.params),
            json_body=deepcopy(self.json_body),
        )
