"""Graphify CLI wrappers for agent topology work."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from app.services.context_gatherer.token_utils import truncate_to_tokens
from app.services.graphify_tools import (
    GraphifyCommandResult,
    estimate_tokens,
    explain_graph,
    graphify_code_refresh_needed,
    graphify_report_path,
    graphify_status,
    path_graph,
    query_graph,
    refresh_graph,
    run_graphify,
)

from ..config import get_config
from ..details import display_path, strip_ansi, summary_hint, write_details
from ..output import output_json
from ._projects_helpers import projects_api

app = typer.Typer(help="Graphify topology and profiling helpers")

_GITNEXUS_PACKAGE = "gitnexus"
_GITNEXUS_NPX_SPEC = "gitnexus@latest"
_FALLOW_PACKAGE = "fallow"
_FALLOW_MODES = {"audit", "changed", "health", "plugins", "flags", "dead-code", "dupes"}
_GRAPH_REFRESH_PROGRESS_DELAY_SECONDS = 1.5
_DOCTOR_BLOCKING_DIAGNOSTICS = {"graph_missing", "graph_stale", "graph_unreadable", "detect_missing"}
_DEFAULT_CONTEXT_QUESTION = "What are the central modules, coupling points, and architecture communities in this project?"
_SEMANTIC_BATCH_AGENT = "graphify-semantic-extractor"
_SEMANTIC_BATCH_MAX_CHARS = 48_000
_SEMANTIC_BATCH_MAX_FILES = 8
_SEMANTIC_TEXT_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".json", ".yaml", ".yml", ".csv", ".svg"}
_SEMANTIC_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_SEMANTIC_SOURCE_TYPES = {"document", "paper", "image", "video", "audio"}
_CODE_ONLY_NODE_TYPES = {"code", "rationale", "community"}


def _project_payload(project_id: str) -> dict[str, Any]:
    project = projects_api("GET", f"/{project_id}")
    if not isinstance(project, dict):
        raise typer.BadParameter(f"Project '{project_id}' not found")
    return project


def _all_projects() -> list[dict[str, Any]]:
    projects = projects_api("GET")
    if not isinstance(projects, list):
        return []
    return projects


def _project_id(value: str | None) -> str:
    return value or get_config().project_id


def _root_for_project(project_id: str) -> Path:
    project = _project_payload(project_id)
    return _root_from_project_payload(project_id, project)


def _root_from_project_payload(project_id: str, project: dict[str, Any]) -> Path:
    root_path = project.get("root_path")
    if not root_path:
        raise typer.BadParameter(f"Project '{project_id}' has no root_path configured")
    return Path(str(root_path)).expanduser().resolve()


def _emit_status(message: str) -> None:
    typer.echo(message, err=True)


def _start_delayed_status_timer(message: str) -> threading.Timer:
    timer = threading.Timer(_GRAPH_REFRESH_PROGRESS_DELAY_SECONDS, _emit_status, args=(message,))
    timer.daemon = True
    timer.start()
    return timer


def _status_for_project(
    project_id: str,
    *,
    auto_refresh: bool = True,
    action: str = "status",
    create_missing: bool = True,
) -> dict[str, Any]:
    return _status_for_project_root(
        project_id,
        _root_for_project(project_id),
        auto_refresh=auto_refresh,
        action=action,
        create_missing=create_missing,
    )


def _status_for_project_root(
    project_id: str,
    root: Path,
    *,
    auto_refresh: bool = True,
    action: str = "status",
    create_missing: bool = True,
) -> dict[str, Any]:
    status = graphify_status(project_id, root)
    if not create_missing and not status.get("graph_exists"):
        return status
    if not auto_refresh or not graphify_code_refresh_needed(status):
        return status

    timer = _start_delayed_status_timer(f"st graph: refreshing Graphify code graph before {action}.")
    try:
        refresh_graph(root)
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        timer.cancel()
        if not status.get("graph_exists") or "graph_unreadable" in status.get("diagnostics", []):
            raise
        _emit_status(f"st graph: auto-refresh failed before {action}; using existing graph. reason={exc}")
        return status
    finally:
        timer.cancel()

    _emit_status(f"st graph: refreshed Graphify code graph before {action}.")
    return graphify_status(project_id, root)


def _fresh_root_for_project(project_id: str, *, action: str) -> Path:
    root = _root_for_project(project_id)
    status = graphify_status(project_id, root)
    if not graphify_code_refresh_needed(status):
        return root

    timer = _start_delayed_status_timer(f"st graph: refreshing Graphify code graph before {action}.")
    try:
        refresh_graph(root)
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        timer.cancel()
        if not status.get("graph_exists") or "graph_unreadable" in status.get("diagnostics", []):
            raise
        _emit_status(f"st graph: auto-refresh failed before {action}; using existing graph. reason={exc}")
        return root
    finally:
        timer.cancel()

    _emit_status(f"st graph: refreshed Graphify code graph before {action}.")
    return root


def _command_payload(result: GraphifyCommandResult) -> dict[str, Any]:
    return asdict(result)


def _issue_count(status: dict[str, Any]) -> int:
    return sum(1 for item in status.get("diagnostics", []) if item in _DOCTOR_BLOCKING_DIAGNOSTICS)


def _warning_count(status: dict[str, Any]) -> int:
    return sum(1 for item in status.get("diagnostics", []) if item not in _DOCTOR_BLOCKING_DIAGNOSTICS)


def _compact_status_lines(status: dict[str, Any]) -> list[str]:
    diagnostics = status.get("diagnostics") or []
    return [
        "## Graph Status",
        f"- project: {status.get('project_id', '-')}",
        f"- nodes: {status.get('node_count', 0)}",
        f"- edges: {status.get('edge_count', 0)}",
        f"- communities: {status.get('community_count', 0)}",
        f"- semantic_coverage: {status.get('semantic_coverage', '-')}",
        f"- diagnostics: {', '.join(str(item) for item in diagnostics) if diagnostics else '-'}",
        f"- graph_stale: {str(status.get('graph_stale', False)).lower()}",
    ]


def _report_context(root: Path, *, line_limit: int = 80) -> str:
    report = graphify_report_path(root)
    if not report.exists():
        return "## Graph Report\n- missing"
    lines = report.read_text(encoding="utf-8", errors="replace").splitlines()
    selected: list[str] = []
    capture = False
    for line in lines:
        if line.startswith("# Graph Report") or line.startswith("## Summary") or line.startswith("## Community Hubs"):
            capture = True
        elif line.startswith("## ") and selected and not line.startswith("## Community Hubs"):
            capture = False
        if capture:
            selected.append(line)
        if len(selected) >= line_limit:
            break
    if not selected:
        selected = lines[:line_limit]
    return "\n".join(selected)


def _graph_context_payload(project_id: str, root: Path, status: dict[str, Any], *, budget: int) -> dict[str, Any]:
    report_context = _report_context(root)
    body = "\n".join(
        [
            "Graphify Context",
            "",
            "Use st graph query/path/explain for topology. Use st search for exact source facts.",
            "",
            *_compact_status_lines(status),
            "",
            report_context,
            "",
            "## Useful Commands",
            f"- st graph query --project {project_id} --budget 1200 \"{_DEFAULT_CONTEXT_QUESTION}\"",
            f"- st graph explain --project {project_id} \"<node>\"",
            f"- st graph path --project {project_id} \"<source>\" \"<target>\"",
            f"- st search -P {project_id} \"<symbol or route>\"",
        ]
    )
    truncated = truncate_to_tokens(body, budget)
    return {
        "project_id": project_id,
        "prompt_context": truncated,
        "metadata": {
            "budget": budget,
            "estimated_tokens": estimate_tokens(truncated),
            "diagnostics": status.get("diagnostics", []),
            "semantic_coverage": status.get("semantic_coverage"),
            "graph_stale": status.get("graph_stale", False),
            "node_count": status.get("node_count", 0),
            "edge_count": status.get("edge_count", 0),
            "community_count": status.get("community_count", 0),
        },
    }


def _semantic_refresh_prompt(project_id: str, root: Path, status: dict[str, Any]) -> str:
    diagnostics = ", ".join(str(item) for item in status.get("diagnostics", [])) or "-"
    return f"""Refresh Graphify semantic coverage for project `{project_id}` at `{root}`.

