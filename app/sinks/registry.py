"""destination.sinks -> Sink instance builder.

Mirrors app/auth/registry.py and app/pagination/registry.py: one entry per
sink type, plus one new file in this package, to add a destination.
"""

from __future__ import annotations

from app.config.schema import DestinationConfig, SinkType
from app.db.session import get_session_factory
from app.sinks.base import Sink
from app.sinks.database_sink import DatabaseSink
from app.sinks.s3_sink import S3Sink


def build_sinks(config: DestinationConfig) -> list[Sink]:
    sinks: list[Sink] = []
    for sink_type in config.sinks:
        if sink_type == SinkType.DATABASE:
            sinks.append(DatabaseSink(get_session_factory()))
        elif sink_type == SinkType.S3:
            sinks.append(S3Sink(bucket="stub-bucket"))
        else:
            raise ValueError(f"no Sink registered for sink type {sink_type!r}")
    return sinks
