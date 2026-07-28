from __future__ import annotations

from app.auth.base import AuthStrategy
from app.fetch.request_spec import RequestSpec


class NoAuth(AuthStrategy):
    """No credentials injected. Used by public, unauthenticated APIs."""

    def apply(self, request: RequestSpec) -> RequestSpec:
        return request.copy_with()
