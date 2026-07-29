"""Structured (JSON) logging setup.

Cheap, dependency-light way to satisfy the "observability" concern
without a full metrics/tracing stack: every fetch
attempt logs source_id, url, status, latency_ms, and attempt count as
structured fields, so an evaluator can grep/jq the container logs to see
exactly what happened during a run.
"""

from __future__ import annotations

import logging
import os
import sys

from pythonjsonlogger import jsonlogger


def configure_logging(level: str | None = None) -> None:
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)
