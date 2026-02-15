"""Issue ID computation for stuck detection."""

from __future__ import annotations

import hashlib
import re


def compute_issue_id(error: str) -> str:
    """Normalize error to stable ID for stuck detection."""
    normalized = re.sub(r":\d+:", ":N:", error)
    normalized = re.sub(r"/home/\w+/", "/HOME/", normalized)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()[:8]
