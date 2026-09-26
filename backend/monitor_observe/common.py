"""Shared limits and wire format for short lived, read-only diagnostic queries."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

SCHEMA = 1
DEFAULT_BYTES = 4096
MAX_BYTES = 65536
MAX_LIMIT = 100


class ObserveQueryError(ValueError):
    """Invalid public diagnostic query."""


def limits(limit: int, max_bytes: int) -> tuple[int, int]:
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ObserveQueryError("limit must be 1..100")
    if type(max_bytes) is not int or not 256 <= max_bytes <= MAX_BYTES:
        raise ObserveQueryError("max_bytes must be 256..65536")
    return limit, max_bytes


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def base(kind: str, requested: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": SCHEMA, "generated_at": utc_now(), "requested": {"kind": kind, **(requested or {})},
            "coverage": {}, "items": [], "next_cursor": None, "truncated": False, "errors": []}


def error(code: str, source: str, message: str | None = None) -> dict[str, str]:
    result = {"code": code, "source": source}
    if message:
        result["message"] = message[:160]
    return result


def availability(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return "unsupported"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "error"


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def pack(payload: dict[str, Any], candidates: list[dict[str, Any]], *, limit: int,
         max_bytes: int, next_cursors: list[str | None] | None = None,
         more: bool = False) -> dict[str, Any]:
    """Bound item count and serialized bytes; never emit malformed JSON."""
    limits(limit, max_bytes)
    for index, item in enumerate(candidates[:limit]):
        trial = {**payload, "items": [*payload["items"], item], "truncated": True,
                 "next_cursor": next_cursors[index] if next_cursors else None}
        if _size(trial) > max_bytes:
            more = True
            break
        payload["items"].append(item)
    more = more or len(payload["items"]) < len(candidates)
    payload["truncated"] = more
    if more and payload["items"] and next_cursors:
        payload["next_cursor"] = next_cursors[len(payload["items"]) - 1]
    if more and not payload["items"]:
        payload["errors"].append(error("output_budget", "response", "first item exceeds max_bytes"))
    if _size(payload) > max_bytes:
        payload["requested"] = {"kind": payload["requested"].get("kind")}
        payload["coverage"] = {}
        payload["errors"] = [error("output_budget", "response")]
        payload["next_cursor"] = None
    if _size(payload) > max_bytes:
        raise ObserveQueryError("response metadata exceeds max_bytes")
    return payload


def item(source: str, provider: str, availability_code: str, data: Any,
         *, unit: str | None = None, measured_at: str | None = None) -> dict[str, Any]:
    return {"sampled_at": measured_at or utc_now(), "freshness": "ok", "source": source,
            "provider": provider, "mode": "on_demand", "unit": unit,
            "availability": availability_code, "value": data}


def bounded_text(value: str, cap: int = 160) -> str:
    # Do not carry control characters from host state into terminal/JSON clients.
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:cap]
