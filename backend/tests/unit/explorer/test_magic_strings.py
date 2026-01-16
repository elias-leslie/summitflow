"""Tests for magic string detection in FileScanner."""

import pytest

from app.services.explorer.types.files import (
    MAGIC_STRING_PATTERNS,
    FileScanner,
)


class TestMagicStringPatterns:
    """Test the magic string regex patterns directly."""

    def test_project_names_pattern_matches(self):
        """Test project_names pattern matches expected strings."""
        pattern = MAGIC_STRING_PATTERNS["project_names"]
        assert pattern.search("summitflow")
        assert pattern.search("SummitFlow")
        assert pattern.search("portfolio-ai")
        assert not pattern.search("random_project")

    def test_hardcoded_paths_pattern_matches(self):
        """Test hardcoded_paths pattern matches expected strings."""
        pattern = MAGIC_STRING_PATTERNS["hardcoded_paths"]
        assert pattern.search('"/home/user/project"')
        assert pattern.search('"/Users/kasadis/code"')
        assert pattern.search('"/var/log/app.log"')
        assert not pattern.search('"./relative/path"')
        assert not pattern.search('"src/app"')

    def test_hardcoded_urls_pattern_matches(self):
        """Test hardcoded_urls pattern matches expected strings."""
        pattern = MAGIC_STRING_PATTERNS["hardcoded_urls"]
        assert pattern.search('"http://localhost:3000"')
        assert pattern.search('"https://127.0.0.1:8080"')
        assert pattern.search('"http://192.168.1.100"')
        assert not pattern.search('"https://api.example.com"')

    def test_legacy_models_pattern_matches(self):
        """Test legacy_models pattern matches deprecated model names."""
        pattern = MAGIC_STRING_PATTERNS["legacy_models"]
        assert pattern.search("claude-3-opus")
        assert pattern.search("claude-3-sonnet")
        assert pattern.search("gemini-2.0-flash")
        assert pattern.search("gpt-3.5-turbo")
        assert not pattern.search("claude-sonnet-4-5")
        assert not pattern.search("gemini-3-flash")


class TestFileScannerMagicStrings:
    """Test FileScanner._detect_magic_strings method."""

    @pytest.fixture
    def scanner(self):
        """Create a FileScanner instance."""
        return FileScanner("test-project")

    def test_detect_project_names(self, scanner):
        """Detect project names in code."""
        content = """
project_id = "summitflow"
url = "https://summitflow.dev"
"""
        result = scanner._detect_magic_strings("app/config.py", content)
        assert "project_names" in result
        assert result["project_names"] >= 2

    def test_detect_hardcoded_paths(self, scanner):
        """Detect hardcoded paths in code."""
        content = """
LOG_PATH = "/var/log/app.log"
DATA_DIR = "/home/user/data"
"""
        result = scanner._detect_magic_strings("app/settings.py", content)
        assert "hardcoded_paths" in result
        assert result["hardcoded_paths"] >= 2

    def test_detect_legacy_models(self, scanner):
        """Detect legacy model references."""
        content = """
model = "claude-3-opus"
fallback = "gpt-3.5-turbo"
"""
        result = scanner._detect_magic_strings("app/ai.py", content)
        assert "legacy_models" in result
        assert result["legacy_models"] >= 2

    def test_exclude_pattern_project_names_in_markdown(self, scanner):
        """Project names in markdown should be excluded."""
        content = "# SummitFlow Documentation\nThis is SummitFlow."
        result = scanner._detect_magic_strings("README.md", content)
        assert "project_names" not in result

    def test_exclude_pattern_project_names_in_tests(self, scanner):
        """Project names in test files should be excluded."""
        content = 'assert project_id == "summitflow"'
        result = scanner._detect_magic_strings("tests/test_config.py", content)
        assert "project_names" not in result

    def test_exclude_pattern_hardcoded_paths_in_json(self, scanner):
        """Hardcoded paths in JSON config should be excluded."""
        content = '{"path": "/home/user/config"}'
        result = scanner._detect_magic_strings("config.json", content)
        assert "hardcoded_paths" not in result

    def test_exclude_pattern_urls_in_tests(self, scanner):
        """Local URLs in test files should be excluded."""
        content = 'url = "http://localhost:8000"'
        result = scanner._detect_magic_strings("test_api.py", content)
        assert "hardcoded_urls" not in result

    def test_legacy_models_not_excluded(self, scanner):
        """Legacy models should be detected everywhere."""
        content = 'model = "claude-3-sonnet"'
        # Even in tests
        result = scanner._detect_magic_strings("test_models.py", content)
        assert "legacy_models" in result
        # Even in markdown
        result = scanner._detect_magic_strings("docs.md", content)
        assert "legacy_models" in result

    def test_empty_content(self, scanner):
        """Empty content returns empty dict."""
        result = scanner._detect_magic_strings("app/empty.py", "")
        assert result == {}

    def test_no_matches(self, scanner):
        """Content with no magic strings returns empty dict."""
        content = """
def clean_function():
    return 42
"""
        result = scanner._detect_magic_strings("app/clean.py", content)
        assert result == {}

    def test_multiple_categories(self, scanner):
        """Detect multiple categories at once."""
        content = """
PROJECT = "summitflow"
MODEL = "claude-3-opus"
API_URL = "http://localhost:8000"
"""
        # Not in excluded patterns
        result = scanner._detect_magic_strings("app/constants.py", content)
        assert "project_names" in result
        assert "legacy_models" in result
        assert "hardcoded_urls" in result
