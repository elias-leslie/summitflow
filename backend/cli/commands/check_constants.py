"""Static lookup tables and selection maps for the st check command."""

from __future__ import annotations

_TOOL_FILE_SUFFIXES: dict[str, set[str]] = {
    "pytest": {".py", ".pyi"},
    "types": {".py", ".pyi"},
    "ruff": {".py", ".pyi"},
    "biome": {
        ".css",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".md",
        ".mdx",
        ".scss",
        ".ts",
        ".tsx",
    },
    "tsc": {".js", ".jsx", ".ts", ".tsx"},
    "vitest": {".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx", ".vue"},
    "sqlfluff": {".sql"},
    "squawk": {".sql"},
}

_TOOL_CONFIG_PATHS: dict[str, set[str]] = {
    "pytest": {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"},
    "biome": {
        "biome.json",
        "biome.jsonc",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    },
    "tsc": {
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "tsconfig.build.json",
        "yarn.lock",
    },
    "vitest": {
        "bun.lock",
        "bun.lockb",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "vite.config.js",
        "vite.config.mjs",
        "vite.config.mts",
        "vite.config.ts",
        "vitest.config.js",
        "vitest.config.mjs",
        "vitest.config.mts",
        "vitest.config.ts",
        "vitest.workspace.ts",
        "yarn.lock",
    },
}

# Data files a Python module can load by name; a change to one counts as a
# change to the modules that name it (see check_changed._data_file_referrers).
_DATA_FILE_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
# Directories never scanned for Python files that name a data file.
_SCAN_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
}

_CODEQL_PAGE_SIZE = 100
_FIX_ARGS: dict[str, list[str]] = {"ruff": ["--fix"], "biome": ["--write"]}

_TOOL_SELECTIONS: dict[str, tuple[tuple[str, ...], bool]] = {
    "--fix": (("ruff", "biome"), True),
    "--check": (("ruff", "types", "pytest", "biome", "tsc", "vitest", "security"), False),
    "-c": (("ruff", "types", "pytest", "biome", "tsc", "vitest", "security"), False),
    "--quick": (("ruff", "types", "pytest", "biome", "tsc", "vitest", "gitleaks"), False),
    "-q": (("ruff", "types", "pytest", "biome", "tsc", "vitest", "gitleaks"), False),
    "--frontend-only": (("biome", "tsc", "vitest"), False),
    "--fe": (("biome", "tsc", "vitest"), False),
}
