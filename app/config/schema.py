"""Pydantic schema for the source-config DSL described in CLAUDE.md Section 3.1.

A source is fully described by one of these documents. The engine (auth +
pagination strategies, Fetcher, Sink) never branches on `source_id` — it only
branches on the `type` discriminators below, each of which maps to a small
strategy class via a registry. Adding a source is adding a new YAML file that
validates against this schema, not new code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"


class AuthType(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"


class PaginationType(str, Enum):
    NEXT_URL_IN_BODY = "next_url_in_body"
    LINK_HEADER = "link_header"
    OFFSET_LIMIT = "offset_limit"
    PAGE_NUMBER = "page_number"


class SinkType(str, Enum):
    DATABASE = "database"
    S3 = "s3"


class EndpointConfig(BaseModel):
    path: str
    method: HttpMethod = HttpMethod.GET
    static_params: dict[str, Any] = Field(default_factory=dict)


class AuthConfig(BaseModel):
    type: AuthType = AuthType.NONE
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "AuthConfig":
        required_by_type: dict[AuthType, list[str]] = {
            AuthType.API_KEY: ["key_name", "value", "location"],
            AuthType.BEARER_TOKEN: ["token"],
        }
        required = required_by_type.get(self.type, [])
        missing = [f for f in required if f not in self.config]
        if missing:
            raise ValueError(
                f"auth.config missing required field(s) {missing} for auth.type={self.type.value!r}"
            )
        if self.type == AuthType.API_KEY and self.config.get("location") not in ("header", "query"):
            raise ValueError("auth.config.location must be 'header' or 'query' for api_key auth")
        return self


class PaginationConfig(BaseModel):
    type: PaginationType
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "PaginationConfig":
        required_by_type: dict[PaginationType, list[str]] = {
            PaginationType.NEXT_URL_IN_BODY: ["next_url_json_path", "records_json_path"],
            PaginationType.LINK_HEADER: ["records_json_path"],
            PaginationType.OFFSET_LIMIT: ["records_json_path", "limit"],
            PaginationType.PAGE_NUMBER: ["records_json_path"],
        }
        required = required_by_type.get(self.type, [])
        missing = [f for f in required if f not in self.config]
        if missing:
            raise ValueError(
                f"pagination.config missing required field(s) {missing} for pagination.type={self.type.value!r}"
            )
        return self


class ResponseConfig(BaseModel):
    record_id_field: str
    raw_storage: bool = True


class RateLimitConfig(BaseModel):
    requests_per_second: float = Field(gt=0, default=2.0)
    burst: int = Field(gt=0, default=4)


class RetryConfig(BaseModel):
    max_attempts: int = Field(gt=0, default=5)
    backoff_base_seconds: float = Field(gt=0, default=1.0)
    backoff_max_seconds: float = Field(gt=0, default=30.0)

    @model_validator(mode="after")
    def _validate_backoff_bounds(self) -> "RetryConfig":
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError("retry.backoff_max_seconds must be >= retry.backoff_base_seconds")
        return self


class DestinationConfig(BaseModel):
    sinks: list[SinkType] = Field(default_factory=lambda: [SinkType.DATABASE])

    @field_validator("sinks")
    @classmethod
    def _non_empty(cls, v: list[SinkType]) -> list[SinkType]:
        if not v:
            raise ValueError("destination.sinks must list at least one sink")
        return v


class SourceConfig(BaseModel):
    source_id: str
    base_url: str
    endpoint: EndpointConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    pagination: PaginationConfig
    response: ResponseConfig
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    timeout_seconds: float = Field(gt=0, default=15.0)
    destination: DestinationConfig = Field(default_factory=DestinationConfig)

    @field_validator("base_url")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("source_id")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "_-" for c in v):
            raise ValueError("source_id must be a non-empty string of letters, digits, '_' or '-'")
        return v
