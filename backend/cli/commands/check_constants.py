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
    "vitest": {".js", ".jsx", ".ts", ".tsx"},
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
        "package.json",
        "pnpm-lock.yaml",
        "vite.config.ts",
        "vitest.config.ts",
        "yarn.lock",
    },
}

_CODEQL_PAGE_SIZE = 100
_FIX_ARGS: dict[str, list[str]] = {"ruff": ["--fix"], "biome": ["--write"]}

_TOOL_SELECTIONS: dict[str, tuple[tuple[str, ...], bool]] = {
    "--fix": (("ruff", "biome"), True),
    "--check": (("ruff", "types", "pytest", "biome", "tsc", "vitest"), False),
    "-c": (("ruff", "types", "pytest", "biome", "tsc", "vitest"), False),
    "--quick": (("ruff", "types", "pytest", "biome", "tsc"), False),
    "-q": (("ruff", "types", "pytest", "biome", "tsc"), False),
    "--frontend-only": (("biome", "tsc", "vitest"), False),
    "--fe": (("biome", "tsc", "vitest"), False),
}
