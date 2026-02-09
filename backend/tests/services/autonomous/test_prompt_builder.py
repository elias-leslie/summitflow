from typing import Any

from app.services.autonomous.prompt_builder import build_execution_prompt


def test_build_execution_prompt_basic() -> None:
    task: dict[str, Any] = {
        "title": "Test Task",
        "description": "Test Description",
        "objective": "Test Objective",
        "files_affected": ["file1.py"]
    }
    context: dict[str, Any] = {
        "files": ["file1.py"],
        "rule_contents": {"Rule1": "Content1"},
        "patterns": [{"pattern": "Pat1", "rationale": "Rat1"}]
    }
    prompt = build_execution_prompt(task, context)
    assert "# Task Execution" in prompt
    assert "**Title:** Test Task" in prompt
    assert "**Description:** Test Description" in prompt
    assert "## OBJECTIVE" in prompt
    assert "Test Objective" in prompt
    assert "file1.py" in prompt
    assert "# Relevant Rules" in prompt
    assert "## Rule1" in prompt
    assert "Content1" in prompt
    assert "# Learned Patterns" in prompt
    assert "Pat1" in prompt
    assert "Rat1" in prompt
    assert "# Verification" in prompt
    assert "# Output Format" in prompt

def test_build_execution_prompt_iteration_context() -> None:
    task: dict[str, Any] = {"title": "Test"}
    context: dict[str, Any] = {}
    iteration_context: dict[str, Any] = {
        "iteration": 2,
        "test_failures": "Pytest failed",
        "static_failures": "Pyright failed",
        "advice": "Try harder",
        "handoff_context": "I gave up"
    }
    prompt = build_execution_prompt(task, context, iteration_context)
    assert "# PREVIOUS ATTEMPT FAILED" in prompt
    assert "attempt #2" in prompt
    assert "## Test Failures" in prompt
    assert "Pytest failed" in prompt
    assert "## Static Analysis Errors" in prompt
    assert "Pyright failed" in prompt
    assert "## SUGGESTION FROM ALTERNATE MODEL" in prompt
    assert "Try harder" in prompt
    assert "# HANDOFF FROM PREVIOUS MODEL" in prompt
    assert "I gave up" in prompt
