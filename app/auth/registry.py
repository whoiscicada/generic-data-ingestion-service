"""auth.type string -> AuthStrategy class lookup.

This is the one place that has to know every AuthStrategy implementation
exists; adding a new auth style means adding one entry here plus one new
file in this package. Nothing else in the system changes.
"""

from __future__ import annotations

from app.auth.api_key import ApiKeyAuth
from app.auth.base import AuthStrategy
from app.auth.bearer_token import BearerTokenAuth
from app.auth.none import NoAuth
from app.config.schema import AuthConfig, AuthType

_STRATEGIES: dict[AuthType, type[AuthStrategy]] = {
    AuthType.NONE: NoAuth,
    AuthType.API_KEY: ApiKeyAuth,
    AuthType.BEARER_TOKEN: BearerTokenAuth,
}


def build_auth_strategy(config: AuthConfig) -> AuthStrategy:
    strategy_cls = _STRATEGIES.get(config.type)
    if strategy_cls is None:
        raise ValueError(f"no AuthStrategy registered for auth.type={config.type.value!r}")
    if strategy_cls is NoAuth:
        return NoAuth()
    return strategy_cls(config.config)