Use local project rules. Keep work scoped to Graphify artifacts and diagnostics.

Required workflow:
1. Run `st pulse --gate`.
2. Run `st graph status --project {project_id}`. If graph is stale/missing/unreadable, run `st graph refresh --project {project_id}` and re-check.
3. Inspect `graphify-out/.graphify_detect.json`. Process only non-code semantic sources: document, paper, image, video, audio. Current status diagnostics: {diagnostics}.
4. Use the Graphify skill extraction rules for semantic nodes/edges/hyperedges. Prefer Gemini via Agent Hub for semantic extraction when model calls are needed.
5. Merge semantic results into `graphify-out/graph.json`, regenerate `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.html`, then run `st graph status --project {project_id}`.
6. Keep stdout compact. Put large logs under `.dev-tools/`.

Do not perform unrelated refactors. Do not edit source code unless needed to repair Graphify tooling itself.
"""


def _semantic_sources(root: Path) -> list[tuple[str, Path]]:
    detect_path = root / "graphify-out" / ".graphify_detect.json"
    if not detect_path.exists():
        return []
    try:
        detect = json.loads(detect_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    files = detect.get("files", {})
    if not isinstance(files, dict):
        return []
    sources: list[tuple[str, Path]] = []
    for source_type in sorted(_SEMANTIC_SOURCE_TYPES):
        paths = files.get(source_type, [])
        if not isinstance(paths, list):
            continue
        for raw_path in paths:
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = root / path
            if path.exists() and path.is_file():
                sources.append((source_type, path.resolve()))
    return sources


def _rel_source(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _semantic_source_text(root: Path, source_type: str, path: Path) -> tuple[str, bool]:
    rel = _rel_source(root, path)
    suffix = path.suffix.lower()
    if suffix in _SEMANTIC_IMAGE_SUFFIXES:
        return f"=== {rel} ({source_type}, image attachment) ===\nUse attached image. Extract visible UI, labels, workflows, and domain concepts.", True
    if suffix in _SEMANTIC_TEXT_SUFFIXES or source_type in {"document", "paper"}:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        return f"=== {rel} ({source_type}) ===\n{content[:20_000]}", False
    return f"=== {rel} ({source_type}) ===\nBinary source. Extract only filename-level concept if content is unavailable.", False


def _semantic_batches(root: Path, sources: list[tuple[str, Path]]) -> list[list[tuple[str, Path]]]:
    batches: list[list[tuple[str, Path]]] = []
    current: list[tuple[str, Path]] = []
    current_chars = 0
    for item in sources:
        source_type, path = item
        text, _ = _semantic_source_text(root, source_type, path)
        size = len(text)
        if current and (
            len(current) >= _SEMANTIC_BATCH_MAX_FILES
            or current_chars + size > _SEMANTIC_BATCH_MAX_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _semantic_batch_prompt(root: Path, batch: list[tuple[str, Path]]) -> tuple[str, list[Path]]:
    sections: list[str] = []
    images: list[Path] = []
    source_list: list[str] = []
    for source_type, path in batch:
        rel = _rel_source(root, path)
        source_list.append(f"- {rel} ({source_type})")
        text, is_image = _semantic_source_text(root, source_type, path)
        sections.append(text)
        if is_image:
            images.append(path)
    return (
        "Extract Graphify semantic graph JSON for these non-code sources.\n"
        "Return JSON only. No markdown fences. No prose.\n\n"
        "Schema:\n"
        '{"nodes":[{"id":"source_entity","label":"Human Name","file_type":"document|paper|image|concept",'
        '"source_file":"relative/path","source_location":null}],'
        '"edges":[{"source":"node_id","target":"node_id","relation":"references|cites|conceptually_related_to|shares_data_with|semantically_similar_to",'
        '"confidence":"EXTRACTED|INFERRED|AMBIGUOUS","confidence_score":1.0,"source_file":"relative/path","source_location":null,"weight":1.0}],'
        '"hyperedges":[]}\n\n'
        "Rules:\n"
        "- Use only these source_file values:\n"
        + "\n".join(source_list)
        + "\n- Create concise nodes for decisions, workflows, requirements, risks, concepts, screens, and docs.\n"
        "- Do not duplicate AST/code nodes. Do not extract secrets or credentials.\n"
        "- Keep IDs lowercase with only a-z, 0-9, underscore.\n\n"
        + "\n\n".join(sections),
        images,
    )


def _parse_semantic_fragment(raw: str) -> dict[str, Any]:
    text = strip_ansi(raw).strip()
    if text.startswith("Error:"):
        raise RuntimeError(text)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index >= 0:
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        if isinstance(payload, dict):
            return payload
        index = text.find("{", index + 1)
    raise RuntimeError("semantic extractor returned no JSON object")


def _safe_node_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return cleaned or "semantic_node"


def _dedupe_node_id(node_id: str, used: set[str]) -> str:
    candidate = _safe_node_id(node_id)
    if candidate not in used:
        used.add(candidate)
        return candidate
    base = candidate
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    candidate = f"{base}_{index}"
    used.add(candidate)
    return candidate


def _sanitize_semantic_fragment(root: Path, batch: list[tuple[str, Path]], fragment: dict[str, Any], used: set[str]) -> dict[str, list[dict[str, Any]]]:
    allowed_sources = {_rel_source(root, path): source_type for source_type, path in batch}
    nodes: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}
    for raw_node in fragment.get("nodes", []):
        if not isinstance(raw_node, dict):
            continue
        source_file = str(raw_node.get("source_file") or "")
        if source_file not in allowed_sources:
            continue
        label = str(raw_node.get("label") or raw_node.get("id") or Path(source_file).stem)
        original_id = str(raw_node.get("id") or f"{Path(source_file).stem}_{label}")
        node_id = _dedupe_node_id(original_id, used)
        id_map[_safe_node_id(original_id)] = node_id
        file_type = str(raw_node.get("file_type") or allowed_sources[source_file])
        if file_type in _CODE_ONLY_NODE_TYPES:
            file_type = allowed_sources[source_file]
        nodes.append({
            **raw_node,
            "id": node_id,
            "label": label[:160],
            "file_type": file_type,
            "source_file": source_file,
            "source_location": raw_node.get("source_location"),
        })
    valid_ids = set(used)
    edges: list[dict[str, Any]] = []
    for raw_edge in fragment.get("edges", []):
        if not isinstance(raw_edge, dict):
            continue
        source = id_map.get(_safe_node_id(str(raw_edge.get("source") or "")), str(raw_edge.get("source") or ""))
        target = id_map.get(_safe_node_id(str(raw_edge.get("target") or "")), str(raw_edge.get("target") or ""))
        if source not in valid_ids or target not in valid_ids or source == target:
            continue
        source_file = str(raw_edge.get("source_file") or "")
        if source_file not in allowed_sources:
            source_file = next(iter(allowed_sources))
        edges.append({
            **raw_edge,
            "source": source,
            "target": target,
            "_src": source,
            "_tgt": target,
            "relation": str(raw_edge.get("relation") or "conceptually_related_to"),
            "confidence": str(raw_edge.get("confidence") or "INFERRED"),
            "confidence_score": float(raw_edge.get("confidence_score") or 0.8),
            "source_file": source_file,
            "source_location": raw_edge.get("source_location"),
            "weight": float(raw_edge.get("weight") or 1.0),
        })
    return {"nodes": nodes, "edges": edges, "hyperedges": []}


def _merge_semantic_fragments(root: Path, fragments: list[dict[str, list[dict[str, Any]]]], semantic_sources: list[tuple[str, Path]]) -> None:
    graph_path = root / "graphify-out" / "graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    semantic_rel_sources = {_rel_source(root, path) for _, path in semantic_sources}
    old_nodes = data.get("nodes", [])
    old_links = data.get("links", data.get("edges", []))
    removed_ids = {
        str(node.get("id"))
        for node in old_nodes
        if isinstance(node, dict)
        and str(node.get("file_type") or "") not in _CODE_ONLY_NODE_TYPES
        and str(node.get("source_file") or "") in semantic_rel_sources
    }
    nodes = [
        node for node in old_nodes
        if not (isinstance(node, dict) and str(node.get("id")) in removed_ids)
    ]
    links = [
        edge for edge in old_links
        if isinstance(edge, dict)
        and str(edge.get("source") or edge.get("_src") or "") not in removed_ids
        and str(edge.get("target") or edge.get("_tgt") or "") not in removed_ids
        and str(edge.get("source_file") or "") not in semantic_rel_sources
    ]
    for fragment in fragments:
        nodes.extend(fragment["nodes"])
        links.extend(fragment["edges"])
    data["nodes"] = nodes
    data["links"] = links
    if "edges" in data:
        data.pop("edges", None)
    graph_path.write_text(json.dumps(data), encoding="utf-8")


def _run_semantic_refresh_batches(
    project_id: str,
    root: Path,
    *,
    agent: str | None,
    model: str | None,
    timeout: int,
) -> int:
    if not agent:
        raise typer.BadParameter("semantic-refresh requires --agent with a purpose-built Agent Hub agent slug")
    status = _status_for_project_root(project_id, root, auto_refresh=True, action="semantic-refresh")
    sources = _semantic_sources(root)
    if not sources:
        print(f"GRAPH_SEMANTIC_REFRESH:OK:0|semantic=0/0|diagnostics={','.join(status.get('diagnostics', [])) or '-'}")
        return 0
    batches = _semantic_batches(root, sources)
    st_bin = shutil.which("st") or sys.argv[0]
    fragments: list[dict[str, list[dict[str, Any]]]] = []
    used_ids = {
        str(node.get("id"))
        for node in json.loads((root / "graphify-out" / "graph.json").read_text(encoding="utf-8")).get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    start = time.perf_counter()
    details_lines = [f"semantic_sources={len(sources)} batches={len(batches)} agent={agent} model={model or 'agent-default'}"]
    try:
        for index, batch in enumerate(batches, start=1):
            prompt, images = _semantic_batch_prompt(root, batch)
            prompt_path = write_details(root, f"graphify-semantic-batch-{index:03d}-prompt", prompt)
            command = [
                st_bin,
                "complete",
                "--agent",
                agent,
                "--project",
                project_id,
                "--roles",
                "agent_system_prompt",
                "--file",
                str(prompt_path),
                "--timeout",
                str(timeout),
                "--skip-cache",
            ]
            if model:
                command[4:4] = ["-M", model]
            for image in images:
                command.extend(["--image", str(image)])
            output = ""
            for attempt in range(1, 4):
                result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=timeout + 30, check=False)
                output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
                if result.returncode == 0 and not output.startswith("Error:"):
                    break
                if attempt == 3 or "Internal server error" not in output:
                    raise RuntimeError(output[-4000:] or f"batch {index} exited {result.returncode}")
                time.sleep(2 * attempt)
            fragment = _parse_semantic_fragment(output)
            sanitized = _sanitize_semantic_fragment(root, batch, fragment, used_ids)
            fragments.append(sanitized)
            details_lines.append(
                f"batch={index}/{len(batches)} files={len(batch)} nodes={len(sanitized['nodes'])} edges={len(sanitized['edges'])}"
            )
        _merge_semantic_fragments(root, fragments, sources)
        refresh_result = run_graphify(root, ["cluster-only", str(root)], timeout=timeout)
        details_lines.append(refresh_result.output)
        refreshed_status = graphify_status(project_id, root)
        semantic_source_count = int(refreshed_status.get("semantic_source_count", 0) or 0)
        semantic_node_count = int(refreshed_status.get("semantic_node_count", 0) or 0)
        diagnostics = [str(item) for item in refreshed_status.get("diagnostics", [])]
        exit_code = 0 if semantic_node_count > 0 and "semantic_sources_not_extracted" not in diagnostics else 1
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        refreshed_status = graphify_status(project_id, root)
        semantic_source_count = int(refreshed_status.get("semantic_source_count", 0) or 0)
        semantic_node_count = int(refreshed_status.get("semantic_node_count", 0) or 0)
        diagnostics = [str(item) for item in refreshed_status.get("diagnostics", [])]
        details_lines.append(f"ERROR: {type(exc).__name__}: {exc}")
        exit_code = 1
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    details = write_details(root, "graphify-semantic-refresh", "\n".join(details_lines))
    print(
        f"GRAPH_SEMANTIC_REFRESH:{'OK' if exit_code == 0 else 'FAIL'}:{exit_code}|"
        f"elapsed_ms={elapsed_ms}|batches={len(batches)}|semantic={semantic_node_count}/"
        f"{semantic_source_count}|diagnostics={','.join(diagnostics) or '-'}|"
        f"details:{display_path(root, details)}"
    )
    return exit_code


def _run_semantic_refresh_agent(
    project_id: str,
    root: Path,
    *,
    agent: str | None,
    model: str | None,
    max_turns: int,
    timeout: int,
) -> int:
    status = _status_for_project_root(project_id, root, auto_refresh=True, action="semantic-refresh")
    prompt = _semantic_refresh_prompt(project_id, root, status)
    prompt_path = write_details(root, "graphify-semantic-refresh-prompt", prompt)
    st_bin = shutil.which("st") or sys.argv[0]
    command = [
        st_bin,
        "complete",
        "--project",
        project_id,
        "--execute-tools",
        "--working-dir",
        str(root),
        "--max-turns",
        str(max_turns),
        "--file",
        str(prompt_path),
        "--timeout",
        str(timeout),
    ]
    if not agent:
        raise typer.BadParameter("semantic-refresh requires --agent with a purpose-built Agent Hub agent slug")
    command[2:2] = ["--agent", agent]
    if model:
        command[4:4] = ["-M", model]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
        output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        exit_code = result.returncode
        if output.startswith("Error:"):
            exit_code = exit_code or 1
    except (OSError, subprocess.SubprocessError) as exc:
        output = f"{type(exc).__name__}: {exc}"
        exit_code = 127
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    details = write_details(root, "graphify-semantic-refresh", output)
    refreshed_status = graphify_status(project_id, root)
    semantic_source_count = int(refreshed_status.get("semantic_source_count", 0) or 0)
    semantic_node_count = int(refreshed_status.get("semantic_node_count", 0) or 0)
    diagnostics = [str(item) for item in refreshed_status.get("diagnostics", [])]
    if semantic_source_count and (
        semantic_node_count == 0 or "semantic_sources_not_extracted" in diagnostics
    ):
        exit_code = exit_code or 1
    print(
        f"GRAPH_SEMANTIC_REFRESH:{'OK' if exit_code == 0 else 'FAIL'}:{exit_code}|"
        f"elapsed_ms={elapsed_ms}|semantic={semantic_node_count}/"
        f"{semantic_source_count}|"
        f"diagnostics={','.join(diagnostics) or '-'}|"
        f"prompt:{display_path(root, prompt_path)}|details:{display_path(root, details)}"
    )
    return exit_code


@app.command("status")
def status(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    all_projects: Annotated[bool, typer.Option("--all", help="Show every registered project.")] = False,
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh", help="Refresh stale code graphs before reporting.")] = True,
) -> None:
    """Show Graphify status and diagnostics."""
    if all_projects:
        projects = _all_projects()
        output_json([
            _status_for_project_root(
                str(item["id"]),
                _root_from_project_payload(str(item["id"]), item),
                auto_refresh=refresh,
                create_missing=False,
            )
            for item in projects
            if item.get("id")
        ])
        return
    output_json(_status_for_project(_project_id(project), auto_refresh=refresh))


@app.command("doctor")
def doctor(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to every project.")] = None,
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh", help="Refresh stale code graphs before diagnosis.")] = True,
) -> None:
    """Report Graphify issues that affect agent usefulness."""
    if project:
        project_id = _project_id(project)
        statuses = [
            _status_for_project(project_id, auto_refresh=refresh, action="doctor", create_missing=True)
        ]
    else:
        projects = _all_projects()
        statuses = [
            _status_for_project_root(
                str(item["id"]),
                _root_from_project_payload(str(item["id"]), item),
                auto_refresh=refresh,
                action="doctor",
                create_missing=False,
            )
            for item in projects
            if item.get("id")
        ]
    issues = [
        {
            "project_id": item["project_id"],
            "diagnostics": [
                diagnostic
                for diagnostic in item["diagnostics"]
                if diagnostic in _DOCTOR_BLOCKING_DIAGNOSTICS
            ],
            "changed_files_since_graph": item["changed_files_since_graph"],
        }
        for item in statuses
        if _issue_count(item)
    ]
    warnings = [
        {
            "project_id": item["project_id"],
            "diagnostics": [
                diagnostic
                for diagnostic in item["diagnostics"]
                if diagnostic not in _DOCTOR_BLOCKING_DIAGNOSTICS
            ],
            "changed_files_since_graph": item["changed_files_since_graph"],
        }
        for item in statuses
        if _warning_count(item)
    ]
    payload = {
        "status": "ISSUES" if issues else "OK",
        "projects": len(statuses),
        "issues": issues,
        "warnings": warnings,
        "issue_count": sum(_issue_count(item) for item in statuses),
        "warning_count": sum(_warning_count(item) for item in statuses),
    }
    output_json(payload)
    if issues:
        raise typer.Exit(2)


@app.command("refresh")
def refresh(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Refresh a project's code-only Graphify graph."""
    project_id = _project_id(project)
    root = _root_for_project(project_id)
    result = refresh_graph(root)
    output_json({"project_id": project_id, **_command_payload(result), "status": _status_for_project_root(project_id, root)})


