"""IngestionJob orchestration tests: real Postgres for job_runs/raw_records,
respx-mocked HTTP for the source itself (no real network in unit tests).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from app.config.schema import SourceConfig
from app.db.models import JobRun
from app.jobs.ingestion_job import IngestionJob
from app.sinks.database_sink import DatabaseSink


def _source_config(**overrides) -> SourceConfig:
    data = {
        "source_id": "job_test_source",
        "base_url": "https://example.com/api",
        "endpoint": {"path": "/things"},
        "auth": {"type": "none"},
        "pagination": {
            "type": "next_url_in_body",
            "config": {"next_url_json_path": "info.next", "records_json_path": "results"},
        },
        "response": {"record_id_field": "id"},
        "retry": {"max_attempts": 2, "backoff_base_seconds": 0.01, "backoff_max_seconds": 0.02},
        "rate_limit": {"requests_per_second": 1000, "burst": 1000},
        "timeout_seconds": 5,
    }
    data.update(overrides)
    return SourceConfig.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_run_writes_records_and_marks_success(session_factory):
    respx.get("https://example.com/api/things").mock(
        return_value=httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 1}, {"id": 2}]})
    )

    source_config = _source_config(source_id="job_success_source")
    sink = DatabaseSink(session_factory)
    job = IngestionJob(source_config=source_config, sinks=[sink], session_factory=session_factory)

    run_id = await job.run()

    async with session_factory() as session:
        run = await session.get(JobRun, run_id)
        assert run.status == "success"
        assert run.pages_fetched == 1
        assert run.records_written == 2
        assert run.records_failed == 0
        assert run.finished_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_run_marks_partial_success_on_page_failure(session_factory):
    respx.get("https://example.com/api/things").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "info": {"next": "https://example.com/api/things?page=2"},
                    "results": [{"id": 1}],
                },
            ),
            httpx.Response(500, json={}),
            httpx.Response(500, json={}),
        ]
    )

    source_config = _source_config(source_id="job_partial_source")
    sink = DatabaseSink(session_factory)
    job = IngestionJob(source_config=source_config, sinks=[sink], session_factory=session_factory)

    run_id = await job.run()

    async with session_factory() as session:
        run = await session.get(JobRun, run_id)
        assert run.status == "partial_success"
        assert run.pages_fetched == 1
        assert run.records_written == 1
        assert run.records_failed == 1
        assert run.error_summary is not None


@pytest.mark.asyncio
@respx.mock
async def test_run_is_idempotent_per_trigger_key(session_factory):
    route = respx.get("https://example.com/api/things").mock(
        return_value=httpx.Response(200, json={"info": {"next": None}, "results": [{"id": 1}]})
    )

    # Unique per test invocation: the DB fixture deliberately doesn't wipe
    # tables between runs (see conftest.py), so a fixed trigger_key would
    # collide with a row from a previous run and short-circuit before the
    # route is ever called, rather than actually exercising idempotency.
    trigger_key = f"daily-{uuid.uuid4()}"
    source_config = _source_config(source_id="job_idempotent_source")
    sink = DatabaseSink(session_factory)

    job1 = IngestionJob(
        source_config=source_config, sinks=[sink], session_factory=session_factory, trigger_key=trigger_key
    )
    run_id_1 = await job1.run()

    job2 = IngestionJob(
        source_config=source_config, sinks=[sink], session_factory=session_factory, trigger_key=trigger_key
    )
    run_id_2 = await job2.run()

    assert run_id_1 == run_id_2
    assert route.call_count == 1
