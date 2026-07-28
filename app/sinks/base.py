"""Sink interface (CLAUDE.md Section 3.5).

The Fetcher/IngestionJob layer only ever calls ``write`` on whatever sinks a
source's config lists under ``destination.sinks``; it never branches on
which concrete sink it's talking to. Adding a new destination (e.g. S3) is
one new file implementing this ABC, registered in app/sinks/registry.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WriteResult:
    written: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class Sink(ABC):
    @abstractmethod
    async def write(
        self,
        records: list[dict[str, Any]],
        source_id: str,
        run_id: str,
        record_id_field: str,
    ) -> WriteResult:
        """Persist a batch of raw records for one page of one run."""
        raise NotImplementedError
