"""AuthStrategy interface.

Every concrete strategy takes a RequestSpec and returns a new one with
whatever headers/params/tokens it needs injected. The Fetcher calls
``apply`` once per outgoing request and never knows which auth style it's
driving.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.fetch.request_spec import RequestSpec


class AuthStrategy(ABC):
    @abstractmethod
    def apply(self, request: RequestSpec) -> RequestSpec:
        """Return a new RequestSpec with auth applied. Must not mutate the input."""
        raise NotImplementedError