@app.command("context")
def context(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    budget: Annotated[int, typer.Option("--budget", min=200, max=8000, help="Prompt context token budget.")] = 1200,
) -> None:
    """Emit compact Graphify context for agents."""
    project_id = _project_id(project)
    root = _fresh_root_for_project(project_id, action="context")
    status = graphify_status(project_id, root)
    output_json(_graph_context_payload(project_id, root, status, budget=budget))


@app.command("semantic-refresh")
def semantic_refresh(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", "-a", help="Purpose-built Agent Hub agent slug.")] = (
        "graphify-semantic-extractor"
    ),
    model: Annotated[
        str | None,
        typer.Option("--model", "-M", help="Optional model override. Defaults to the agent model chain."),
    ] = None,
    max_turns: Annotated[int, typer.Option("--max-turns", "-n", min=1, max=200, help="Agentic turn limit.")] = 40,
    timeout: Annotated[int, typer.Option("--timeout", min=60, max=7200, help="Agent Hub read timeout seconds.")] = 1800,
    execute: Annotated[bool, typer.Option("--execute/--no-execute", help="Run Agent Hub; otherwise write prompt and print command.")] = True,
) -> None:
    """Launch an explicit semantic Graphify refresh through Agent Hub."""
    project_id = _project_id(project)
    root = _root_for_project(project_id)
    if not execute:
        status = _status_for_project_root(project_id, root, auto_refresh=True, action="semantic-refresh")
        prompt_path = write_details(root, "graphify-semantic-refresh-prompt", _semantic_refresh_prompt(project_id, root, status))
        print(
            "GRAPH_SEMANTIC_REFRESH:READY|"
            f"project={project_id}|prompt:{display_path(root, prompt_path)}|"
            f"mode=batch|agent={agent}|model={model or 'agent-default'}|"
            f"max_turns_ignored={max_turns}"
        )
        return
    raise typer.Exit(
        _run_semantic_refresh_batches(
            project_id,
            root,
            agent=agent,
            model=model,
            timeout=timeout,
        )
    )


