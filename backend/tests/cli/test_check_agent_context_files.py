"""Agent context stays in Agent Hub: instruction files in a project root are flagged."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.commands.check_agent_context_files import run_agent_context_files_check


@pytest.mark.parametrize(
    "rel",
    ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "frontend/AGENTS.md", ".cursor/rules/a.mdc",
     ".claude/rules/a.md", ".github/copilot-instructions.md", ".cursorrules"],
)
def test_instruction_files_fail(tmp_path: Path, capsys, rel: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith("/a.mdc") or (rel.endswith("/a.md") and "rules" in rel):
        target = target.parent
    else:
        target.write_text("x")
    assert run_agent_context_files_check(tmp_path) == 1
    assert "AGENTCTX:FAIL:" in capsys.readouterr().out


def test_clean_project_passes(tmp_path: Path, capsys) -> None:
    (tmp_path / "README.md").write_text("x")
    assert run_agent_context_files_check(tmp_path) == 0
    assert "AGENTCTX:OK" in capsys.readouterr().out


def test_allow_list_is_data_in_st_check_toml(tmp_path: Path, capsys) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "CLAUDE.md").write_text("@AGENTS.md")
    assert run_agent_context_files_check(tmp_path) == 1
    (tmp_path / ".st-check.toml").write_text('[agent_context]\nallow = ["frontend/CLAUDE.md"]\n')
    assert run_agent_context_files_check(tmp_path) == 0
    (tmp_path / "AGENTS.md").write_text("x")
    assert run_agent_context_files_check(tmp_path) == 1
    assert "AGENTCTX:FAIL:AGENTS.md" in capsys.readouterr().out
