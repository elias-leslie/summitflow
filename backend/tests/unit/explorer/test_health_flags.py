"""Unit tests for health flag computation."""

import tempfile
from pathlib import Path

from app.services.explorer.types.file_constants import CODE_HEALTH_THRESHOLDS
from app.services.explorer.types.file_detection import compute_health_flags


class TestHealthFlagComputation:
    """Test the compute_health_flags function."""

    def test_too_many_functions_flag(self) -> None:
        """Test too_many_functions flag when function count exceeds threshold."""
        max_funcs = CODE_HEALTH_THRESHOLDS["max_functions_per_file"]
        flags = compute_health_flags(Path("/tmp/test.py"), ".py", max_funcs + 1, 0, 0)
        assert flags.get("too_many_functions") is True

    def test_too_many_functions_not_set_when_under_threshold(self) -> None:
        """Test too_many_functions not set when under threshold."""
        max_funcs = CODE_HEALTH_THRESHOLDS["max_functions_per_file"]
        flags = compute_health_flags(Path("/tmp/test.py"), ".py", max_funcs, 0, 0)
        assert "too_many_functions" not in flags

    def test_too_many_classes_flag(self) -> None:
        """Test too_many_classes flag when class count exceeds threshold."""
        max_classes = CODE_HEALTH_THRESHOLDS["max_classes_per_file"]
        flags = compute_health_flags(Path("/tmp/test.py"), ".py", 0, max_classes + 1, 0)
        assert flags.get("too_many_classes") is True

    def test_too_many_imports_flag(self) -> None:
        """Test too_many_imports flag when import count exceeds threshold."""
        max_imports = CODE_HEALTH_THRESHOLDS["max_imports"]
        flags = compute_health_flags(Path("/tmp/test.py"), ".py", 0, 0, max_imports + 1)
        assert flags.get("too_many_imports") is True

    def test_no_flags_when_all_under_thresholds(self) -> None:
        """Test no flags set when all counts are under thresholds."""
        flags = compute_health_flags(Path("/tmp/test.py"), ".py", 5, 2, 10)
        # Should have no basic flags
        assert "too_many_functions" not in flags
        assert "too_many_classes" not in flags
        assert "too_many_imports" not in flags

    def test_non_python_file_skips_ast_analysis(self) -> None:
        """Test that non-Python files skip AST analysis."""
        flags = compute_health_flags(Path("/tmp/test.js"), ".js", 25, 0, 0)
        # Should have basic flag but no AST-based flags
        assert flags.get("too_many_functions") is True
        assert "has_long_functions" not in flags
        assert "deep_nesting" not in flags


class TestHealthFlagsWithRealFiles:
    """Test health flags with actual Python files."""

    def test_has_long_functions_flag_with_long_function(self) -> None:
        """Test has_long_functions flag detected for file with long function."""
        # Create a Python file with a long function (>50 lines)
        long_function = "def long_func():\n" + "    pass\n" * 55
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(long_function)
            f.flush()

            flags = compute_health_flags(Path(f.name), ".py", 1, 0, 0)
            assert flags.get("has_long_functions") is True

    def test_has_large_classes_flag_with_many_methods(self) -> None:
        """Test has_large_classes flag detected for class with many methods."""
        # Create a class with >10 methods
        methods = "\n".join([f"    def method_{i}(self):\n        pass\n" for i in range(12)])
        code = f"class LargeClass:\n{methods}"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            flags = compute_health_flags(Path(f.name), ".py", 0, 1, 0)
            assert flags.get("has_large_classes") is True

    def test_deep_nesting_flag_with_nested_code(self) -> None:
        """Test deep_nesting flag detected for deeply nested code."""
        # Create code with >3 levels of nesting
        code = """
def func():
    if True:
        for i in range(10):
            while True:
                if True:  # 4 levels deep
                    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            flags = compute_health_flags(Path(f.name), ".py", 1, 0, 0)
            assert flags.get("deep_nesting") is True

    def test_no_ast_flags_for_clean_code(self) -> None:
        """Test no AST flags for clean, well-structured code."""
        code = """
def short_func():
    return "hello"

class SmallClass:
    def method1(self):
        pass

    def method2(self):
        pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            flags = compute_health_flags(Path(f.name), ".py", 1, 1, 0)
            # Should have no flags
            assert "has_long_functions" not in flags
            assert "has_large_classes" not in flags
            assert "deep_nesting" not in flags


class TestThresholdValues:
    """Test the threshold constant values."""

    def test_max_function_lines_is_50(self) -> None:
        """Test max_function_lines threshold is 50."""
        assert CODE_HEALTH_THRESHOLDS["max_function_lines"] == 50

    def test_max_class_methods_is_10(self) -> None:
        """Test max_class_methods threshold is 10."""
        assert CODE_HEALTH_THRESHOLDS["max_class_methods"] == 10

    def test_max_nesting_depth_is_3(self) -> None:
        """Test max_nesting_depth threshold is 3."""
        assert CODE_HEALTH_THRESHOLDS["max_nesting_depth"] == 3

    def test_max_functions_per_file_is_20(self) -> None:
        """Test max_functions_per_file threshold is 20."""
        assert CODE_HEALTH_THRESHOLDS["max_functions_per_file"] == 20

    def test_max_classes_per_file_is_5(self) -> None:
        """Test max_classes_per_file threshold is 5."""
        assert CODE_HEALTH_THRESHOLDS["max_classes_per_file"] == 5

    def test_max_imports_is_30(self) -> None:
        """Test max_imports threshold is 30."""
        assert CODE_HEALTH_THRESHOLDS["max_imports"] == 30
