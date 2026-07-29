"""Postgres sink: upsert idempotency via ON CONFLICT DO UPDATE.

A record missing its configured id field is a schema-drift symptom, not a
hard failure: it's logged as a warning and counted in WriteResult.failed,
while the rest of the batch still gets written.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import RawRecord
from app.sinks.base import Sink, WriteResult

logger = logging.getLogger(__name__)


class DatabaseSink(Sink):
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def write(
        self,
        records: list[dict[str, Any]],
        source_id: str,
        run_id: str,
        record_id_field: str,
    ) -> WriteResult:
        rows: list[dict[str, Any]] = []
        failed = 0
        errors: list[str] = []

        for record in records:
            record_id = record.get(record_id_field)
            if record_id is None:
                failed += 1
                message = f"record missing id field {record_id_field!r}; skipped"
                errors.append(message)
                logger.warning(
                    "record_missing_id_field",
                    extra={"source_id": source_id, "run_id": run_id, "record_id_field": record_id_field},
                )
                continue
            rows.append(
                {
                    "source_id": source_id,
                    "record_id": str(record_id),
                    "run_id": run_id,
                    "raw_payload": record,
                }
            )

        if not rows:
            return WriteResult(written=0, failed=failed, errors=errors)

        stmt = pg_insert(RawRecord).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_id", "record_id"],
            set_={
                "raw_payload": stmt.excluded.raw_payload,
                "run_id": stmt.excluded.run_id,
                "last_seen_at": func.now(),
            },
        )

        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.commit()

        return WriteResult(written=len(rows), failed=failed, errors=errors)