@app.command("query")
def query(
    question: Annotated[str, typer.Argument(help="Topology question.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    budget: Annotated[int, typer.Option("--budget", min=100, max=8000, help="Graphify token budget.")] = 1200,
    dfs: Annotated[bool, typer.Option("--dfs", help="Use depth-first traversal.")] = False,
) -> None:
    """Run Graphify query against a project graph."""
    result = query_graph(_fresh_root_for_project(_project_id(project), action="query"), question, budget=budget, dfs=dfs)
    output_json(_command_payload(result))


@app.command("path")
def path(
    source: Annotated[str, typer.Argument(help="Source node label.")],
    target: Annotated[str, typer.Argument(help="Target node label.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Find shortest Graphify path between two nodes."""
    result = path_graph(_fresh_root_for_project(_project_id(project), action="path"), source, target)
    output_json(_command_payload(result))


@app.command("explain")
def explain(
    node: Annotated[str, typer.Argument(help="Node label.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Explain one graph node and its neighbors."""
    result = explain_graph(_fresh_root_for_project(_project_id(project), action="explain"), node)
    output_json(_command_payload(result))


@app.command("fallow")
def fallow(
    mode: Annotated[
        str,
        typer.Argument(help="Fallow mode: audit, changed, health, plugins, flags, dead-code, dupes."),
    ] = "audit",
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    changed_since: Annotated[str, typer.Option("--changed-since", help="Git ref for changed mode.")] = "main",
    top: Annotated[int, typer.Option("--top", min=1, max=100, help="Clone groups for dupes mode.")] = 10,
    timeout: Annotated[int, typer.Option("--timeout", min=5, max=600, help="Command timeout in seconds.")] = 120,
) -> None:
    """Run Fallow with compact stdout and full details in .dev-tools."""
    raise typer.Exit(
        _run_fallow_compact(
            _root_for_project(_project_id(project)),
            mode,
            changed_since=changed_since,
            top=top,
            timeout=timeout,
        )
    )


def _run_measured(command: list[str], *, cwd: Path, timeout: int = 180) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = "\n".join(
            part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part
        )
        exit_code = result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
        exit_code = 1
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return {
        "command": command,
        "exit_code": exit_code,
        "elapsed_ms": elapsed_ms,
        "output_chars": len(output),
        "estimated_tokens": (len(output) + 3) // 4 if output else 0,
        "output_preview": output[:1200],
    }


def _extract_json_payload(output: str) -> dict[str, Any] | None:
    text = strip_ansi(output)
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index >= 0:
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        return payload if isinstance(payload, dict) else None
    return None


def _fallow_command(mode: str, *, changed_since: str, top: int) -> list[str]:
    fallow_bin = shutil.which("fallow") or "fallow"
    if mode == "audit":
        return [fallow_bin, "audit", "--format", "json", "--quiet"]
    if mode == "changed":
        return [
            fallow_bin,
            "dead-code",
            "--changed-since",
            changed_since,
            "--format",
            "json",
            "--quiet",
            "--summary",
        ]
    if mode == "health":
        return [fallow_bin, "health", "--format", "json", "--quiet", "--score"]
    if mode == "plugins":
        return [fallow_bin, "list", "--format", "json", "--plugins"]
    if mode == "flags":
        return [fallow_bin, "flags", "--format", "json", "--quiet"]
    if mode == "dead-code":
        return [fallow_bin, "dead-code", "--format", "json", "--quiet"]
    return [fallow_bin, "dupes", "--format", "json", "--quiet", "--top", str(top)]


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list_field(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _fallow_hint(mode: str, payload: dict[str, Any] | None, output: str) -> str:
    if not payload:
        return summary_hint(output)
    if mode == "audit":
        summary = _dict_field(payload, "summary")
        attribution = _dict_field(payload, "attribution")
        return (
            f"verdict={payload.get('verdict', '-')}"
            f" changed={payload.get('changed_files_count', 0)}"
            f" dead={summary.get('dead_code_issues', 0)}"
            f" complexity={summary.get('complexity_findings', 0)}"
            f" dupes={summary.get('duplication_clone_groups', 0)}"
            f" introduced={attribution.get('dead_code_introduced', 0)}"
        )
    if mode in {"changed", "dead-code"}:
        summary = _dict_field(payload, "summary")
        return (
            f"issues={payload.get('total_issues', summary.get('total_issues', 0))}"
            f" files={summary.get('unused_files', 0)}"
            f" exports={summary.get('unused_exports', 0)}"
            f" deps={summary.get('unused_dependencies', 0)}"
            f" circular={summary.get('circular_dependencies', 0)}"
        )
    if mode == "health":
        score = _dict_field(payload, "health_score")
        summary = _dict_field(payload, "summary")
        return (
            f"score={score.get('score', '-')}"
            f" grade={score.get('grade', '-')}"
            f" functions={summary.get('functions_analyzed', 0)}"
            f" above={summary.get('functions_above_threshold', 0)}"
        )
    if mode == "plugins":
        plugins = _list_field(payload, "plugins")
        names = [str(item.get("name")) for item in plugins if isinstance(item, dict) and item.get("name")]
        return f"plugins={','.join(names) if names else '-'}"
    if mode == "flags":
        return f"flags={payload.get('total_flags', 0)}"
    stats = _dict_field(payload, "stats")
    groups = _list_field(payload, "clone_groups")
    group_count = len(groups) if isinstance(groups, list) else stats.get("clone_groups", 0)
    return f"clone_groups={group_count} duplicated_pct={stats.get('duplication_percentage', 0)}"


def _run_fallow_compact(root: Path, mode: str, *, changed_since: str, top: int, timeout: int) -> int:
    if mode not in _FALLOW_MODES:
        print(f"FALLOW:ERROR:unknown_mode:{mode}|valid={','.join(sorted(_FALLOW_MODES))}")
        return 2
    command = _fallow_command(mode, changed_since=changed_since, top=top)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        exit_code = result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        output = f"{type(exc).__name__}: {exc}"
        exit_code = 127
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    details = write_details(root, f"fallow-{mode}", output)
    clean_output = strip_ansi(output)
    payload = _extract_json_payload(output)
    byte_count = len(clean_output.encode("utf-8"))
    token_count = (len(clean_output) + 3) // 4 if clean_output else 0
    print(
        f"FALLOW:{mode}:{'OK' if exit_code == 0 else 'FAIL'}:{exit_code}|"
        f"elapsed_ms={elapsed_ms}|bytes={byte_count}|tokens={token_count}|"
        f"details:{display_path(root, details)}|hint:{_fallow_hint(mode, payload, output)}"
    )
    return exit_code


def _gitnexus_profile(root: Path) -> dict[str, Any]:
    gitnexus_bin = shutil.which("gitnexus")
    npm_bin = shutil.which("npm")
    npx_bin = shutil.which("npx")
    metadata = (
        _run_measured(
            [npm_bin, "view", _GITNEXUS_PACKAGE, "version", "description", "license", "--json"],
            cwd=root,
            timeout=30,
        )
        if npm_bin
        else {"tool": "npm", "available": False}
    )
    startup: dict[str, Any] | None = None
    local_status: dict[str, Any] | None = None
    context_probe: dict[str, Any] | None = None
    impact_probe: dict[str, Any] | None = None
    if gitnexus_bin:
        startup = _run_measured([gitnexus_bin, "--version"], cwd=root, timeout=30)
        local_status = _run_measured([gitnexus_bin, "status"], cwd=root, timeout=60)
        context_probe = _run_measured([gitnexus_bin, "context", "graphify_status"], cwd=root, timeout=60)
        impact_probe = _run_measured(
            [gitnexus_bin, "impact", "graphify_status", "--depth", "2"],
            cwd=root,
            timeout=60,
        )
    return {
        "tool": "gitnexus",
        "worth": "optional",
        "available": bool(gitnexus_bin),
        "npx_available": bool(npx_bin),
        "metadata": metadata,
        "startup": startup,
        "local_status": local_status,
        "context_probe": context_probe,
        "impact_probe": impact_probe,
        "fills_real_gaps": [
            "MCP tools for Codex/editor agents",
            "impact and detect_changes blast-radius analysis",
            "multi-repo groups and contract queries",
        ],
        "not_default_reasons": [
            "overlaps Graphify topology/search",
            "PolyForm Noncommercial license requires explicit fit check",
            "first install is heavy enough to keep explicit",
            "query/detect_changes need local validation before relying on them",
        ],
        "recommended_use": "Use after st search/st graph when work needs symbol context, impact radius, MCP-fed agent context, or multi-repo contract queries.",
        "manual_commands": {
            "install_user_prefix": ["npm", "install", "--global", "--prefix", "~/.local", "gitnexus@1.6.3"],
            "index_current_repo": [
                "gitnexus",
                "analyze",
                ".",
                "--skip-agents-md",
                "--no-stats",
                "--max-file-size",
                "1024",
            ],
            "codex_mcp": ["codex", "mcp", "add", "gitnexus", "--", "gitnexus", "mcp"],
            "status_after_install": ["gitnexus", "status"],
        },
    }


def _fallow_profile(root: Path) -> dict[str, Any]:
    fallow_bin = shutil.which("fallow")
    fallow_mcp_bin = shutil.which("fallow-mcp")
    npm_bin = shutil.which("npm")
    metadata = (
        _run_measured(
            [npm_bin, "view", _FALLOW_PACKAGE, "version", "description", "license", "bin", "--json"],
            cwd=root,
            timeout=30,
        )
        if npm_bin
        else {"tool": "npm", "available": False}
    )
    startup: dict[str, Any] | None = None
    plugins_probe: dict[str, Any] | None = None
    audit_probe: dict[str, Any] | None = None
    health_score_probe: dict[str, Any] | None = None
    changed_dead_code_probe: dict[str, Any] | None = None
    if fallow_bin:
        startup = _run_measured([fallow_bin, "--version"], cwd=root, timeout=30)
        plugins_probe = _run_measured([fallow_bin, "list", "--format", "json", "--plugins"], cwd=root, timeout=60)
        audit_probe = _run_measured([fallow_bin, "audit", "--format", "json", "--quiet"], cwd=root, timeout=120)
        health_score_probe = _run_measured(
            [fallow_bin, "health", "--format", "json", "--quiet", "--score"],
            cwd=root,
            timeout=120,
        )
        changed_dead_code_probe = _run_measured(
            [fallow_bin, "dead-code", "--changed-since", "main", "--format", "json", "--quiet", "--summary"],
            cwd=root,
            timeout=120,
        )
    return {
        "tool": "fallow",
        "worth": "recommended_optional",
        "available": bool(fallow_bin),
        "mcp_available": bool(fallow_mcp_bin),
        "metadata": metadata,
        "startup": startup,
        "plugins_probe": plugins_probe,
        "audit_probe": audit_probe,
        "health_score_probe": health_score_probe,
        "changed_dead_code_probe": changed_dead_code_probe,
        "fills_real_gaps": [
            "TypeScript/JavaScript dead-code analysis across the module graph",
            "changed-file audit for AI-generated frontend code",
            "duplication, complexity, feature-flag, and dependency-use evidence",
            "typed MCP tools for agents that should not parse large CLI output manually",
        ],
        "not_default_reasons": [
            "full dead-code, duplication, and health output can be very large",
            "static findings need trace commands or tests before deletion",
            "does not analyze Python backend code",
            "overlaps lint/type/test gates only as codebase-level evidence, not replacement",
        ],
        "recommended_use": "Use `fallow audit --format json --quiet` after frontend JS/TS changes; use targeted trace commands before deleting exports, files, or dependencies.",
        "manual_commands": {
            "install_user_prefix": ["npm", "install", "--global", "--prefix", "~/.local", "fallow@2.57.0"],
            "codex_mcp": ["codex", "mcp", "add", "fallow", "--", "fallow-mcp"],
            "audit_changed": ["fallow", "audit", "--format", "json", "--quiet"],
            "health_score": ["fallow", "health", "--format", "json", "--quiet", "--score"],
            "project_plugins": ["fallow", "list", "--format", "json", "--plugins"],
            "trace_dependency": ["fallow", "dead-code", "--trace-dependency", "<package>", "--format", "json"],
        },
    }


@app.command("profile")
def profile(
    question: Annotated[
        str,
        typer.Option("--question", "-q", help="Architecture question to profile."),
    ] = "What are the central modules and relationship patterns in this project?",
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    budget: Annotated[int, typer.Option("--budget", min=100, max=8000, help="Graphify token budget.")] = 1200,
    codex: Annotated[bool, typer.Option("--codex", help="Probe Codex CLI availability and startup cost.")] = False,
    agent_hub: Annotated[bool, typer.Option("--agent-hub", help="Probe Agent Hub completion CLI availability.")] = False,
    gitnexus: Annotated[
        bool,
        typer.Option("--gitnexus", help="Evaluate optional GitNexus fit without installing or mutating MCP config."),
    ] = False,
    fallow: Annotated[
        bool,
        typer.Option("--fallow", help="Evaluate optional Fallow JS/TS codebase-intelligence fit."),
    ] = False,
) -> None:
    """Profile st search vs Graphify command shapes for agent work."""
    project_id = _project_id(project)
    root = _fresh_root_for_project(project_id, action="profile")
    st_bin = shutil.which("st") or sys.argv[0]
    runs = [
        _run_measured([st_bin, "-P", project_id, "search", question], cwd=root),
        _command_payload(query_graph(root, question, budget=budget)),
    ]
    tool_probes: list[dict[str, Any]] = []
    if codex:
        codex_bin = shutil.which("codex")
        if codex_bin:
            tool_probes.append(_run_measured([codex_bin, "--version"], cwd=root, timeout=30))
            tool_probes.append(_run_measured([codex_bin, "exec", "--help"], cwd=root, timeout=30))
        else:
            tool_probes.append({"tool": "codex", "available": False})
    if agent_hub:
        tool_probes.append(
            _run_measured(
                [
                    st_bin,
                    "-P",
                    "agent-hub",
                    "agents",
                    "preview",
                    "explorer",
                    "-P",
                    project_id,
                    "--input",
                    question,
                    "--json",
                ],
                cwd=root,
                timeout=90,
            )
        )
    if gitnexus:
        tool_probes.append(_gitnexus_profile(root))
    if fallow:
        tool_probes.append(_fallow_profile(root))
    output_json(
        {
            "project_id": project_id,
            "question": question,
            "runs": runs,
            "tool_probes": tool_probes,
            "recommendation": "Use st search for exact symbols/files; use st graph query/path/explain for topology; use Fallow for JS/TS changed-code health; use GitNexus for indexed symbol impact.",
        }
    )
