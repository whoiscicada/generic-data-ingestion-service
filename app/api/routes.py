"""FastAPI routes.

Source configs live in ``request.app.state.sources`` (a dict keyed by
source_id), seeded at startup from configs/sources/ and extendable at
runtime via POST /sources -- proving a new source can be added without an
application redeploy, only a config.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select

from app.api.schemas import IngestRequest, IngestResponse, RunSummary, SourceRegisteredResponse
from app.config.schema import SourceConfig
from app.db.models import JobRun
from app.jobs.ingestion_job import IngestionJob
from app.sinks.registry import build_sinks

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/sources", response_model=SourceRegisteredResponse, status_code=201)
async def register_source(request: Request, config: dict) -> SourceRegisteredResponse:
    try:
        source_config = SourceConfig.model_validate(config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    request.app.state.sources[source_config.source_id] = source_config
    return SourceRegisteredResponse(
        source_id=source_config.source_id,
        message="source registered for this process; not persisted to disk",
    )


@router.post("/ingest/{source_id}", response_model=IngestResponse)
async def trigger_ingest(source_id: str, request: Request, body: IngestRequest | None = None) -> IngestResponse:
    sources: dict[str, SourceConfig] = request.app.state.sources
    source_config = sources.get(source_id)
    if source_config is None:
        raise HTTPException(status_code=404, detail=f"unknown source_id {source_id!r}")

    trigger_key = body.trigger_key if body else None
    sinks = build_sinks(source_config.destination)
    job = IngestionJob(
        source_config=source_config,
        sinks=sinks,
        session_factory=request.app.state.session_factory,
        trigger_key=trigger_key,
    )
    run_id = await job.run()
    return IngestResponse(run_id=run_id, source_id=source_id)


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: uuid.UUID, request: Request) -> RunSummary:
    async with request.app.state.session_factory() as session:
        run = await session.get(JobRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown run_id {run_id}")
        return RunSummary.model_validate(run)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(request: Request, limit: int = 20) -> list[RunSummary]:
    async with request.app.state.session_factory() as session:
        result = await session.execute(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit))
        return [RunSummary.model_validate(run) for run in result.scalars().all()]
