"""Minimal dotted-path JSON accessor.

Config fields like ``records_json_path: "info.next"`` only ever need to walk
plain dict keys (no array indexing, no wildcards) for the APIs this system
targets, so a tiny dotted-path walker is enough — no need for a full
JSONPath/jmespath dependency. ``""`` or ``"$"`` means "the document itself"
(used when a response body is a bare JSON array).
"""

from __future__ import annotations

from typing import Any


def get_json_path(data: Any, path: str) -> Any:
    if not path or path == "$":
        return data
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
