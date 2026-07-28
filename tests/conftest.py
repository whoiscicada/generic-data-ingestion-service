"""Shared fixtures for DB-backed tests.

Per CLAUDE.md D-1, there is no SQLite fallback: these fixtures talk to a
real Postgres instance via DATABASE_URL (the same env var docker-compose
sets for the app container). Run docker-compose's `db` service (or point
DATABASE_URL at any reachable Postgres) before running tests in this file.
"""

from __future__ import annotations

import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base


@pytest_asyncio.fixture
async def session_factory():
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://ingestion:ingestion@localhost:5432/ingestion"),
    )
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
