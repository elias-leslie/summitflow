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
        mock_response.text = json.dumps(
            {
                "verdict": "false_positive",
                "confidence": 0.95,
                "reason": "Intentional backward compatibility layer",
                "suggested_action": "Add to allow list",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
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
        mock_response.text = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.88,
                "reason": "Outdated TODO from 2 years ago",
                "suggested_action": "Create task to fix or remove",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
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
        mock_response.text = json.dumps(
            {
                "verdict": "needs_refactor",
                "confidence": 0.75,
                "reason": "Code smell but not urgent",
                "suggested_action": "Add to backlog",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
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
        mock_response.text = "Not valid JSON"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
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
        mock_client.models.generate_content.side_effect = Exception("API Error")
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
        mock_response.text = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.8,
                "reason": "Real issue",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
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


class TestMemoryIntegration:
    """Test memory integration for learning and reuse."""

    def test_memory_disabled_by_default_without_project_id(self) -> None:
        """Test that memory is disabled when no project_id is provided."""
        classifier = CodeHealthClassifier()
        assert classifier.enable_memory is False

    def test_memory_enabled_with_project_id(self) -> None:
        """Test that memory is enabled when project_id is provided."""
        classifier = CodeHealthClassifier(project_id="test-project")
        assert classifier.enable_memory is True

    def test_memory_can_be_explicitly_disabled(self) -> None:
        """Test that memory can be explicitly disabled."""
        classifier = CodeHealthClassifier(project_id="test-project", enable_memory=False)
        assert classifier.enable_memory is False

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    @patch("app.storage.memory.create_observation")
    def test_stores_observation_after_classification(
        self,
        mock_create_obs: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Test that classification result is stored as observation."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.9,
                "reason": "Real issue detected",
                "suggested_action": "Fix it",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="old code pattern",
        )

        result = classifier.classify(finding)

        # Verify observation was stored
        mock_create_obs.assert_called_once()
        call_kwargs = mock_create_obs.call_args.kwargs
        assert call_kwargs["project_id"] == "test-project"
        assert call_kwargs["observation_type"] == "code_health"
        assert "compat_comments" in call_kwargs["title"]
        assert result.verdict.value in call_kwargs["title"]
        assert call_kwargs["confidence"] == 0.9
        assert "compat_comments" in call_kwargs["concepts"]

    @patch("app.storage.memory.search_observations_fts")
    def test_queries_memory_for_similar_decisions(
        self,
        mock_search: MagicMock,
    ) -> None:
        """Test that classifier queries memory for similar past decisions."""
        # Mock a high-confidence past decision
        mock_search.return_value = [
            {
                "id": "obs-123",
                "observation_type": "code_health",
                "confidence": 0.95,
                "facts": {
                    "category": "compat_comments",
                    "verdict": "false_positive",
                    "reason": "Intentional compatibility layer",
                    "suggested_action": "Add to allow list",
                },
            }
        ]

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="old code pattern",
        )

        result = classifier._query_memory_for_similar(finding)

        # Verify memory was queried
        mock_search.assert_called_once()
        assert "compat_comments" in mock_search.call_args.kwargs["query"]

        # Verify result from memory
        assert result is not None
        assert result.verdict == ClassificationVerdict.FALSE_POSITIVE
        assert result.confidence == 0.95
        assert "[From memory]" in result.reason

    @patch("app.storage.memory.search_observations_fts")
    def test_skips_low_confidence_memory_results(
        self,
        mock_search: MagicMock,
    ) -> None:
        """Test that low-confidence memory results are skipped."""
        # Mock a low-confidence past decision (below 0.8 threshold)
        mock_search.return_value = [
            {
                "id": "obs-123",
                "observation_type": "code_health",
                "confidence": 0.5,
                "facts": {
                    "category": "compat_comments",
                    "verdict": "false_positive",
                    "reason": "Maybe intentional",
                },
            }
        ]

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="old code pattern",
        )

        result = classifier._query_memory_for_similar(finding)

        # Should return None (not reusing low-confidence result)
        assert result is None

    @patch("app.storage.memory.search_observations_fts")
    def test_skips_different_category_memory_results(
        self,
        mock_search: MagicMock,
    ) -> None:
        """Test that memory results with different category are skipped."""
        # Mock a result with different category
        mock_search.return_value = [
            {
                "id": "obs-123",
                "observation_type": "code_health",
                "confidence": 0.95,
                "facts": {
                    "category": "stale_todos",  # Different from query
                    "verdict": "false_positive",
                    "reason": "Not relevant",
                },
            }
        ]

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="old code pattern",
        )

        result = classifier._query_memory_for_similar(finding)

        # Should return None (category mismatch)
        assert result is None

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    @patch("app.storage.memory.search_observations_fts")
    def test_reuses_memory_instead_of_llm(
        self,
        mock_search: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Test that high-confidence memory result skips LLM call."""
        # Mock a high-confidence past decision
        mock_search.return_value = [
            {
                "id": "obs-123",
                "observation_type": "code_health",
                "confidence": 0.92,
                "facts": {
                    "category": "compat_comments",
                    "verdict": "false_positive",
                    "reason": "Known compatibility layer",
                    "suggested_action": "Allow list it",
                },
            }
        ]

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="old code pattern",
        )

        result = classifier.classify(finding)

        # LLM should NOT be called
        mock_get_client.assert_not_called()

        # Result should be from memory
        assert result.verdict == ClassificationVerdict.FALSE_POSITIVE
        assert "[From memory]" in result.reason

    @patch("app.services.code_health.classifier.CodeHealthClassifier._get_client")
    @patch("app.storage.memory.search_observations_fts")
    @patch("app.storage.memory.create_observation")
    def test_calls_llm_when_no_memory_match(
        self,
        mock_create_obs: MagicMock,
        mock_search: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Test that LLM is called when no high-confidence memory match exists."""
        # Mock empty memory search result
        mock_search.return_value = []

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "verdict": "true_positive",
                "confidence": 0.85,
                "reason": "New issue found",
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        classifier = CodeHealthClassifier(project_id="test-project")
        finding = Finding(
            file_path="app/test.py",
            category="new_category",
            pattern="new pattern",
        )

        result = classifier.classify(finding)

        # Memory should be searched first
        mock_search.assert_called_once()

        # LLM should be called since no memory match
        mock_get_client.assert_called_once()

        # Result should be from LLM
        assert result.verdict == ClassificationVerdict.TRUE_POSITIVE
        assert "[From memory]" not in result.reason

        # Observation should be stored for learning
        mock_create_obs.assert_called_once()
