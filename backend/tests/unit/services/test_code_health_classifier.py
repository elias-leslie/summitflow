"""Unit tests for code health classifier."""

import json
from unittest.mock import MagicMock, patch

from app.services.code_health.classifier import (
    ClassificationResult,
    ClassificationVerdict,
    CodeHealthClassifier,
    Finding,
    build_classification_prompt,
)


class TestFinding:
    """Test Finding dataclass."""

    def test_creates_finding_with_required_fields(self) -> None:
        """Test creating a finding with required fields only."""
        finding = Finding(
            file_path="app/storage/memory.py",
            category="compat_comments",
            pattern="backward compatibility",
        )
        assert finding.file_path == "app/storage/memory.py"
        assert finding.category == "compat_comments"
        assert finding.pattern == "backward compatibility"
        assert finding.line_number is None
        assert finding.context is None

    def test_creates_finding_with_all_fields(self) -> None:
        """Test creating a finding with all fields."""
        finding = Finding(
            file_path="app/api/tasks.py",
            category="legacy_vars",
            pattern="old_config",
            line_number=42,
            context="def old_config(): pass",
        )
        assert finding.line_number == 42
        assert finding.context == "def old_config(): pass"


class TestBuildClassificationPrompt:
    """Test build_classification_prompt function."""

    def test_includes_required_fields(self) -> None:
        """Test prompt includes file, category, and pattern."""
        finding = Finding(
            file_path="test.py",
            category="compat_comments",
            pattern="legacy",
        )
        prompt = build_classification_prompt(finding)

        assert "test.py" in prompt
        assert "compat_comments" in prompt
        assert "legacy" in prompt

    def test_includes_line_number_when_present(self) -> None:
        """Test prompt includes line number when provided."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
            line_number=100,
        )
        prompt = build_classification_prompt(finding)

        assert "Line: 100" in prompt

    def test_excludes_line_number_when_absent(self) -> None:
        """Test prompt excludes line number when not provided."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )
        prompt = build_classification_prompt(finding)

        assert "Line:" not in prompt

    def test_includes_context_when_present(self) -> None:
        """Test prompt includes code context when provided."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
            context="# some code here\nold_func = new_func",
        )
        prompt = build_classification_prompt(finding)

        assert "Code Context" in prompt
        assert "old_func = new_func" in prompt

    def test_includes_verdict_options(self) -> None:
        """Test prompt includes all verdict options."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )
        prompt = build_classification_prompt(finding)

        assert "FALSE_POSITIVE" in prompt
        assert "TRUE_POSITIVE" in prompt
        assert "NEEDS_REFACTOR" in prompt

    def test_includes_json_response_format(self) -> None:
        """Test prompt specifies JSON response format."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )
        prompt = build_classification_prompt(finding)

        assert "Response Format (JSON only)" in prompt
        assert '"verdict":' in prompt
        assert '"confidence":' in prompt


class TestCodeHealthClassifier:
    """Test CodeHealthClassifier class."""

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_classify_returns_false_positive(self, mock_get_client: MagicMock) -> None:
        """Test classifying a finding as false positive."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "verdict": "false_positive",
                "confidence": 0.95,
                "reason": "Intentional backward compatibility layer",
                "suggested_action": "Add to allow list",
            }
        )
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        finding = Finding(
            file_path="app/storage/memory.py",
            category="compat_comments",
            pattern="# Re-export for backward compatibility",
        )

        result = classifier.classify(finding)

        assert result.verdict == ClassificationVerdict.FALSE_POSITIVE
        assert result.confidence == 0.95
        assert "backward compatibility" in result.reason

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_classify_returns_true_positive(self, mock_get_client: MagicMock) -> None:
        """Test classifying a finding as true positive."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.88,
                "reason": "Outdated TODO from 2 years ago",
                "suggested_action": "Create task to fix or remove",
            }
        )
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        finding = Finding(
            file_path="app/api/routes.py",
            category="stale_todos",
            pattern="# TODO: Fix this later",
            line_number=42,
        )

        result = classifier.classify(finding)

        assert result.verdict == ClassificationVerdict.TRUE_POSITIVE
        assert result.confidence == 0.88
        assert "Create task" in (result.suggested_action or "")

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_classify_returns_needs_refactor(self, mock_get_client: MagicMock) -> None:
        """Test classifying a finding as needs refactor."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "verdict": "needs_refactor",
                "confidence": 0.75,
                "reason": "Code smell but not urgent",
                "suggested_action": "Add to backlog",
            }
        )
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        finding = Finding(
            file_path="app/utils/helpers.py",
            category="legacy_vars",
            pattern="old_helper_func",
        )

        result = classifier.classify(finding)

        assert result.verdict == ClassificationVerdict.NEEDS_REFACTOR
        assert result.confidence == 0.75

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_handles_json_parse_error(self, mock_get_client: MagicMock) -> None:
        """Test handling of JSON parse errors."""
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )

        result = classifier.classify(finding)

        assert result.verdict == ClassificationVerdict.NEEDS_REFACTOR
        assert result.confidence == 0.3
        assert "parse" in result.reason.lower()

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_handles_api_error(self, mock_get_client: MagicMock) -> None:
        """Test handling of API errors."""
        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )

        result = classifier.classify(finding)

        assert result.verdict == ClassificationVerdict.NEEDS_REFACTOR
        assert result.confidence == 0.0
        assert "error" in result.reason.lower()

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    def test_classify_batch(self, mock_get_client: MagicMock) -> None:
        """Test batch classification of findings."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.8,
                "reason": "Real issue",
            }
        )
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier()
        findings = [
            Finding(file_path="a.py", category="test", pattern="pattern1"),
            Finding(file_path="b.py", category="test", pattern="pattern2"),
        ]

        results = classifier.classify_batch(findings)

        assert len(results) == 2
        assert all(isinstance(r[0], Finding) for r in results)
        assert all(isinstance(r[1], ClassificationResult) for r in results)


class TestClassificationVerdict:
    """Test ClassificationVerdict enum."""

    def test_verdict_values(self) -> None:
        """Test verdict enum values."""
        assert ClassificationVerdict.FALSE_POSITIVE.value == "false_positive"
        assert ClassificationVerdict.TRUE_POSITIVE.value == "true_positive"
        assert ClassificationVerdict.NEEDS_REFACTOR.value == "needs_refactor"

    def test_verdict_from_string(self) -> None:
        """Test creating verdict from string."""
        assert ClassificationVerdict("false_positive") == ClassificationVerdict.FALSE_POSITIVE
        assert ClassificationVerdict("true_positive") == ClassificationVerdict.TRUE_POSITIVE
        assert ClassificationVerdict("needs_refactor") == ClassificationVerdict.NEEDS_REFACTOR
