"""PaginationStrategy interface (CLAUDE.md Section 3.3).

The Fetcher loop only ever calls these three methods; it has no idea whether
it's driving a body-embedded next-URL, a Link header, or offset/limit
pagination. A strategy signals "no more pages" by returning ``None`` from
``next_request``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.fetch.request_spec import RequestSpec


class PaginationStrategy(ABC):
    @abstractmethod
    def first_request(self, base_request: RequestSpec) -> RequestSpec:
        """Return the (possibly adjusted) first-page request."""
        raise NotImplementedError

    @abstractmethod
    def next_request(self, current_request: RequestSpec, response: httpx.Response) -> RequestSpec | None:
        """Return the next-page request, or None if there are no more pages."""
        raise NotImplementedError

    @abstractmethod
    def extract_records(self, response: httpx.Response) -> list[dict[str, Any]]:
        """Pull the list of record dicts out of a page response body."""
        raise NotImplementedError
