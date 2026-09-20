from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.external_work import (
    ExternalWorkResult,
    capture_external_work_baseline,
    checkout_is_clean_for_external_work,
    verify_external_work,
)

ITEM_ID = "123e4567-e89b-12d3-a456-426614174000"
TASK_ID = "task-maintenance-1"
DIGEST = "a" * 64


def _task() -> dict[str, str]:
    return {
        "id": TASK_ID,
        "project_id": "agent-hub",
        "external_origin": "agent-hub-context-maintenance",
        "external_request_key": ITEM_ID,
        "external_payload_digest": DIGEST,
    }


def _response(**overrides: object) -> dict[str, object]:
    return {
        "verified": True,
        "reason": "canonical receipt verified",
        "item_id": ITEM_ID,
        "item_version": 12,
        "task_id": TASK_ID,
        "external_request_key": ITEM_ID,
        "external_payload_digest": DIGEST,
        "state": "resolved",
        "change_id": "123e4567-e89b-12d3-a456-426614174001",
        "event_id": "123e4567-e89b-12d3-a456-426614174002",
        "verified_sources": [{"source_type": "prompt", "source_id": "prompt-1", "revision": "sha256:1"}],
        "payload_hash": "b" * 64,
        "verification": "canonical_generation",
        **overrides,
    }


