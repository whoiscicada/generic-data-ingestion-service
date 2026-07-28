"""FastAPI app factory + startup wiring (CLAUDE.md Section 3.7).

Contains no source-specific logic: startup configures logging, creates the
Postgres schema if it doesn't exist yet, and loads every config under
configs/sources/ into an in-memory registry. Everything else is delegated
to app/api/routes.py and app/jobs/ingestion_job.py.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router
from app.config.loader import load_all_source_configs
from app.db.session import create_schema, get_session_factory
from app.logging_config import configure_logging

SOURCES_DIR = Path(__file__).resolve().parent.parent / "configs" / "sources"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await create_schema()
    app.state.session_factory = get_session_factory()
    app.state.sources = load_all_source_configs(SOURCES_DIR) if SOURCES_DIR.exists() else {}
    logger.info("startup_complete", extra={"loaded_sources": list(app.state.sources.keys())})
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Generic Data Ingestion Service", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
