"""Pure helpers for the contract-driven runtime evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SCREENSHOT_ROOT = Path("/tmp/summitflow-runtime-evaluator")


@dataclass
class RuntimeEvaluationResult:
    """Structured runtime-evaluation output."""

    mode: str
    passed: bool
    summary: str
    criteria: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    api_results: list[dict[str, Any]] = field(default_factory=list)
    design_result: dict[str, Any] | None = None

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "passed": self.passed,
            "summary": self.summary,
            "criteria": self.criteria,
            "screenshots": self.screenshots,
            "api_results": self.api_results,
            "design_result": self.design_result,
        }


def format_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def replace_localhost(url: str, host: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return url
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    suffix = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.scheme}://{host}{port}{path}{suffix}{fragment}"


def resolve_runtime_url(target_url: str, frontend_base: str | None, host: str) -> str:
    if target_url.startswith("http://") or target_url.startswith("https://"):
        return replace_localhost(target_url, host)
    if not frontend_base:
        return target_url
    return f"{frontend_base.rstrip('/')}/{target_url.lstrip('/')}"


def resolve_api_url(path: str, api_base: str | None, host: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return replace_localhost(path, host)
    if not api_base:
        return path
    return f"{api_base.rstrip('/')}/{path.lstrip('/')}"


def make_screenshot_path(task_id: str, criterion_id: str) -> Path:
    return _SCREENSHOT_ROOT / task_id / f"{criterion_id}.png"


def build_result(
    decision_mode: str,
    criteria: list[dict[str, Any]],
    screenshots: list[str],
    api_results: list[dict[str, Any]],
    design_result: dict[str, Any] | None,
) -> RuntimeEvaluationResult:
    passed = all(c.get("status") == "passed" for c in criteria)
    first_failure = next((c for c in criteria if c.get("status") != "passed"), None)
    summary = (
        str(first_failure.get("summary"))
        if first_failure
        else f"Runtime evaluation passed ({len(criteria)}/{len(criteria)})"
    )
    return RuntimeEvaluationResult(
        mode=decision_mode, passed=passed, summary=summary,
        criteria=criteria, screenshots=screenshots, api_results=api_results, design_result=design_result,
    )
