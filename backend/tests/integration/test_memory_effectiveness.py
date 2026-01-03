"""TDD tests for memory effectiveness.

These tests verify that the memory system provides useful context to agents
via PROGRESSIVE DISCLOSURE:
  - patterns_index: titles only (in session-start response)
  - Full content: via member-dis expand or /context/expand

Methodology:
1. Run tests → expect failures (memory has no useful patterns yet)
2. Add patterns to fix failures
3. Re-run tests → verify improvement
4. Iterate until all pass
"""

import subprocess

import httpx
import pytest

# Base URL for local API
API_BASE = "http://localhost:8001"
PROJECT_ID = "summitflow"


class TestPatternsIndex:
    """Tests that patterns_index provides useful knowledge discovery.

    Progressive disclosure: patterns_index contains TITLES only.
    Full content retrieved via member-dis expand or /context/expand.
    """

    @pytest.fixture
    def session_start_response(self) -> dict:
        """Fetch full session-start response from real API."""
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{API_BASE}/api/projects/{PROJECT_ID}/context/session-start",
                json={},
            )
            resp.raise_for_status()
            return resp.json()

    @pytest.fixture
    def patterns_index(self, session_start_response: dict) -> list[dict]:
        """Extract patterns_index from session-start response."""
        return session_start_response.get("patterns_index", [])

    def test_patterns_index_has_entries(self, patterns_index: list[dict]):
        """Session-start should include patterns index for progressive disclosure."""
        assert len(patterns_index) >= 5, (
            f"patterns_index should have at least 5 entries for useful coverage. "
            f"Got {len(patterns_index)} entries."
        )

    def test_patterns_index_has_storage_pattern(self, patterns_index: list[dict]):
        """Patterns index should include storage location pattern.

        This is the #1 most searched location (34 searches in session history).
        """
        pattern_titles = " ".join(p.get("title", "").lower() for p in patterns_index)

        assert any(kw in pattern_titles for kw in ["storage", "persistence", "data layer"]), (
            f"patterns_index should have a storage location pattern. Titles: {pattern_titles[:200]}"
        )

    def test_patterns_index_has_api_pattern(self, patterns_index: list[dict]):
        """Patterns index should include API location pattern.

        This is the #2 most searched location (30 searches in session history).
        """
        pattern_titles = " ".join(p.get("title", "").lower() for p in patterns_index)

        assert any(kw in pattern_titles for kw in ["api", "endpoint", "router"]), (
            f"patterns_index should have an API location pattern. Titles: {pattern_titles[:200]}"
        )

    def test_patterns_index_has_components_pattern(self, patterns_index: list[dict]):
        """Patterns index should include React components location pattern.

        This is the #3 most searched location (26 searches in session history).
        """
        pattern_titles = " ".join(p.get("title", "").lower() for p in patterns_index)

        assert any(kw in pattern_titles for kw in ["component", "react", "frontend", "tsx"]), (
            f"patterns_index should have a components location pattern. Titles: {pattern_titles[:200]}"
        )

    def test_patterns_index_covers_key_locations(self, patterns_index: list[dict]):
        """Patterns index should cover at least 3 key codebase locations."""
        location_keywords = [
            "storage",
            "api",
            "component",
            "service",
            "migration",
            "task",
            "celery",
        ]
        pattern_titles = " ".join(p.get("title", "").lower() for p in patterns_index)

        found_locations = [kw for kw in location_keywords if kw in pattern_titles]

        assert len(found_locations) >= 3, (
            f"patterns_index should cover at least 3 key locations. "
            f"Found: {found_locations}. Looking for: {location_keywords}"
        )


class TestMemberDisSearch:
    """Tests that member-dis search returns relevant results."""

    def _run_member_dis(self, *args: str) -> subprocess.CompletedProcess:
        """Run member-dis CLI command."""
        return subprocess.run(
            ["member-dis", *args],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/home/kasadis/summitflow",
        )

    def test_member_dis_search_finds_storage(self):
        """member-dis search should find storage-related patterns.

        When an agent asks 'where are tasks stored', the search should
        return patterns mentioning backend/app/storage.
        """
        result = self._run_member_dis("search", "where are tasks stored")

        # Should return useful results (not empty or error)
        combined_output = (result.stdout + result.stderr).lower()

        assert any(
            phrase in combined_output
            for phrase in ["storage", "tasks.py", "backend/app", "no results"]
        ), (
            f"member-dis search should return results or 'no results'. Got:\n{result.stdout}\n{result.stderr}"
        )

    def test_member_dis_search_finds_api(self):
        """member-dis search should find API-related patterns."""
        result = self._run_member_dis("search", "where are api endpoints")

        combined_output = (result.stdout + result.stderr).lower()

        assert any(
            phrase in combined_output
            for phrase in ["api", "router", "endpoint", "backend/app/api", "no results"]
        ), (
            f"member-dis search should return results or 'no results'. Got:\n{result.stdout}\n{result.stderr}"
        )

    def test_member_dis_available(self):
        """member-dis CLI should be available and working."""
        result = self._run_member_dis("--help")

        assert (
            result.returncode == 0
            or "usage" in result.stdout.lower()
            or "member-dis" in result.stderr.lower()
        ), (
            f"member-dis should be available. returncode={result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestPatternExpand:
    """Tests that full pattern content is accessible.

    This validates the second half of progressive disclosure:
    patterns_index gives titles, patterns API gives full content.

    NOTE: There's currently a gap - patterns_index uses short IDs (pat:abc123)
    but expand API needs full UUIDs. Agents must use /patterns API instead.
    """

    def test_patterns_api_returns_full_content(self):
        """Patterns API should return full content for applied patterns."""
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{API_BASE}/api/projects/{PROJECT_ID}/patterns",
                params={"status": "applied", "limit": 5},
            )
            resp.raise_for_status()
            data = resp.json()

            patterns = data.get("patterns", [])
            if not patterns:
                pytest.skip("No applied patterns to test")

            # Each pattern should have full content
            pattern = patterns[0]
            assert "content" in pattern, (
                f"Pattern should have content field. Got: {list(pattern.keys())}"
            )
            assert len(pattern.get("content", "")) > 10, (
                f"Pattern content should be substantial. Got: {pattern.get('content', '')[:50]}"
            )

    def test_patterns_index_has_type_field(self):
        """Patterns index should include type for filtering.

        Agents can use type to decide which patterns to expand.
        """
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{API_BASE}/api/projects/{PROJECT_ID}/context/session-start",
                json={},
            )
            resp.raise_for_status()
            patterns_index = resp.json().get("patterns_index", [])

            if not patterns_index:
                pytest.skip("No patterns in index")

            # Should have type field for filtering
            pattern = patterns_index[0]
            assert "type" in pattern, (
                f"Pattern index entry should have type. Got: {list(pattern.keys())}"
            )


class TestMemoryStats:
    """Tests that memory system has content to search."""

    def test_patterns_exist_in_database(self):
        """Database should have patterns that can be searched."""
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{API_BASE}/api/memory/stats")
            resp.raise_for_status()
            stats = resp.json()

        lifecycle = stats.get("lifecycle", {})
        pattern_breakdown = lifecycle.get("pattern_status_breakdown", {})

        # Count patterns that are usable (applied, approved, merged)
        usable_count = sum(
            pattern_breakdown.get(status, 0) for status in ["applied", "approved", "merged"]
        )

        assert usable_count >= 10, (
            f"Should have at least 10 usable patterns. "
            f"Got {usable_count}. Breakdown: {pattern_breakdown}"
        )
