"""Tests for project-aware quality-gate pattern memory wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.quality_gate.fix_agent import _apply_and_verify, _build_prompt
from app.services.quality_gate.fix_verification import process_successful_fix


def test_build_prompt_passes_project_id_to_pattern_lookup(tmp_path: Path) -> None:
    check_result = {
        "project_id": "agent-hub",
        "check_type": "ruff",
        "check_name": "F401",
        "error_message": "unused import",
        "file_path": "test.py",
    }

    with (
        patch("app.services.quality_gate.fix_agent.get_similar_patterns", return_value=[]) as mock_patterns,
        patch("app.services.quality_gate.fix_agent.build_fix_prompt", return_value="prompt") as mock_build,
        patch("app.services.quality_gate.fix_agent.enhance_prompt_for_supervisor") as mock_enhance,
    ):
        result = _build_prompt(check_result, "import os\n", tmp_path, "WORKER")

    assert result == "prompt"
    mock_patterns.assert_called_once_with("ruff", "F401", "unused import", "agent-hub")
    mock_build.assert_called_once()
    mock_enhance.assert_not_called()


def test_process_successful_fix_passes_project_id_to_pattern_storage() -> None:
    conn = MagicMock()

    with (
        patch("app.services.quality_gate.fix_verification.qcr_store.mark_fixed"),
        patch("app.services.quality_gate.fix_verification.store_successful_pattern") as mock_store,
    ):
        process_successful_fix(
            conn=conn,
            result_id=123,
            project_id="agent-hub",
            agent_slug="fixer",
            check_type="ruff",
            check_name="F401",
            error_message="unused import",
            file_rel_path="test.py",
            original_content="import os\n",
            fixed_content="",
        )

    assert mock_store.call_args.kwargs["project_id"] == "agent-hub"


def test_apply_and_verify_passes_check_result_project_id_to_verification(tmp_path: Path) -> None:
    conn = MagicMock()
    file_path = tmp_path / "test.py"
    file_path.write_text("import os\n")
    check_result = {
        "project_id": "agent-hub",
        "check_type": "ruff",
        "check_name": "F401",
        "error_message": "unused import",
    }

    with (
        patch("app.services.quality_gate.fix_agent.apply_fix", return_value=True),
        patch(
            "app.services.quality_gate.fix_agent.verify_and_process_fix",
            return_value="fixed",
        ) as mock_verify,
    ):
        result = _apply_and_verify(
            conn=conn,
            result_id=123,
            check_result=check_result,
            project_path=tmp_path,
            file_path=file_path,
            file_rel_path="test.py",
            file_content="import os\n",
            new_content="",
            agent_slug="fixer",
            level="WORKER",
        )

    assert result == "fixed"
    assert mock_verify.call_args.args[2] == "agent-hub"
