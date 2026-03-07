"""Constants for file scanner - thresholds, patterns, and configuration.

Extracted from files.py to keep the scanner class focused on scanning logic.
"""

from __future__ import annotations

import re

# File extensions to skip
SKIP_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".lock",
}

# Bloat thresholds by extension: (warning_loc, critical_loc)
BLOAT_THRESHOLDS: dict[str, tuple[int, int]] = {
    ".py": (500, 1000),
    ".ts": (400, 800),
    ".tsx": (300, 600),
    ".js": (400, 800),
    ".jsx": (300, 600),
    ".sql": (200, 500),
    ".md": (500, 1000),
    ".css": (400, 800),
    ".scss": (400, 800),
}

STALE_THRESHOLD_DAYS = 90

# Schema version for metadata - increment when adding new fields
# v4: Added symbol_count and symbol_kinds to file metadata
METADATA_SCHEMA_VERSION = 4

SYMBOL_INDEX_EXTENSIONS = {".py", ".ts", ".tsx"}

# Regex patterns for complexity metrics
FUNCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*def\s+", re.MULTILINE),
    ".ts": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".tsx": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".js": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".jsx": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
}

CLASS_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*class\s+\w+", re.MULTILINE),
    ".ts": re.compile(r"class\s+\w+", re.MULTILINE),
    ".tsx": re.compile(r"class\s+\w+", re.MULTILINE),
    ".js": re.compile(r"class\s+\w+", re.MULTILINE),
    ".jsx": re.compile(r"class\s+\w+", re.MULTILINE),
}

IMPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*(import|from)\s+", re.MULTILINE),
    ".ts": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".tsx": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".js": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".jsx": re.compile(r"^\s*import\s+", re.MULTILINE),
}

# Refactor priority thresholds
REFACTOR_HIGH_COMPLEXITY = 15
REFACTOR_HIGH_LINES = 500
REFACTOR_MEDIUM_COMPLEXITY = 10
REFACTOR_MEDIUM_LINES = 300

# Magic string patterns for detection - patterns that should be constants or config
MAGIC_STRING_PATTERNS: dict[str, re.Pattern[str]] = {
    # Project-specific names that should be configurable
    "project_names": re.compile(
        r"\b(summitflow|portfolio-ai|SummitFlow)\b",
        re.IGNORECASE,
    ),
    # Hardcoded paths (absolute or well-known)
    "hardcoded_paths": re.compile(
        r'["\'](?:/home/\w+|/Users/\w+|/var/|/tmp/|/opt/|C:\\|D:\\)[^"\']*["\']',
    ),
    # Hardcoded URLs that might need to be configurable
    "hardcoded_urls": re.compile(
        r'["\']https?://(?:localhost|127\.0\.0\.1|192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)[^"\']*["\']',
    ),
    # Legacy/deprecated model names
    "legacy_models": re.compile(
        r"\b(claude-3-|gemini-2\.[05]|gpt-3\.5|gpt-4-(?!turbo))\w*\b",
    ),
}

# Globs to exclude from magic string detection
MAGIC_STRING_EXCLUDE_PATTERNS: dict[str, list[str]] = {
    # Don't flag project names in documentation/tests
    "project_names": ["*.md", "*test*", "*spec*", "CLAUDE.md", "README*"],
    # Don't flag hardcoded paths in config files
    "hardcoded_paths": ["*.json", "*.yaml", "*.yml", "*.toml", "*.md"],
    # Don't flag local URLs in test files
    "hardcoded_urls": ["*test*", "*spec*", "*.md"],
    # Flag legacy models everywhere
    "legacy_models": [],
}

# Compatibility cruft patterns - indicators of technical debt
COMPAT_CRUFT_PATTERNS: dict[str, re.Pattern[str]] = {
    # Backwards compatibility comments/annotations
    "compat_comments": re.compile(
        r"#\s*(backward|backwards|compat|for\s+compat|legacy|alias|re-export)",
        re.IGNORECASE,
    ),
    # Deprecated markers
    "deprecated_markers": re.compile(
        r"#\s*(DEPRECATED|@deprecated|deprecated:)",
        re.IGNORECASE,
    ),
    # Legacy/old variable naming patterns
    "legacy_vars": re.compile(
        r"\b(\w+_old|\w+_legacy|\w+_deprecated|old_\w+|legacy_\w+|deprecated_\w+)\b",
    ),
    # Stale TODO/FIXME comments (potential technical debt)
    "stale_todos": re.compile(
        r"#\s*(TODO|FIXME|XXX|HACK)\b",
    ),
    # Alias exports/re-exports for compatibility
    "alias_exports": re.compile(
        r"^\s*\w+\s*=\s*\w+\s*#.*(?:alias|compat|legacy)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# Globs to exclude from compat cruft detection
COMPAT_CRUFT_EXCLUDE_PATTERNS: dict[str, list[str]] = {
    # Don't flag compat comments in tests (often intentional)
    "compat_comments": ["*test*", "*spec*"],
    # Deprecated markers should be flagged everywhere
    "deprecated_markers": [],
    # Don't flag legacy vars in migrations or tests
    "legacy_vars": ["*migration*", "*test*", "*spec*"],
    # Don't flag TODOs in tests (often intentional placeholders)
    "stale_todos": [],
    # Don't flag alias exports in __init__.py (often intentional)
    "alias_exports": ["__init__.py"],
}

# Code health thresholds for flag computation
CODE_HEALTH_THRESHOLDS = {
    "max_function_lines": 50,  # Functions longer than this get flagged
    "max_class_methods": 10,  # Classes with more methods get flagged
    "max_nesting_depth": 3,  # Nesting deeper than this gets flagged
    "max_functions_per_file": 20,  # Files with more functions get flagged
    "max_classes_per_file": 5,  # Files with more classes get flagged
    "max_imports": 30,  # Files with more imports get flagged
}
