"""IngestionJob: drives one end-to-end run.

Creates a job_runs row, streams Fetcher -> Sink(s) page by page, and updates
the row incrementally so a run's status is observable mid-flight via
GET /runs/{run_id}. A page-level fetch or write failure is isolated (logged,
counted) rather than aborting the whole run; the run ends in
``partial_success`` if any page failed, ``success`` if none did, or
``failed`` if not even the first page could be fetched.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.registry import build_auth_strategy
from app.config.schema import SourceConfig
from app.db.models import JobRun
from app.fetch.fetcher import Fetcher
from app.pagination.registry import build_pagination_strategy
from app.sinks.base import Sink

logger = logging.getLogger(__name__)


class IngestionJob:
    def __init__(
        self,
        source_config: SourceConfig,
        sinks: list[Sink],
        session_factory: async_sessionmaker,
        trigger_key: str | None = None,
    ):
        self.source_config = source_config
        self.sinks = sinks
        self.session_factory = session_factory
        self.trigger_key = trigger_key

    async def _create_run(self) -> uuid.UUID:
        async with self.session_factory() as session:
            run = JobRun(source_id=self.source_config.source_id, trigger_key=self.trigger_key)
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run.id

    async def _update_run(
        self,
        run_id: uuid.UUID,
        *,
        pages_fetched: int | None = None,
        records_written: int | None = None,
        records_failed: int | None = None,
        status: str | None = None,
        error_summary: str | None = None,
        finished: bool = False,
    ) -> None:
        async with self.session_factory() as session:
            run = await session.get(JobRun, run_id)
            if run is None:
                return
            if pages_fetched is not None:
                run.pages_fetched = pages_fetched
            if records_written is not None:
                run.records_written = records_written
            if records_failed is not None:
                run.records_failed = records_failed
            if status is not None:
                run.status = status
            if error_summary is not None:
                run.error_summary = error_summary
            if finished:
                run.finished_at = datetime.now(timezone.utc)
            await session.commit()

    async def run(self) -> uuid.UUID:
        if self.trigger_key is not None:
            existing = await self.find_by_trigger_key(
                self.session_factory, self.source_config.source_id, self.trigger_key
            )
            if existing is not None:
                logger.info(
                    "ingest_idempotent_hit",
                    extra={
                        "source_id": self.source_config.source_id,
                        "trigger_key": self.trigger_key,
                        "run_id": str(existing.id),
                    },
                )
                return existing.id

        run_id = await self._create_run()
        run_id_str = str(run_id)
        record_id_field = self.source_config.response.record_id_field

        auth = build_auth_strategy(self.source_config.auth)
        pagination = build_pagination_strategy(self.source_config.pagination)
        fetcher = Fetcher(source_config=self.source_config, auth=auth, pagination=pagination)

        pages_fetched = 0
        records_written = 0
        records_failed = 0
        error_messages: list[str] = []

        async for page in fetcher.fetch_pages():
            if not page.ok:
                records_failed += 1
                error_messages.append(f"page {page.page_number}: {page.error}")
                logger.error(
                    "page_isolated_as_failure",
                    extra={"source_id": self.source_config.source_id, "run_id": run_id_str, "page": page.page_number},
                )
                continue

            pages_fetched += 1
            for sink in self.sinks:
                try:
                    result = await sink.write(
                        page.records, self.source_config.source_id, run_id_str, record_id_field
                    )
                    records_written += result.written
                    records_failed += result.failed
                    error_messages.extend(result.errors)
                except Exception as exc:
                    records_failed += len(page.records)
                    error_messages.append(f"page {page.page_number} sink {type(sink).__name__}: {exc}")
                    logger.error(
                        "sink_write_failed",
                        extra={
                            "source_id": self.source_config.source_id,
                            "run_id": run_id_str,
                            "page": page.page_number,
                            "sink": type(sink).__name__,
                            "error": str(exc),
                        },
                    )

            await self._update_run(
                run_id,
                pages_fetched=pages_fetched,
                records_written=records_written,
                records_failed=records_failed,
            )

        if pages_fetched == 0 and error_messages:
            status = "failed"
        elif error_messages:
            status = "partial_success"
        else:
            status = "success"

        await self._update_run(
            run_id,
            pages_fetched=pages_fetched,
            records_written=records_written,
            records_failed=records_failed,
            status=status,
            error_summary="; ".join(error_messages[:20]) if error_messages else None,
            finished=True,
        )
        return run_id

    @staticmethod
    async def find_by_trigger_key(
        session_factory: async_sessionmaker, source_id: str, trigger_key: str
    ) -> JobRun | None:
        async with session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.source_id == source_id, JobRun.trigger_key == trigger_key)
            )
            return result.scalar_one_or_none()
