"""Runtime bridge for executable ST command owners."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from . import config, state
from .context import OutputContext
from .usage import collect_usage_specs

CONTEXT_ENV = "ST_EXTENSION_CONTEXT"
CONTRACT_VERSION = 1
_CONTEXT_KEYS = {
    "contract_version",
    "project_id",
    "project_root",
    "cwd",
    "api_base",
    "agent_hub_url",
    "output",
}
_OUTPUT_KEYS = {"human", "compact", "progress_only"}


@dataclass(frozen=True)
class ExtensionContext:
    contract_version: int
    project_id: str | None
    project_root: str | None
    cwd: str
    api_base: str
    agent_hub_url: str
    output: OutputContext


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{CONTEXT_ENV}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{CONTEXT_ENV}.{key} must be null or a non-empty string")
    return value.strip()


def _parse_context(raw: str) -> ExtensionContext:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONTEXT_ENV} must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{CONTEXT_ENV} must be a JSON object")
    if set(payload) != _CONTEXT_KEYS:
        raise ValueError(f"{CONTEXT_ENV} must contain exactly {sorted(_CONTEXT_KEYS)}")
    if payload["contract_version"] != CONTRACT_VERSION:
        raise ValueError(f"unsupported ST extension contract version: {payload['contract_version']!r}")
    output = payload["output"]
    if not isinstance(output, dict) or set(output) != _OUTPUT_KEYS:
        raise ValueError(f"{CONTEXT_ENV}.output must contain exactly {sorted(_OUTPUT_KEYS)}")
    if any(type(output[key]) is not bool for key in _OUTPUT_KEYS):
        raise ValueError(f"{CONTEXT_ENV}.output values must be booleans")
    cwd = _required_string(payload, "cwd")
    project_root = _optional_string(payload, "project_root")
    if not Path(cwd).is_absolute() or (project_root is not None and not Path(project_root).is_absolute()):
        raise ValueError(f"{CONTEXT_ENV} cwd and project_root must be absolute paths")
    return ExtensionContext(
        contract_version=CONTRACT_VERSION,
        project_id=_optional_string(payload, "project_id"),
        project_root=project_root,
        cwd=cwd,
        api_base=_required_string(payload, "api_base").rstrip("/"),
        agent_hub_url=_required_string(payload, "agent_hub_url").rstrip("/"),
        output=OutputContext(**output),
    )


def _apply_output(output: OutputContext) -> None:
    state.set_human_output(output.human)
    state.set_compact_output(output.compact)
    state.set_progress_only(output.progress_only)


def initialize_context(
    environ: Mapping[str, str] | None = None,
) -> tuple[ExtensionContext | None, OutputContext]:
    """Validate and install dispatcher context before Typer resolves callbacks."""
    source = os.environ if environ is None else environ
    raw = source.get(CONTEXT_ENV)
    if raw is None:
        config.clear_runtime_context()
        output = OutputContext()
        _apply_output(output)
        return None, output
    extension_context = _parse_context(raw)
    config.configure_runtime_context(
        api_base=extension_context.api_base,
        agent_hub_url=extension_context.agent_hub_url,
        project_id=extension_context.project_id,
        project_root=extension_context.project_root,
        cwd=extension_context.cwd,
    )
    _apply_output(extension_context.output)
    return extension_context, extension_context.output


def clear_context() -> None:
    """Clear in-process runtime context without changing environment variables."""
    config.clear_runtime_context()
    state.set_human_output(False)
    state.set_compact_output(False)
    state.set_progress_only(False)


def run_app(
    app: typer.Typer,
    namespace: str,
    args: Sequence[str] | None = None,
) -> Any:
    """Initialize trusted context, then invoke an owner Typer application.

    Typer's ordinary standalone behavior is preserved: usage errors are rendered,
    callbacks raising ``typer.Exit`` retain their status, and the process exits
    instead of returning a status that an owner entrypoint could accidentally drop.
    """
    if not namespace.strip():
        raise ValueError("extension namespace must be non-empty")
    _, output = initialize_context()
    return app(args=list(args) if args is not None else None, obj=output)


def _collect_help(
    command: Any,
    context: Any,
    prefix: str,
    out: dict[str, str],
) -> None:
    """Render Click's complete static help without invoking command callbacks."""
    rich_markup_mode = getattr(command, "rich_markup_mode", None)
    try:
        # Typer's Rich renderer writes to a cached console instead of returning
        # help text. Plain Click rendering carries the same arguments, options,
        # defaults, and command descriptions in a stable serializable string.
        if hasattr(command, "rich_markup_mode"):
            command.rich_markup_mode = None  # type: ignore[attr-defined]
        out[prefix] = command.get_help(context)
    finally:
        if hasattr(command, "rich_markup_mode"):
            command.rich_markup_mode = rich_markup_mode  # type: ignore[attr-defined]
    list_commands = getattr(command, "list_commands", None)
    get_command = getattr(command, "get_command", None)
    if not callable(list_commands) or not callable(get_command):
        return
    for name in list_commands(context):
        child = get_command(context, name)
        if child is None:
            continue
        child_path = " ".join(part for part in (prefix, name) if part)
        child_context = child.make_context(name, [], parent=context, resilient_parsing=True)
        _collect_help(child, child_context, child_path, out)


def describe_app(app: typer.Typer, namespace: str) -> dict[str, Any]:
    """Return static, JSON-serializable owner help and usage metadata."""
    if not namespace.strip():
        raise ValueError("extension namespace must be non-empty")
    root = typer.main.get_command(app)
    help_by_path: dict[str, str] = {}
    root_context = root.make_context(namespace, [], resilient_parsing=True)
    _collect_help(root, root_context, "", help_by_path)
    return {
        "namespace": namespace,
        "help": help_by_path,
        "usage": [spec.to_dict() for spec in collect_usage_specs(app)],
    }
