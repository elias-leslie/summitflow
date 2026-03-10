"""Shared constants for explorer and codebase scanning.

Merged patterns from executor.py and files.py for consistent directory exclusion.
"""

from __future__ import annotations

# Scan status values
SCAN_STATUS_IDLE = "idle"
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_COMPLETED = "completed"
SCAN_STATUS_FAILED = "failed"

# Extensions known to be binary
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
        ".woff", ".woff2", ".ttf", ".eot",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
        ".sqlite", ".db",
    }
)

# Map file extensions to CodeMirror language identifiers
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".xml": "xml",
    ".svg": "xml",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".toml": "toml",
    ".dockerfile": "dockerfile",
}

# Sensitive directories that should never be browsed
FORBIDDEN_DIRS: frozenset[str] = frozenset({".git", ".env"})

# Directories to skip during scanning (union of all skip patterns)
SKIP_DIRS: frozenset[str] = frozenset(
    {
        # Version control
        ".git",
        # Package/dependency directories
        "node_modules",
        ".venv",
        "venv",
        # Build/output directories
        ".next",
        "dist",
        "build",
        # Cache directories
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        # Data directories (project-specific)
        "data",
        "solution_state",
        ".beads",
        # Backup and external content
        "backups",
        "references",
        "logs",
        # Test artifacts
        "test-results",
        # IDE/editor
        ".idea",
        ".vscode",
    }
)
