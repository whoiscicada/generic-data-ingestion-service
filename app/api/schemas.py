"""Request/response Pydantic models for the API layer (CLAUDE.md Section 3.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class IngestRequest(BaseModel):
    trigger_key: str | None = None


class IngestResponse(BaseModel):
    run_id: uuid.UUID
    source_id: str


class RunSummary(BaseModel):
    id: uuid.UUID
    source_id: str
    trigger_key: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages_fetched: int
    records_written: int
    records_failed: int
    error_summary: str | None

    model_config = {"from_attributes": True}


class SourceRegisteredResponse(BaseModel):
    source_id: str
    message: str
