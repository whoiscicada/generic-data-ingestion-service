"""SQLAlchemy 2.0 models — Postgres only (CLAUDE.md D-1: no SQLite fallback).

``raw_records`` stores the raw JSON payload alongside a handful of
normalized columns so schema drift in a source's response shape doesn't
cause hard failures (CLAUDE.md Section 5). Idempotency is enforced by a
unique constraint on (source_id, record_id), upserted via Postgres
``INSERT ... ON CONFLICT DO UPDATE`` in app/sinks/database_sink.py.

``job_runs`` is the observability surface: one row per ingestion run,
updated incrementally as pages are processed so a run's status is visible
mid-flight via GET /runs/{run_id}.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trigger_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (UniqueConstraint("source_id", "trigger_key", name="uq_job_runs_source_trigger"),)


class RawRecord(Base):
    __tablename__ = "raw_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    record_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_runs.id"), nullable=True
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source_id", "record_id", name="uq_raw_records_source_record"),)
