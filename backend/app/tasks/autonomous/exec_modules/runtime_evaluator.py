"""Contract-driven runtime evaluator for selective post-quality verification."""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

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
from ._runtime_eval_helpers import (
    RuntimeEvaluationResult,
    build_result,
    format_list,
    make_screenshot_path,
    replace_localhost,
    resolve_api_url,
    resolve_runtime_url,
)
from .ah_events import emit_runtime_evaluator_result
from .design_critic import run_design_critic

_SLUG_RUNTIME_EXECUTION_EVALUATOR = "runtime-execution-evaluator"
_BROWSER_HEALTH_COMMAND = ("sf-browser", "health")
_BROWSER_ATTEMPTS = 3
_BROWSER_RETRY_DELAYS_SECONDS = (0.5, 1.0)


def _check_browser_health() -> tuple[bool, str]:
    result = subprocess.run(list(_BROWSER_HEALTH_COMMAND), capture_output=True, text=True, timeout=15, check=False)
    output = result.stdout.strip() or result.stderr.strip() or "sf-browser health returned no output"
    return result.returncode == 0, output


def _get_runtime_host() -> str:
    info = get_network_info()
    return str(info.get("host_ip") or "localhost")


def _resolve_frontend_base(project_id: str, host: str) -> str | None:
    project = get_project_config(project_id) or {}
    if frontend_port := project.get("frontend_port"):
        return f"http://{host}:{frontend_port}"
    base_url = project.get("base_url")
    if isinstance(base_url, str) and base_url:
        return replace_localhost(base_url.rstrip("/"), host)
    return None


def _resolve_api_base(project_id: str, host: str) -> str | None:
    project = get_project_config(project_id) or {}
    if backend_port := project.get("backend_port"):
        return f"http://{host}:{backend_port}/api"
    return None


def _make_screenshot_path(task_id: str, criterion_id: str) -> Path:
    return make_screenshot_path(task_id, criterion_id)


def _probe_frontend_target(page_url: str) -> dict[str, Any]:
    try:
        response = httpx.get(page_url, timeout=5.0, follow_redirects=True)
        return {
            "ok": response.status_code < 500,
            "status_code": response.status_code,
            "error": None,
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }


def _format_browser_failure(
    page_url: str,
    attempt: int,
    attempts: int,
    browser_health: str,
    probe: dict[str, Any],
    error: str | None,
) -> str:
    probe_summary = (
        f"direct GET {page_url} -> {probe['status_code']}"
        if probe.get("status_code") is not None
        else f"direct GET {page_url} failed: {probe.get('error') or 'unknown error'}"
    )
    browser_summary = error or "Screenshot failed"
    return (
        f"Browser check failed for resolved target {page_url} "
        f"(attempt {attempt}/{attempts}; {probe_summary}; browser health: {browser_health}; "
        f"browser result: {browser_summary})"
    )


def _capture_runtime_page(
    page_url: str,
    screenshot_path: Path,
    browser_health: str,
) -> tuple[bool, str | None, dict[str, Any]]:
    last_probe: dict[str, Any] = {"ok": False, "status_code": None, "error": "No probe executed"}
    last_error: str | None = None

    for attempt in range(1, _BROWSER_ATTEMPTS + 1):
        last_probe = _probe_frontend_target(page_url)
        success, error = _capture_page_screenshot_sync(page_url, screenshot_path)
        if success:
            return True, None, {
                "resolved_target": page_url,
                "attempt": attempt,
                "attempts": _BROWSER_ATTEMPTS,
                "probe": last_probe,
            }

        last_error = error or "Screenshot failed"
        should_retry = attempt < _BROWSER_ATTEMPTS and bool(last_probe.get("ok"))
        if should_retry:
            time.sleep(_BROWSER_RETRY_DELAYS_SECONDS[attempt - 1])
            continue

        return False, _format_browser_failure(page_url, attempt, _BROWSER_ATTEMPTS, browser_health, last_probe, last_error), {
            "resolved_target": page_url,
            "attempt": attempt,
            "attempts": _BROWSER_ATTEMPTS,
            "probe": last_probe,
            "browser_error": last_error,
        }

    return False, _format_browser_failure(page_url, _BROWSER_ATTEMPTS, _BROWSER_ATTEMPTS, browser_health, last_probe, last_error), {
        "resolved_target": page_url,
        "attempt": _BROWSER_ATTEMPTS,
        "attempts": _BROWSER_ATTEMPTS,
        "probe": last_probe,
        "browser_error": last_error,
    }


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
    return result if result is not None else (False, "Screenshot capture returned no result")


