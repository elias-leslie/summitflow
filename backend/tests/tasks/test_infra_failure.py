"""Tests for infrastructure failure classification in execution pipeline."""

from __future__ import annotations

import pytest

from app.tasks.autonomous.execution import _is_infrastructure_failure


class TestInfrastructureFailureClassification:

    @pytest.mark.parametrize(
        "output,reason,returncode",
        [
            ("bash: rg: command not found", "", 127),
            ("/bin/sh: dt: command not found", "", 127),
            ("No such file or directory: /foo/bar.py", "", 1),
            ("FileNotFoundError: [Errno 2] No such file or directory: 'missing.py'", "", 1),
            ("Permission denied: ./run_tests.sh", "", 126),
            ("ModuleNotFoundError: No module named 'nonexistent'", "", 1),
            ("ImportError: cannot import name 'Missing' from 'pkg'", "", 1),
            ("Error: timed out after 60s", "", 1),
            ("Connection refused (localhost:8003)", "", 1),
        ],
    )
    def test_detects_infrastructure_failures(
        self, output: str, reason: str, returncode: int
    ) -> None:
        assert _is_infrastructure_failure(output, reason, returncode) is True

    @pytest.mark.parametrize(
        "output,reason,returncode",
        [
            ("FAILED tests/test_foo.py::test_bar - AssertionError", "", 1),
            ("Expected 'hello' but got 'world'", "output_mismatch", 1),
            ("E       assert 1 == 2", "", 1),
            ("FAIL: 3 errors, 2 warnings", "", 1),
            ("line 42: syntax error near unexpected token", "", 2),
            ("TypeError: unsupported operand type(s)", "", 1),
        ],
    )
    def test_detects_code_failures(
        self, output: str, reason: str, returncode: int
    ) -> None:
        assert _is_infrastructure_failure(output, reason, returncode) is False

    def test_reason_field_checked(self) -> None:
        assert _is_infrastructure_failure("", "command not found", 127) is True

    def test_empty_output_is_code_failure(self) -> None:
        assert _is_infrastructure_failure("", "", 1) is False