@patch("app.tasks.autonomous.exec_modules.external_work.httpx.post")
def test_verify_external_work_requires_exact_identity_and_returns_receipt(post: MagicMock, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-secret")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _response()
    post.return_value = response

    result = verify_external_work(_task())

    assert result.passed
    assert result.receipt is not None
    assert result.receipt["item_version"] == 12
    post.assert_called_once()
    assert post.call_args.kwargs["json"]["action"] == "verify_work"
    assert post.call_args.kwargs["json"]["item_id"] == ITEM_ID
    assert post.call_args.kwargs["json"]["generation"] == 0
    assert post.call_args.kwargs["headers"]["X-Agent-Hub-Internal"] == "test-secret"


@patch("app.tasks.autonomous.exec_modules.external_work.httpx.post")
def test_verify_external_work_rejects_unverified_or_malformed_response(post: MagicMock, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-secret")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"verified": True, "item_id": ITEM_ID}
    post.return_value = response

    result = verify_external_work(_task())

    assert not result.passed
    assert result.reason == "canonical_verification_marker_missing"


@patch("app.tasks.autonomous.exec_modules.external_work.httpx.post")
def test_verify_external_work_rejects_empty_or_malformed_source_receipt(post: MagicMock, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-secret")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _response(verified_sources=[])
    post.return_value = response
    assert verify_external_work(_task()).reason == "canonical_receipt_sources_missing"

    response.json.return_value = _response(
        verified_sources=[{"source_type": "prompt", "source_id": "prompt-1"}],
    )
    assert verify_external_work(_task()).reason == "canonical_receipt_sources_missing"


@patch("app.tasks.autonomous.exec_modules.external_work.httpx.post")
def test_verify_external_work_rejects_malformed_receipt_id_even_with_other_id(post: MagicMock, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-secret")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _response(change_id="not-a-uuid")
    post.return_value = response

    assert verify_external_work(_task()).reason == "canonical_receipt_change_or_event_malformed"


@patch("app.tasks.autonomous.exec_modules.external_work.httpx.post")
def test_verify_external_work_fails_closed_without_internal_secret(post: MagicMock, monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)

    result = verify_external_work(_task())

    assert result.reason == "agent_hub_internal_auth_unavailable"
    post.assert_not_called()


def test_checkout_is_clean_requires_task_checkpoint_baseline() -> None:
    task = _task()
    with patch(
        "app.tasks.autonomous.exec_modules.external_work.get_active_checkpoints",
        return_value=[SimpleNamespace(task_id=TASK_ID, base_commit="base-sha")],
    ), patch(
        "app.tasks.autonomous.exec_modules.external_work.subprocess.run",
        side_effect=[
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout=""),
        ],
    ):
        assert checkout_is_clean_for_external_work(task, "/tmp/project")


def test_checkout_is_not_clean_when_head_differs_from_checkpoint() -> None:
    task = _task()
    with patch(
        "app.tasks.autonomous.exec_modules.external_work.get_active_checkpoints",
        return_value=[SimpleNamespace(task_id=TASK_ID, base_commit="base-sha")],
    ), patch(
        "app.tasks.autonomous.exec_modules.external_work.subprocess.run",
        side_effect=[
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=1, stdout=""),
        ],
    ):
        assert not checkout_is_clean_for_external_work(task, "/tmp/project")


def test_checkout_is_not_clean_without_retained_baseline() -> None:
    task = _task()
    with patch(
        "app.tasks.autonomous.exec_modules.external_work.get_active_checkpoints",
        return_value=[],
    ), patch("app.storage.task_spirit.get_task_spirit", return_value={"context": {}}):
        assert not checkout_is_clean_for_external_work(task, "/tmp/project")


def test_capture_external_work_baseline_persists_clean_execution_start() -> None:
    with (
        patch(
            "app.storage.task_spirit.get_task_spirit",
            return_value={"context": {}},
        ),
        patch(
            "app.storage.task_spirit.update_task_spirit",
        ) as update_spirit,
        patch(
            "app.tasks.autonomous.exec_modules.external_work.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout=""),
                SimpleNamespace(returncode=0, stdout="head-sha\n"),
            ],
        ),
    ):
        assert capture_external_work_baseline(_task(), "/tmp/project")

    update_spirit.assert_called_once_with(
        TASK_ID,
        context={"external_work_baseline": {"head": "head-sha", "source": "execution_start"}},
    )


def test_capture_external_work_baseline_does_not_rewrite_existing_start() -> None:
    existing = {"context": {"external_work_baseline": {"head": "original", "source": "execution_start"}}}
    with (
        patch("app.storage.task_spirit.get_task_spirit", return_value=existing),
        patch("app.storage.task_spirit.update_task_spirit") as update_spirit,
    ):
        assert capture_external_work_baseline(_task(), "/tmp/project")
    update_spirit.assert_not_called()


def test_quality_check_accepts_only_a_verified_clean_external_receipt() -> None:
    from app.tasks.autonomous.exec_modules import quality_check

    verified = ExternalWorkResult(True, "ok", _response())
    with (
        patch.object(quality_check, "_has_work_product", return_value=False),
        patch.object(quality_check, "get_task", return_value=_task()),
        patch.object(quality_check, "checkout_is_clean_for_external_work", return_value=True),
        patch.object(quality_check, "verify_external_work", return_value=verified),
    ):
        passed, steps = quality_check.run_execution_quality_check(
            TASK_ID, "subtask-1", [], "/tmp/project", "agent-hub",
        )

    assert passed is True
    assert steps[0]["reason"] == "external_work_verified"


def test_final_closeout_revalidates_receipt_and_keeps_code_gate_for_stale_receipt() -> None:
    from app.tasks.autonomous.exec_modules import completion_handler

    results = [{"status": "passed", "step_results": [{"passed": True, "external_work": _response()}]}]
    with (
        patch.object(completion_handler.task_store, "get_task", return_value=_task()),
        patch.object(completion_handler, "external_work_receipt", return_value=_response()),
        patch.object(completion_handler, "checkout_is_clean_for_external_work", return_value=True),
        patch.object(
            completion_handler,
            "verify_external_work",
            return_value=ExternalWorkResult(False, "canonical_receipt_not_terminal"),
        ),
        patch.object(
            completion_handler,
            "check_diff_gate",
            return_value=SimpleNamespace(passed=False, summary="no changes"),
        ),
        patch.object(completion_handler, "emit_task_transition"),
        patch.object(completion_handler, "emit_error"),
        patch.object(completion_handler, "notify_failure"),
        patch.object(completion_handler.task_store, "update_task_status"),
    ):
        assert not completion_handler.handle_successful_completion(
            TASK_ID, "agent-hub", "/tmp/project", results,
        )


def test_final_closeout_keeps_code_gates_when_baseline_changed() -> None:
    from app.tasks.autonomous.exec_modules import completion_handler

    results = [{"status": "passed", "step_results": [{"passed": True, "external_work": _response()}]}]
    with (
        patch.object(completion_handler.task_store, "get_task", return_value=_task()),
        patch.object(completion_handler, "external_work_receipt", return_value=_response()),
        patch.object(completion_handler, "checkout_is_clean_for_external_work", return_value=False),
        patch.object(completion_handler, "verify_external_work") as verify,
        patch.object(
            completion_handler,
            "check_diff_gate",
            return_value=SimpleNamespace(passed=False, summary="code changed after baseline"),
        ),
        patch.object(completion_handler, "emit_task_transition"),
        patch.object(completion_handler, "emit_error"),
        patch.object(completion_handler, "notify_failure"),
        patch.object(completion_handler.task_store, "update_task_status"),
    ):
        assert not completion_handler.handle_successful_completion(
            TASK_ID, "agent-hub", "/tmp/project", results,
        )
    verify.assert_not_called()


def test_fresh_external_proof_uses_normal_transition_helper() -> None:
    from app.tasks.autonomous.exec_modules import completion_handler

    receipt = _response()
    results = [{"status": "passed", "step_results": [{"passed": True, "external_work": receipt}]}]
    with (
        patch.object(completion_handler.task_store, "get_task", return_value=_task()),
        patch.object(completion_handler, "external_work_receipt", return_value=receipt),
        patch.object(completion_handler, "checkout_is_clean_for_external_work", return_value=True),
        patch.object(
            completion_handler,
            "verify_external_work",
            return_value=ExternalWorkResult(True, "ok", receipt),
        ),
        patch.object(completion_handler, "transition_to_complete") as transition,
        patch.object(completion_handler, "check_diff_gate") as diff_gate,
        patch.object(completion_handler, "run_quality_gate") as quality_gate,
    ):
        assert completion_handler.handle_successful_completion(
            TASK_ID, "agent-hub", "/tmp/project", results,
        )

    transition.assert_called_once()
    diff_gate.assert_not_called()
    quality_gate.assert_not_called()
