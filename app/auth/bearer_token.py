from __future__ import annotations

from typing import Any

from app.auth.base import AuthStrategy
from app.fetch.request_spec import RequestSpec


class BearerTokenAuth(AuthStrategy):
    """Injects a static ``Authorization: Bearer <token>`` header.

    Config shape (``auth.config``):
        token: str  -- typically ``${SOME_ENV_VAR}``, substituted at config-load time.

    Token refresh (OAuth2 client-credentials) is a separate, stretch strategy —
    this one assumes a long-lived static token, which is what a GitHub PAT is.
    """

    def __init__(self, config: dict[str, Any]):
        self.token: str = config["token"]

    def apply(self, request: RequestSpec) -> RequestSpec:
        headers = {**request.headers, "Authorization": f"Bearer {self.token}"}
        return request.copy_with(headers=headers)
