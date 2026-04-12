"""Stable task-version signature for autonomous planning dedupe."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def build_task_planning_signature(task: Mapping[str, Any] | None) -> str | None:
    """Return a stable hash for the task fields that should trigger replanning."""
    if not isinstance(task, Mapping):
        return None

    payload = {
        "title": str(task.get("title") or "").strip(),
        "description": str(task.get("description") or "").strip(),
        "task_type": str(task.get("task_type") or "").strip(),
        "complexity": str(task.get("complexity") or "").strip(),
        "labels": sorted(
            str(label).strip()
            for label in (task.get("labels") or [])
            if str(label).strip()
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
