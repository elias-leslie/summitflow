"""Unit tests for compat cruft detection in FileScanner."""

from app.services.explorer.types.files import (
    COMPAT_CRUFT_EXCLUDE_PATTERNS,
    COMPAT_CRUFT_PATTERNS,
)


class TestCompatCruftPatterns:
    """Test the compat cruft regex patterns."""

    def test_compat_comments_pattern_matches_backward(self) -> None:
        """Test compat_comments pattern matches 'backward' comments."""
        pattern = COMPAT_CRUFT_PATTERNS["compat_comments"]
        content = "# backward compatibility\n# compat layer"
        matches = pattern.findall(content)
        assert len(matches) == 2

    def test_compat_comments_pattern_matches_legacy(self) -> None:
        """Test compat_comments pattern matches 'legacy' comments."""
        pattern = COMPAT_CRUFT_PATTERNS["compat_comments"]
        content = "# legacy code\n# alias for old function"
        matches = pattern.findall(content)
        assert len(matches) == 2

    def test_compat_comments_pattern_matches_re_export(self) -> None:
        """Test compat_comments pattern matches 're-export' comments."""
        pattern = COMPAT_CRUFT_PATTERNS["compat_comments"]
        content = "# Re-export for backward compatibility"
        matches = pattern.findall(content)
        assert len(matches) >= 1  # Should match 're-export' and/or 'backward'

    def test_deprecated_markers_pattern_matches_uppercase(self) -> None:
        """Test deprecated_markers pattern matches DEPRECATED."""
        pattern = COMPAT_CRUFT_PATTERNS["deprecated_markers"]
        content = "# DEPRECATED: Use new_function instead"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_deprecated_markers_pattern_matches_at_deprecated(self) -> None:
        """Test deprecated_markers pattern matches @deprecated."""
        pattern = COMPAT_CRUFT_PATTERNS["deprecated_markers"]
        content = "# @deprecated use v2 API"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_deprecated_markers_pattern_matches_deprecated_colon(self) -> None:
        """Test deprecated_markers pattern matches deprecated:."""
        pattern = COMPAT_CRUFT_PATTERNS["deprecated_markers"]
        content = "# deprecated: will be removed in v2"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_legacy_vars_pattern_matches_suffix_old(self) -> None:
        """Test legacy_vars pattern matches _old suffix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "config_old = {}\ndata_old = None"
        matches = pattern.findall(content)
        assert len(matches) == 2

    def test_legacy_vars_pattern_matches_suffix_legacy(self) -> None:
        """Test legacy_vars pattern matches _legacy suffix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "handler_legacy = OldHandler()"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_legacy_vars_pattern_matches_suffix_deprecated(self) -> None:
        """Test legacy_vars pattern matches _deprecated suffix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "api_deprecated = None"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_legacy_vars_pattern_matches_prefix_old(self) -> None:
        """Test legacy_vars pattern matches old_ prefix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "old_handler = None"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_legacy_vars_pattern_matches_prefix_legacy(self) -> None:
        """Test legacy_vars pattern matches legacy_ prefix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "legacy_config = {}"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_legacy_vars_pattern_matches_prefix_deprecated(self) -> None:
        """Test legacy_vars pattern matches deprecated_ prefix."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        content = "deprecated_method = lambda: None"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_stale_todos_pattern_matches_todo(self) -> None:
        """Test stale_todos pattern matches TODO."""
        pattern = COMPAT_CRUFT_PATTERNS["stale_todos"]
        content = "# TODO: Fix this later"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_stale_todos_pattern_matches_fixme(self) -> None:
        """Test stale_todos pattern matches FIXME."""
        pattern = COMPAT_CRUFT_PATTERNS["stale_todos"]
        content = "# FIXME: Handle edge case"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_stale_todos_pattern_matches_xxx(self) -> None:
        """Test stale_todos pattern matches XXX."""
        pattern = COMPAT_CRUFT_PATTERNS["stale_todos"]
        content = "# XXX: This is a hack"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_stale_todos_pattern_matches_hack(self) -> None:
        """Test stale_todos pattern matches HACK."""
        pattern = COMPAT_CRUFT_PATTERNS["stale_todos"]
        content = "# HACK: Workaround for bug"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_alias_exports_pattern_matches_compat_alias(self) -> None:
        """Test alias_exports pattern matches compat alias."""
        pattern = COMPAT_CRUFT_PATTERNS["alias_exports"]
        content = "old_func = new_func  # alias for compat"
        matches = pattern.findall(content)
        assert len(matches) == 1

    def test_alias_exports_pattern_matches_legacy_export(self) -> None:
        """Test alias_exports pattern matches legacy export."""
        pattern = COMPAT_CRUFT_PATTERNS["alias_exports"]
        content = "OldClass = NewClass  # legacy export"
        matches = pattern.findall(content)
        assert len(matches) == 1


class TestCompatCruftExcludePatterns:
    """Test the exclude patterns for compat cruft detection."""

    def test_compat_comments_excludes_test_files(self) -> None:
        """Test that compat_comments excludes test files."""
        excludes = COMPAT_CRUFT_EXCLUDE_PATTERNS["compat_comments"]
        assert "*test*" in excludes
        assert "*spec*" in excludes

    def test_deprecated_markers_not_excluded(self) -> None:
        """Test that deprecated_markers has no exclusions."""
        excludes = COMPAT_CRUFT_EXCLUDE_PATTERNS["deprecated_markers"]
        assert len(excludes) == 0

    def test_legacy_vars_excludes_migrations(self) -> None:
        """Test that legacy_vars excludes migration files."""
        excludes = COMPAT_CRUFT_EXCLUDE_PATTERNS["legacy_vars"]
        assert "*migration*" in excludes

    def test_stale_todos_not_excluded(self) -> None:
        """Test that stale_todos has no exclusions."""
        excludes = COMPAT_CRUFT_EXCLUDE_PATTERNS["stale_todos"]
        assert len(excludes) == 0

    def test_alias_exports_excludes_init_files(self) -> None:
        """Test that alias_exports excludes __init__.py files."""
        excludes = COMPAT_CRUFT_EXCLUDE_PATTERNS["alias_exports"]
        assert "__init__.py" in excludes


class TestCompatCruftPatternCoverage:
    """Test that patterns don't over-match."""

    def test_compat_comments_no_false_positive_on_normal_comment(self) -> None:
        """Test compat_comments doesn't match normal comments."""
        pattern = COMPAT_CRUFT_PATTERNS["compat_comments"]
        content = "# This is a normal comment\n# No compat issues here"
        matches = pattern.findall(content)
        assert len(matches) == 0

    def test_legacy_vars_no_false_positive_on_normal_var(self) -> None:
        """Test legacy_vars doesn't match variables that happen to contain 'old'."""
        pattern = COMPAT_CRUFT_PATTERNS["legacy_vars"]
        # 'bold' and 'folder' contain 'old' but shouldn't match
        content = "bold_text = True\nfolder_path = '/tmp'"
        matches = pattern.findall(content)
        # These should not match because 'bold' and 'folder' don't have _old suffix
        assert len(matches) == 0

    def test_stale_todos_no_false_positive_in_string(self) -> None:
        """Test stale_todos doesn't match TODO in strings without # prefix."""
        pattern = COMPAT_CRUFT_PATTERNS["stale_todos"]
        content = 'msg = "TODO: Complete this"\nprint("FIXME later")'
        matches = pattern.findall(content)
        # Pattern requires # prefix, so no matches
        assert len(matches) == 0