def _evaluate_user_flow_with_screenshot(
    project_id: str,
    task: dict[str, Any],
    page_url: str,
    screenshot_path: Path,
    flow: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    prompt = get_prompt_template(_SLUG_RUNTIME_EXECUTION_EVALUATOR).format_map({
        "task_title": str(task.get("title") or ""),
        "task_description": str(task.get("description") or ""),
        "page_url": page_url,
        "flow_title": str(flow.get("title") or "Flow"),
        "flow_setup": format_list(flow.get("setup") or []),
        "flow_actions": format_list(flow.get("actions") or []),
        "flow_expected_outcomes": format_list(flow.get("expected_outcomes") or []),
        "risk_notes": format_list(execution_contract.get("risk_notes") or []),
        "evidence_requirements": format_list(execution_contract.get("evidence_requirements") or []),
    })
    response_text, error = analyze_screenshot_with_prompt(project_id, screenshot_path, prompt)
    if error or response_text is None:
        return {"passed": False, "summary": error or "Runtime evaluator unavailable", "evidence": [str(screenshot_path)]}
    parsed = parse_json_response(response_text)
    evidence = [str(item).strip() for item in parsed.get("evidence", []) if str(item).strip()]
    evidence.append(str(screenshot_path))
    return {"passed": bool(parsed.get("passed")), "summary": str(parsed.get("summary") or response_text[:240]).strip(), "evidence": evidence}


def _run_api_check(check: dict[str, Any], api_base: str | None, host: str) -> dict[str, Any]:
    url = resolve_api_url(str(check.get("path") or ""), api_base, host)
    response = httpx.request(str(check.get("method") or "GET"), url, timeout=10.0)
    expected_status = int(check.get("expected_status") or check.get("status") or 200)
    body_expectations = [str(item) for item in check.get("body_expectations", [])]
    passed = response.status_code == expected_status and all(e in response.text for e in body_expectations)
    return {
        "criterion_id": check.get("criterion_id"), "category": "api",
        "status": "passed" if passed else "failed",
        "summary": f"{check.get('method', 'GET')} {url} -> {response.status_code}",
        "evidence": [response.text[:240]], "details": {"url": url, "expected_status": expected_status},
    }


def _process_user_flows(
    task_id: str, task: dict[str, Any], project_id: str,
    user_flows: list[dict[str, Any]], target_urls: list[Any],
    frontend_base: str | None, host: str, execution_contract: dict[str, Any], browser_health: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    criteria: list[dict[str, Any]] = []
    screenshots: list[str] = []
    for index, flow in enumerate(user_flows):
        target = str(flow.get("target_url") or (target_urls[min(index, len(target_urls) - 1)] if target_urls else ""))
        page_url = resolve_runtime_url(target, frontend_base, host)
        screenshot_path = _make_screenshot_path(task_id, str(flow.get("flow_id") or f"flow-{index + 1}"))
        success, error, capture_details = _capture_runtime_page(page_url, screenshot_path, browser_health)
        if not success:
            criteria.append({
                "criterion_id": flow.get("flow_id"),
                "category": "browser",
                "status": "failed",
                "summary": error or "Screenshot failed",
                "evidence": [page_url],
                "details": capture_details,
            })
            continue
        screenshots.append(str(screenshot_path))
        flow_result = _evaluate_user_flow_with_screenshot(project_id, task, page_url, screenshot_path, flow, execution_contract)
        criteria.append({
            "criterion_id": flow.get("flow_id"),
            "category": "browser",
            "status": "passed" if flow_result.get("passed") else "failed",
            "summary": flow_result.get("summary"),
            "evidence": flow_result.get("evidence") or [str(screenshot_path)],
            "details": {"url": page_url, **capture_details},
        })
    return criteria, screenshots


def _process_target_urls(
    task_id: str, target_urls: list[Any], frontend_base: str | None, host: str, browser_health: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    criteria: list[dict[str, Any]] = []
    screenshots: list[str] = []
    for index, target in enumerate(target_urls, start=1):
        page_url = resolve_runtime_url(str(target), frontend_base, host)
        screenshot_path = _make_screenshot_path(task_id, f"url-{index}")
        success, error, capture_details = _capture_runtime_page(page_url, screenshot_path, browser_health)
        if success:
            screenshots.append(str(screenshot_path))
        criteria.append({
            "criterion_id": f"url-{index}",
            "category": "browser",
            "status": "passed" if success else "failed",
            "summary": "Screenshot captured" if success else (error or "Screenshot failed"),
            "evidence": [str(screenshot_path)] if success else [page_url],
            "details": {"url": page_url, **capture_details},
        })
    return criteria, screenshots


def _collect_api_results(
    execution_contract: dict[str, Any], api_base: str | None, host: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    api_results: list[dict[str, Any]] = []
    criteria: list[dict[str, Any]] = []
    for check in execution_contract.get("api_checks") or []:
        r = _run_api_check(check, api_base, host)
        api_results.append(r)
        criteria.append(r)
    for check in execution_contract.get("negative_cases") or []:
        r = _run_api_check(check, api_base, host)
        r["category"] = "negative"
        api_results.append(r)
        criteria.append(r)
    return api_results, criteria


def run_runtime_evaluator(task_id: str, project_id: str) -> RuntimeEvaluationResult:
    """Run contract-driven runtime evaluation for a completed task."""
    task = task_store.get_task(task_id) or {}
    spirit = get_task_spirit(task_id) or {}
    decision = determine_task_harness(task, spirit, [])
    if not decision.run_runtime_evaluator:
        return RuntimeEvaluationResult(mode=decision.mode, passed=True, summary="Harness route skipped runtime evaluation")

    raw_context = spirit.get("context")
    execution_contract = normalize_execution_contract(
        (raw_context if isinstance(raw_context, dict) else {}).get("execution_contract"),
        default_mode=decision.mode,
    )
    if not execution_contract:
        result = RuntimeEvaluationResult(mode=decision.mode, passed=False, summary="Missing execution contract")
        emit_runtime_evaluator_result(task_id, result.to_event_payload())
        return result

    browser_ok, browser_detail = _check_browser_health()
    if not browser_ok:
        result = RuntimeEvaluationResult(mode=decision.mode, passed=False, summary=f"sf-browser health failed: {browser_detail}", criteria=[{"criterion_id": "browser-health", "category": "runtime", "status": "failed", "summary": browser_detail, "evidence": [browser_detail]}])
        emit_runtime_evaluator_result(task_id, result.to_event_payload())
        return result

    host = _get_runtime_host()
    frontend_base = _resolve_frontend_base(project_id, host)
    api_base = _resolve_api_base(project_id, host)
    target_urls = execution_contract.get("target_urls") or []
    user_flows = execution_contract.get("user_flows") or []

    if user_flows:
        criteria, screenshots = _process_user_flows(task_id, task, project_id, user_flows, target_urls, frontend_base, host, execution_contract, browser_detail)
    else:
        criteria, screenshots = _process_target_urls(task_id, target_urls, frontend_base, host, browser_detail)

    api_results, api_criteria = _collect_api_results(execution_contract, api_base, host)
    criteria.extend(api_criteria)

    design_result: dict[str, Any] | None = None
    if decision.run_design_critic and screenshots:
        page_url = resolve_runtime_url(str(target_urls[0]), frontend_base, host) if target_urls else screenshots[0]
        design_result = run_design_critic(project_id, page_url, Path(screenshots[0]), execution_contract)
        criteria.append({"criterion_id": "design-critic", "category": "design", "status": "passed" if design_result.get("passed") else "failed", "summary": design_result.get("summary"), "evidence": [screenshots[0]], "details": {"overall_score": design_result.get("overall_score")}})

    result = build_result(decision.mode, criteria, screenshots, api_results, design_result)
    emit_runtime_evaluator_result(task_id, result.to_event_payload())
    return result
