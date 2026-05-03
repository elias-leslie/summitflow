"""Graphify command and artifact helpers."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..utils import safe_subprocess

_GRAPHIFY_TIMEOUT_SECONDS = 180
_DEFAULT_GRAPHIFY_BIN = Path.home() / ".local" / "bin" / "graphify"
_SEMANTIC_FILE_TYPES = {"document", "paper", "image", "video", "audio"}
_CODE_ONLY_FILE_TYPES = {"code", "rationale", "community"}
_CDN_MARKERS = ("https://unpkg.com", "https://cdn.", "https://cdn.jsdelivr.net")
_CODE_REFRESH_DIAGNOSTICS = {"graph_missing", "graph_stale", "graph_unreadable", "detect_missing"}
_CODE_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".cxx",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}
_SOURCE_EXCLUDE_DIRS = {
    ".git",
    ".gitnexus",
    ".jj",
    ".mypy_cache",
    ".next",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".st",
    ".summitflow",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "data",
    "dist",
    "graphify-out",
    "htmlcov",
    "node_modules",
    "out",
    "references",
}
_SENSITIVE_FILENAMES = {".env", ".env.local", "credentials.json", "secrets.json"}
_SENSITIVE_PATH_PARTS = ("credential", "secret", "token")
_SENSITIVE_SUFFIXES = {".key", ".pem"}


@dataclass(frozen=True)
class GraphifyCommandResult:
    """Measured Graphify command output."""

    command: list[str]
    output: str
    elapsed_ms: int
    output_chars: int
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """Estimate tokens cheaply for command-output accounting."""
    return (len(text) + 3) // 4 if text else 0


def graphify_bin() -> str:
    """Resolve Graphify executable."""
    configured = os.getenv("GRAPHIFY_BIN")
    if configured:
        return configured
    found = shutil.which("graphify")
    if found:
        return found
    if _DEFAULT_GRAPHIFY_BIN.exists():
        return str(_DEFAULT_GRAPHIFY_BIN)
    raise FileNotFoundError("graphify executable not found")


def graphify_dir(root: Path) -> Path:
    """Return Graphify output directory for a project root."""
    return root / "graphify-out"


def graphify_graph_path(root: Path) -> Path:
    """Return graph.json path for a project root."""
    return graphify_dir(root) / "graph.json"


def _mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _detect_path(out: Path) -> Path:
    return out / ".graphify_detect.json"


def _detect_summary(out: Path) -> dict[str, int]:
    detect = _detect_path(out)
    if not detect.exists():
        return {}
    try:
        data = _read_json(detect)
    except (OSError, json.JSONDecodeError):
        return {}
    files = data.get("files", {})
    if not isinstance(files, dict):
        return {}
    return {
        str(category): len(paths)
        for category, paths in files.items()
        if isinstance(paths, list) and paths
    }


def _source_files(out: Path) -> list[str]:
    detect = _detect_path(out)
    if not detect.exists():
        return []
    try:
        data = _read_json(detect)
    except (OSError, json.JSONDecodeError):
        return []
    files = data.get("files", {})
    if not isinstance(files, dict):
        return []
    paths: list[str] = []
    for category_paths in files.values():
        if isinstance(category_paths, list):
            paths.extend(str(path) for path in category_paths)
    return paths


def _normalize_source_path(root: Path, raw_path: str) -> str | None:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _detected_source_set(root: Path, out: Path) -> set[str]:
    paths: set[str] = set()
    for raw_path in _source_files(out):
        normalized = _normalize_source_path(root, raw_path)
        if normalized and (root / normalized).suffix.lower() in _CODE_SOURCE_SUFFIXES:
            paths.add(normalized)
    return paths


def _is_supported_source(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    name = parts[-1]
    if name in _SENSITIVE_FILENAMES or path.suffix.lower() in _SENSITIVE_SUFFIXES:
        return False
    if any(marker in part for part in parts for marker in _SENSITIVE_PATH_PARTS):
        return False
    return path.suffix.lower() in _CODE_SOURCE_SUFFIXES


def _current_source_set(root: Path) -> set[str]:
    paths: set[str] = set()
    if not root.exists():
        return paths
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        try:
            relative_parts = current_dir.resolve().relative_to(root.resolve()).parts
        except ValueError:
            relative_parts = ()
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SOURCE_EXCLUDE_DIRS
            and not (not relative_parts and name == "backups")
            and not (name.startswith(".") and name != ".github")
        ]
        for filename in filenames:
            path = current_dir / filename
            if not _is_supported_source(path):
                continue
            try:
                paths.add(path.resolve().relative_to(root.resolve()).as_posix())
            except ValueError:
                continue
    return paths


def _graph_source_set(root: Path, nodes: list[dict[str, Any]], out: Path) -> set[str]:
    paths: set[str] = set()
    for node in nodes:
        raw_path = node.get("source_file")
        file_type = str(node.get("file_type") or "")
        if file_type not in {"code", "rationale"} or not raw_path:
            continue
        normalized = _normalize_source_path(root, str(raw_path))
        if normalized:
            paths.add(normalized)
    return paths or _detected_source_set(root, out)


def _changed_files_since(root: Path, out: Path, nodes: list[dict[str, Any]], graph_mtime: datetime | None) -> tuple[int, list[str]]:
    if graph_mtime is None:
        return 0, []
    detected_sources = _graph_source_set(root, nodes, out)
    current_sources = _current_source_set(root)
    changed: list[str] = []
    graph_ts = graph_mtime.timestamp()
    for rel_path in sorted(current_sources & detected_sources):
        path = root / rel_path
        try:
            if path.exists() and path.stat().st_mtime > graph_ts:
                changed.append(rel_path)
        except OSError:
            continue
    added = sorted(current_sources - detected_sources)
    deleted = sorted(detected_sources - current_sources)
    sample = changed[:6] + [f"added:{path}" for path in added[:3]] + [f"deleted:{path}" for path in deleted[:3]]
    return len(changed) + len(added) + len(deleted), sample[:12]


def graphify_report_path(root: Path) -> Path:
    """Return GRAPH_REPORT.md path for a project root."""
    return graphify_dir(root) / "GRAPH_REPORT.md"


def _html_uses_cdn(graph_html: Path) -> bool:
    if not graph_html.exists():
        return False
    try:
        prefix = graph_html.read_text(encoding="utf-8", errors="ignore")[:4096]
    except OSError:
        return False
    return any(marker in prefix for marker in _CDN_MARKERS)


def graphify_status(project_id: str, root: Path) -> dict[str, Any]:
    """Build complete Graphify status and diagnostic payload."""
    out = graphify_dir(root)
    graph_json = out / "graph.json"
    graph_html = out / "graph.html"
    report = out / "GRAPH_REPORT.md"
    graph_updated_at = _mtime(graph_json)

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    unreadable_error: str | None = None
    if graph_json.exists():
        try:
            data = _read_json(graph_json)
            raw_nodes = data.get("nodes", [])
            raw_links = data.get("links", data.get("edges", []))
            nodes = raw_nodes if isinstance(raw_nodes, list) else []
            links = raw_links if isinstance(raw_links, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            unreadable_error = str(exc)

    file_type_counts: dict[str, int] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        file_type = str(node.get("file_type") or "unknown")
        file_type_counts[file_type] = file_type_counts.get(file_type, 0) + 1

    communities = {
        node.get("community")
        for node in nodes
        if isinstance(node, dict) and node.get("community") is not None
    }
    semantic_node_count = sum(
        count for file_type, count in file_type_counts.items() if file_type not in _CODE_ONLY_FILE_TYPES
    )
    detect_summary = _detect_summary(out)
    semantic_source_count = sum(detect_summary.get(file_type, 0) for file_type in _SEMANTIC_FILE_TYPES)
    changed_count, changed_sample = _changed_files_since(root, out, nodes, graph_updated_at)
    html_uses_cdn = _html_uses_cdn(graph_html)
    graph_exists = graph_json.exists()
    detect_exists = _detect_path(out).exists()
    semantic_coverage = (
        "semantic"
        if semantic_node_count
        else "code_only_with_semantic_sources"
        if semantic_source_count
        else "code_only"
    )
    diagnostics: list[str] = []
    if not graph_exists:
        diagnostics.append("graph_missing")
    if graph_exists and not detect_exists:
        diagnostics.append("detect_missing")
    if changed_count:
        diagnostics.append("graph_stale")
    if semantic_source_count and semantic_node_count == 0:
        diagnostics.append("semantic_sources_not_extracted")
    if html_uses_cdn:
        diagnostics.append("html_uses_external_cdn")
    if unreadable_error:
        diagnostics.append("graph_unreadable")

    return {
        "project_id": project_id,
        "root_path": str(root),
        "graph_exists": graph_exists,
        "html_available": graph_html.exists(),
        "report_available": report.exists(),
        "node_count": len(nodes),
        "edge_count": len(links),
        "community_count": len(communities),
        "graph_updated_at": graph_updated_at,
        "html_updated_at": _mtime(graph_html),
        "report_updated_at": _mtime(report),
        "html_url": f"/api/projects/{project_id}/graphify/html" if graph_html.exists() else None,
        "report_url": f"/api/projects/{project_id}/graphify/report" if report.exists() else None,
        "code_node_count": file_type_counts.get("code", 0),
        "rationale_node_count": file_type_counts.get("rationale", 0),
        "semantic_node_count": semantic_node_count,
        "file_type_counts": file_type_counts,
        "detected_source_counts": detect_summary,
        "semantic_source_count": semantic_source_count,
        "semantic_coverage": semantic_coverage,
        "graph_stale": changed_count > 0,
        "changed_files_since_graph": changed_count,
        "changed_files_sample": changed_sample,
        "graph_size_bytes": _size(graph_json),
        "html_size_bytes": _size(graph_html),
        "report_size_bytes": _size(report),
        "html_uses_cdn": html_uses_cdn,
        "diagnostics": diagnostics,
        "unreadable_error": unreadable_error,
    }


def graphify_code_refresh_needed(status: dict[str, Any]) -> bool:
    """Return True when a code-only Graphify refresh can fix agent-facing staleness."""
    diagnostics = {str(item) for item in status.get("diagnostics", [])}
    return bool(diagnostics & _CODE_REFRESH_DIAGNOSTICS)


def run_graphify(root: Path, args: list[str], *, timeout: int = _GRAPHIFY_TIMEOUT_SECONDS) -> GraphifyCommandResult:
    """Run Graphify in a project root and capture measured output."""
    command = [graphify_bin(), *args]
    start = time.perf_counter()
    result = safe_subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    if result.returncode != 0:
        raise RuntimeError(output[-4000:] or f"graphify exited with {result.returncode}")
    return GraphifyCommandResult(
        command=command,
        output=output,
        elapsed_ms=elapsed_ms,
        output_chars=len(output),
        estimated_tokens=estimate_tokens(output),
    )


def query_graph(root: Path, question: str, *, budget: int = 1200, dfs: bool = False) -> GraphifyCommandResult:
    """Run Graphify query for a project graph."""
    args = ["query", question, "--budget", str(budget), "--graph", str(graphify_graph_path(root))]
    if dfs:
        args.append("--dfs")
    return run_graphify(root, args)


def path_graph(root: Path, source: str, target: str) -> GraphifyCommandResult:
    """Run Graphify path for a project graph."""
    return run_graphify(root, ["path", source, target, "--graph", str(graphify_graph_path(root))])


def explain_graph(root: Path, node: str) -> GraphifyCommandResult:
    """Run Graphify explain for a project graph."""
    return run_graphify(root, ["explain", node, "--graph", str(graphify_graph_path(root))])


def refresh_graph(root: Path, *, timeout: int = _GRAPHIFY_TIMEOUT_SECONDS) -> GraphifyCommandResult:
    """Refresh Graphify code graph for a project root."""
    return run_graphify(root, ["update", str(root)], timeout=timeout)
