"""pagination.type string -> PaginationStrategy class lookup.

Same role as app/auth/registry.py: one entry per style, plus one new file
in this package, to add support for a new pagination mechanism.
"""

from __future__ import annotations

from app.config.schema import PaginationConfig, PaginationType
from app.pagination.base import PaginationStrategy
from app.pagination.link_header import LinkHeaderPagination
from app.pagination.next_url_in_body import NextUrlInBodyPagination
from app.pagination.offset_limit import OffsetLimitPagination
from app.pagination.page_number import PageNumberPagination

_STRATEGIES: dict[PaginationType, type[PaginationStrategy]] = {
    PaginationType.NEXT_URL_IN_BODY: NextUrlInBodyPagination,
    PaginationType.LINK_HEADER: LinkHeaderPagination,
    PaginationType.OFFSET_LIMIT: OffsetLimitPagination,
    PaginationType.PAGE_NUMBER: PageNumberPagination,
}


def build_pagination_strategy(config: PaginationConfig) -> PaginationStrategy:
    strategy_cls = _STRATEGIES.get(config.type)
    if strategy_cls is None:
        raise ValueError(f"no PaginationStrategy registered for pagination.type={config.type.value!r}")
    return strategy_cls(config.config)
