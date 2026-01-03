"""Tests for AST analyzer."""

import pytest
from app.services.explorer.analyzers.ast_analyzer import parse_python_file


class TestParsePythonFile:
    """Tests for parse_python_file function."""

    def test_parse_simple_function(self, tmp_path):
        """Test parsing a file with a simple function."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        file = tmp_path / "simple.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert len(result["functions"]) == 1
        func = result["functions"][0]
        assert func["name"] == "hello"
        assert func["params"] == ["name"]
        assert func["has_docstring"] is True
        assert func["lines"] > 0

    def test_parse_async_function(self, tmp_path):
        """Test parsing async function."""
        code = """
async def fetch(url):
    return await get(url)
"""
        file = tmp_path / "async.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert len(result["functions"]) == 1
        assert result["functions"][0]["name"] == "fetch"
        assert result["functions"][0]["params"] == ["url"]

    def test_parse_class_with_methods(self, tmp_path):
        """Test parsing a class with methods."""
        code = '''
class Calculator:
    """A simple calculator."""

    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
'''
        file = tmp_path / "class.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "Calculator"
        assert "add" in cls["methods"]
        assert "subtract" in cls["methods"]
        assert cls["has_docstring"] is True

    def test_parse_nesting_depth(self, tmp_path):
        """Test calculating max nesting depth."""
        code = """
def deeply_nested():
    if True:
        for i in range(10):
            while True:
                if False:
                    pass
"""
        file = tmp_path / "nested.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert result["max_nesting"] == 4  # if > for > while > if

    def test_parse_no_nesting(self, tmp_path):
        """Test file with no nesting."""
        code = """
x = 1
y = 2
"""
        file = tmp_path / "flat.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert result["max_nesting"] == 0

    def test_parse_function_params(self, tmp_path):
        """Test parsing various parameter types."""
        code = """
def complex_params(a, b, /, c, d=1, *args, e, f=2, **kwargs):
    pass
"""
        file = tmp_path / "params.py"
        file.write_text(code)

        result = parse_python_file(file)

        params = result["functions"][0]["params"]
        assert "a" in params
        assert "b" in params
        assert "c" in params
        assert "*args" in params
        assert "e" in params
        assert "**kwargs" in params

    def test_parse_no_docstring(self, tmp_path):
        """Test function without docstring."""
        code = """
def no_docs():
    return 42
"""
        file = tmp_path / "nodocs.py"
        file.write_text(code)

        result = parse_python_file(file)

        assert result["functions"][0]["has_docstring"] is False

    def test_parse_empty_file(self, tmp_path):
        """Test parsing empty file."""
        file = tmp_path / "empty.py"
        file.write_text("")

        result = parse_python_file(file)

        assert result["functions"] == []
        assert result["classes"] == []
        assert result["max_nesting"] == 0

    def test_parse_nonexistent_file(self):
        """Test parsing non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            parse_python_file("/nonexistent/file.py")

    def test_parse_syntax_error(self, tmp_path):
        """Test parsing file with syntax error raises error."""
        file = tmp_path / "bad.py"
        file.write_text("def broken(")

        with pytest.raises(SyntaxError):
            parse_python_file(file)
