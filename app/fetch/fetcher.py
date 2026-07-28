"""Fetcher: drives one source end-to-end (CLAUDE.md Section 3.4).

Builds the initial request from SourceConfig, applies AuthStrategy on every
attempt, executes via httpx.AsyncClient, rate-limits via a per-source token
bucket, retries transient failures with exponential backoff + jitter
(honoring Retry-After when present), enforces per-request timeouts, and logs
each attempt at a structured level. Yields one PageResult per page so the
caller (IngestionJob) can hand records to sinks incrementally and isolate a
failing page without aborting the whole run.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt

from app.auth.base import AuthStrategy
from app.config.schema import SourceConfig
from app.fetch.rate_limiter import TokenBucketRateLimiter
from app.fetch.request_spec import RequestSpec
from app.pagination.base import PaginationStrategy

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class TransientHTTPError(Exception):
    """A response status that's worth retrying (429 / 5xx)."""

    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__(f"transient HTTP status {response.status_code} from {response.request.url}")


@dataclass
class PageResult:
    page_number: int
    records: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class Fetcher:
    # Hard ceiling on pages per run. A misconfigured or misbehaving source
    # (e.g. a "next" cursor that never advances) must not be able to loop
    # forever; this turns that failure mode into a bounded, logged one.
    DEFAULT_MAX_PAGES = 10_000

    def __init__(
        self,
        source_config: SourceConfig,
        auth: AuthStrategy,
        pagination: PaginationStrategy,
        rate_limiter: TokenBucketRateLimiter | None = None,
        client: httpx.AsyncClient | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ):
        self.source_config = source_config
        self.auth = auth
        self.pagination = pagination
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(
            requests_per_second=source_config.rate_limit.requests_per_second,
            burst=source_config.rate_limit.burst,
        )
        self._external_client = client
        self.max_pages = max_pages

    def _build_first_request(self) -> RequestSpec:
        endpoint = self.source_config.endpoint
        base = RequestSpec(
            method=endpoint.method.value,
            url=f"{self.source_config.base_url}{endpoint.path}",
            params=dict(endpoint.static_params),
        )
        return self.pagination.first_request(base)

    def _backoff_seconds(self, attempt: int, retry_after_header: str | None) -> float:
        if retry_after_header:
            try:
                return float(retry_after_header)
            except ValueError:
                pass
        retry_cfg = self.source_config.retry
        exp = min(retry_cfg.backoff_max_seconds, retry_cfg.backoff_base_seconds * (2 ** (attempt - 1)))
        return exp * (0.5 + random.random() / 2)

    def _wait(self, retry_state: RetryCallState) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        retry_after = exc.response.headers.get("Retry-After") if isinstance(exc, TransientHTTPError) else None
        return self._backoff_seconds(retry_state.attempt_number, retry_after)

    def _before_sleep(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "fetch_attempt_failed",
            extra={
                "source_id": self.source_config.source_id,
                "attempt": retry_state.attempt_number,
                "max_attempts": self.source_config.retry.max_attempts,
                "error": str(exc),
            },
        )

    async def _send_with_retries(self, client: httpx.AsyncClient, request: RequestSpec) -> httpx.Response:
        retry_cfg = self.source_config.retry
        retrying = AsyncRetrying(
            stop=stop_after_attempt(retry_cfg.max_attempts),
            wait=self._wait,
            retry=retry_if_exception_type((TransientHTTPError, httpx.TimeoutException, httpx.TransportError)),
            before_sleep=self._before_sleep,
            reraise=True,
        )

        async for attempt in retrying:
            with attempt:
                authed = self.auth.apply(request)
                start = time.monotonic()
                response = await client.request(
                    authed.method,
                    authed.url,
                    headers=authed.headers,
                    params=authed.params,
                    json=authed.json_body,
                    timeout=self.source_config.timeout_seconds,
                )
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                logger.info(
                    "fetch_attempt",
                    extra={
                        "source_id": self.source_config.source_id,
                        "url": str(response.request.url),
                        "status": response.status_code,
                        "latency_ms": latency_ms,
                        "attempt": attempt.retry_state.attempt_number,
                    },
                )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise TransientHTTPError(response)
                response.raise_for_status()
                return response

        raise AssertionError("unreachable: AsyncRetrying always returns or raises")

    async def fetch_pages(self) -> AsyncIterator[PageResult]:
        request: RequestSpec | None = self._build_first_request()
        page_number = 1

        owns_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient()
        try:
            while request is not None:
                if page_number > self.max_pages:
                    logger.error(
                        "max_pages_exceeded",
                        extra={
                            "source_id": self.source_config.source_id,
                            "max_pages": self.max_pages,
                        },
                    )
                    yield PageResult(
                        page_number=page_number,
                        error=f"exceeded max_pages safety cap ({self.max_pages}); aborting run",
                    )
                    return

                await self.rate_limiter.acquire()
                try:
                    response = await self._send_with_retries(client, request)
                except Exception as exc:
                    logger.error(
                        "page_fetch_exhausted_retries",
                        extra={
                            "source_id": self.source_config.source_id,
                            "page_number": page_number,
                            "error": str(exc),
                        },
                    )
                    yield PageResult(page_number=page_number, error=str(exc))
                    return

                records = self.pagination.extract_records(response)
                yield PageResult(page_number=page_number, records=records)
                request = self.pagination.next_request(request, response)
                page_number += 1
        finally:
            if owns_client:
                await client.aclose()
