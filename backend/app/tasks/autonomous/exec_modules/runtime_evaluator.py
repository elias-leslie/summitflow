"""Contract-driven runtime evaluator for selective post-quality verification."""

from __future__ import annotations

import asyncio
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ....services.explorer.base import get_project_config
from ....services.explorer.index_generator import get_network_info
from ....services.mockup_generator.analysis.screenshot import capture_page_screenshot
from ....services.mockup_generator.analysis.vision import analyze_screenshot_with_prompt
from ....services.task_harness import determine_task_harness, normalize_execution_contract
from ....storage import tasks as task_store
from ....storage.task_spirit import get_task_spirit
from ._prompt_fetch import get_prompt_template
from ._prompt_json import parse_json_response
from .ah_events import emit_runtime_evaluator_result
from .design_critic import run_design_critic

_SLUG_RUNTIME_EXECUTION_EVALUATOR = "runtime-execution-evaluator"
_BROWSER_HEALTH_COMMAND = ("sf-browser", "health")
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


def _format_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _check_browser_health() -> tuple[bool, str]:
    result = subprocess.run(
        list(_BROWSER_HEALTH_COMMAND),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = result.stdout.strip() or result.stderr.strip() or "sf-browser health returned no output"
    return result.returncode == 0, output


def _get_runtime_host() -> str:
    info = get_network_info()
    return str(info.get("host_ip") or "localhost")


def _replace_localhost(url: str, host: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return url
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    suffix = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.scheme}://{host}{port}{path}{suffix}{fragment}"


def _resolve_frontend_base(project_id: str, host: str) -> str | None:
    project = get_project_config(project_id) or {}
    frontend_port = project.get("frontend_port")
    if frontend_port:
        return f"http://{host}:{frontend_port}"
    base_url = project.get("base_url")
    if isinstance(base_url, str) and base_url:
        return _replace_localhost(base_url.rstrip("/"), host)
    return None


def _resolve_api_base(project_id: str, host: str) -> str | None:
    project = get_project_config(project_id) or {}
    backend_port = project.get("backend_port")
    if backend_port:
        return f"http://{host}:{backend_port}/api"
    return None


def _resolve_runtime_url(target_url: str, frontend_base: str | None, host: str) -> str:
    if target_url.startswith("http://") or target_url.startswith("https://"):
        return _replace_localhost(target_url, host)
    if not frontend_base:
        return target_url
    return f"{frontend_base.rstrip('/')}/{target_url.lstrip('/')}"


def _resolve_api_url(path: str, api_base: str | None, host: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return _replace_localhost(path, host)
    if not api_base:
        return path
    return f"{api_base.rstrip('/')}/{path.lstrip('/')}"


def _make_screenshot_path(task_id: str, criterion_id: str) -> Path:
    return _SCREENSHOT_ROOT / task_id / f"{criterion_id}.png"


def _capture_page_screenshot_sync(page_url: str, screenshot_path: Path) -> tuple[bool, str | None]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(capture_page_screenshot(page_url, screenshot_path))

    result: tuple[bool, str | None] | None = None
    failure: BaseException | None = None

    def _runner() -> None:
        nonlocal result, failure
        try:
            result = asyncio.run(capture_page_screenshot(page_url, screenshot_path))
        except BaseException as exc:  # pragma: no cover - re-raised after join
            failure = exc

    thread = threading.Thread(target=_runner, name="runtime-evaluator-screenshot", daemon=True)
    thread.start()
    thread.join()
    if failure is not None:
        raise failure
    if result is None:
        return False, "Screenshot capture returned no result"
    return result


def _evaluate_user_flow_with_screenshot(
    project_id: str,
    task: dict[str, Any],
    page_url: str,
    screenshot_path: Path,
    flow: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    prompt = get_prompt_template(_SLUG_RUNTIME_EXECUTION_EVALUATOR).format_map(
        {
            "task_title": str(task.get("title") or ""),
            "task_description": str(task.get("description") or ""),
            "page_url": page_url,
            "flow_title": str(flow.get("title") or "Flow"),
            "flow_setup": _format_list(flow.get("setup") or []),
            "flow_actions": _format_list(flow.get("actions") or []),
            "flow_expected_outcomes": _format_list(flow.get("expected_outcomes") or []),
            "risk_notes": _format_list(execution_contract.get("risk_notes") or []),
            "evidence_requirements": _format_list(execution_contract.get("evidence_requirements") or []),
        }
    )
    response_text, error = analyze_screenshot_with_prompt(project_id, screenshot_path, prompt)
    if error or response_text is None:
        return {
            "passed": False,
            "summary": error or "Runtime evaluator unavailable",
            "evidence": [str(screenshot_path)],
        }
    parsed = parse_json_response(response_text)
    evidence = [
        str(item).strip()
        for item in parsed.get("evidence", [])
        if str(item).strip()
    ]
    evidence.append(str(screenshot_path))
    return {
        "passed": bool(parsed.get("passed")),
        "summary": str(parsed.get("summary") or response_text[:240]).strip(),
        "evidence": evidence,
    }


def _run_api_check(
    check: dict[str, Any],
    api_base: str | None,
    host: str,
) -> dict[str, Any]:
    url = _resolve_api_url(str(check.get("path") or ""), api_base, host)
    response = httpx.request(
        str(check.get("method") or "GET"),
        url,
        timeout=10.0,
    )
    expected_status = int(check.get("expected_status") or check.get("status") or 200)
    body_expectations = [str(item) for item in check.get("body_expectations", [])]
    response_text = response.text
    status_ok = response.status_code == expected_status
    body_ok = all(expectation in response_text for expectation in body_expectations)
    passed = status_ok and body_ok
    return {
        "criterion_id": check.get("criterion_id"),
        "category": "api",
        "status": "passed" if passed else "failed",
        "summary": f"{check.get('method', 'GET')} {url} -> {response.status_code}",
        "evidence": [response_text[:240]],
        "details": {"url": url, "expected_status": expected_status},
    }


def _build_result(
    decision_mode: str,
    criteria: list[dict[str, Any]],
    screenshots: list[str],
    api_results: list[dict[str, Any]],
    design_result: dict[str, Any] | None,
) -> RuntimeEvaluationResult:
    passed = all(criterion.get("status") == "passed" for criterion in criteria)
    first_failure = next((criterion for criterion in criteria if criterion.get("status") != "passed"), None)
    summary = (
        str(first_failure.get("summary"))
        if first_failure
        else f"Runtime evaluation passed ({len(criteria)}/{len(criteria)})"
    )
    return RuntimeEvaluationResult(
        mode=decision_mode,
        passed=passed,
        summary=summary,
        criteria=criteria,
        screenshots=screenshots,
        api_results=api_results,
        design_result=design_result,
    )


def run_runtime_evaluator(task_id: str, project_id: str) -> RuntimeEvaluationResult:
    """Run contract-driven runtime evaluation for a completed task."""
    task = task_store.get_task(task_id) or {}
    spirit = get_task_spirit(task_id) or {}
    decision = determine_task_harness(task, spirit, [])
    if not decision.run_runtime_evaluator:
        return RuntimeEvaluationResult(
            mode=decision.mode,
            passed=True,
            summary="Harness route skipped runtime evaluation",
        )

    raw_context = spirit.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    execution_contract = normalize_execution_contract(
        context.get("execution_contract"),
        default_mode=decision.mode,
    )
    if not execution_contract:
        result = RuntimeEvaluationResult(
            mode=decision.mode,
            passed=False,
            summary="Missing execution contract",
        )
        emit_runtime_evaluator_result(task_id, result.to_event_payload())
        return result

    browser_ok, browser_detail = _check_browser_health()
    if not browser_ok:
        result = RuntimeEvaluationResult(
            mode=decision.mode,
            passed=False,
            summary=f"sf-browser health failed: {browser_detail}",
            criteria=[
                {
                    "criterion_id": "browser-health",
                    "category": "runtime",
                    "status": "failed",
                    "summary": browser_detail,
                    "evidence": [browser_detail],
                }
            ],
        )
        emit_runtime_evaluator_result(task_id, result.to_event_payload())
        return result

    host = _get_runtime_host()
    frontend_base = _resolve_frontend_base(project_id, host)
    api_base = _resolve_api_base(project_id, host)
    criteria: list[dict[str, Any]] = []
    screenshots: list[str] = []
    api_results: list[dict[str, Any]] = []

    target_urls = execution_contract.get("target_urls") or []
    user_flows = execution_contract.get("user_flows") or []

    if user_flows:
        for index, flow in enumerate(user_flows):
            target = str(flow.get("target_url") or target_urls[min(index, len(target_urls) - 1)] if target_urls else "")
            page_url = _resolve_runtime_url(target, frontend_base, host)
            screenshot_path = _make_screenshot_path(task_id, str(flow.get("flow_id") or f"flow-{index + 1}"))
            success, error = _capture_page_screenshot_sync(page_url, screenshot_path)
            if not success:
                criteria.append(
                    {
                        "criterion_id": flow.get("flow_id"),
                        "category": "browser",
                        "status": "failed",
                        "summary": error or "Screenshot failed",
                        "evidence": [page_url],
                    }
                )
                continue
            screenshots.append(str(screenshot_path))
            flow_result = _evaluate_user_flow_with_screenshot(
                project_id,
                task,
                page_url,
                screenshot_path,
                flow,
                execution_contract,
            )
            criteria.append(
                {
                    "criterion_id": flow.get("flow_id"),
                    "category": "browser",
                    "status": "passed" if flow_result.get("passed") else "failed",
                    "summary": flow_result.get("summary"),
                    "evidence": flow_result.get("evidence") or [str(screenshot_path)],
                    "details": {"url": page_url},
                }
            )
    else:
        for index, target in enumerate(target_urls, start=1):
            page_url = _resolve_runtime_url(str(target), frontend_base, host)
            screenshot_path = _make_screenshot_path(task_id, f"url-{index}")
            success, error = _capture_page_screenshot_sync(page_url, screenshot_path)
            if success:
                screenshots.append(str(screenshot_path))
            criteria.append(
                {
                    "criterion_id": f"url-{index}",
                    "category": "browser",
                    "status": "passed" if success else "failed",
                    "summary": "Screenshot captured" if success else (error or "Screenshot failed"),
                    "evidence": [str(screenshot_path)] if success else [page_url],
                    "details": {"url": page_url},
                }
            )

    for check in execution_contract.get("api_checks") or []:
        result = _run_api_check(check, api_base, host)
        api_results.append(result)
        criteria.append(result)
    for check in execution_contract.get("negative_cases") or []:
        result = _run_api_check(check, api_base, host)
        result["category"] = "negative"
        api_results.append(result)
        criteria.append(result)

    design_result: dict[str, Any] | None = None
    if decision.run_design_critic and screenshots:
        page_url = _resolve_runtime_url(str(target_urls[0]), frontend_base, host) if target_urls else screenshots[0]
        design_result = run_design_critic(project_id, page_url, Path(screenshots[0]), execution_contract)
        criteria.append(
            {
                "criterion_id": "design-critic",
                "category": "design",
                "status": "passed" if design_result.get("passed") else "failed",
                "summary": design_result.get("summary"),
                "evidence": [screenshots[0]],
                "details": {"overall_score": design_result.get("overall_score")},
            }
        )

    result = _build_result(decision.mode, criteria, screenshots, api_results, design_result)
    emit_runtime_evaluator_result(task_id, result.to_event_payload())
    return result
