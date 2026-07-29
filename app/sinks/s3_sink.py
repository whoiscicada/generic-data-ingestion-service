"""Interface-only S3 sink stub.

Its only purpose is to prove destination pluggability is real: it implements
the same Sink ABC as DatabaseSink, and a source config can list it under
``destination.sinks`` without any change to the Fetcher or IngestionJob. It
deliberately does not touch a real S3/MinIO endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from app.sinks.base import Sink, WriteResult

logger = logging.getLogger(__name__)


class S3Sink(Sink):
    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket = bucket
        self.prefix = prefix

    async def write(
        self,
        records: list[dict[str, Any]],
        source_id: str,
        run_id: str,
        record_id_field: str,
    ) -> WriteResult:
        logger.info(
            "s3_sink_stub_write",
            extra={
                "source_id": source_id,
                "run_id": run_id,
                "record_count": len(records),
                "bucket": self.bucket,
            },
        )
        raise NotImplementedError(
            "S3Sink is an interface-only stub; implement against a real "
            "S3/MinIO client to make it functional."
        )
