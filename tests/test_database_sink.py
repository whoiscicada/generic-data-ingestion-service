"""DatabaseSink tests against a real Postgres instance (CLAUDE.md D-1: no
SQLite stand-in -- the upsert path under test must be the one that ships).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import RawRecord
from app.sinks.database_sink import DatabaseSink


@pytest.mark.asyncio
async def test_write_inserts_new_records(session_factory):
    sink = DatabaseSink(session_factory)
    run_id = str(uuid.uuid4())
    result = await sink.write(
        records=[{"id": 1, "name": "Rick"}, {"id": 2, "name": "Morty"}],
        source_id="test_source",
        run_id=run_id,
        record_id_field="id",
    )
    assert result.written == 2
    assert result.failed == 0

    async with session_factory() as session:
        rows = (
            (await session.execute(select(RawRecord).where(RawRecord.source_id == "test_source")))
            .scalars()
            .all()
        )
        assert {row.record_id for row in rows} == {"1", "2"}


@pytest.mark.asyncio
async def test_write_upserts_on_conflict_source_and_record_id(session_factory):
    sink = DatabaseSink(session_factory)
    run_id_1 = str(uuid.uuid4())
    run_id_2 = str(uuid.uuid4())

    await sink.write(
        records=[{"id": 42, "name": "original"}],
        source_id="upsert_source",
        run_id=run_id_1,
        record_id_field="id",
    )
    result = await sink.write(
        records=[{"id": 42, "name": "updated"}],
        source_id="upsert_source",
        run_id=run_id_2,
        record_id_field="id",
    )
    assert result.written == 1

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RawRecord).where(RawRecord.source_id == "upsert_source", RawRecord.record_id == "42")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].raw_payload["name"] == "updated"
        assert rows[0].run_id == uuid.UUID(run_id_2)


@pytest.mark.asyncio
async def test_write_isolates_records_missing_id_field(session_factory):
    sink = DatabaseSink(session_factory)
    result = await sink.write(
        records=[{"id": 1, "name": "ok"}, {"name": "no id field"}],
        source_id="drift_source",
        run_id=str(uuid.uuid4()),
        record_id_field="id",
    )
    assert result.written == 1
    assert result.failed == 1
    assert "no id field" not in str(result.errors)
    assert result.errors and "missing id field" in result.errors[0]
