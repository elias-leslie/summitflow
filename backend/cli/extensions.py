"""Trusted registration is passive; executable resolution happens only on dispatch/check."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import typer
from pydantic import ValidationError
from typer.core import TyperCommand

from .extension_contract import CONTRACT_VERSION, ExtensionBinding, ExtensionManifest
from .tool_registry import tool_registry_path


@dataclass
class ExtensionRecord:
    binding: ExtensionBinding | None
    manifest: ExtensionManifest | None = None
    status: str = "unverified"
    diagnostic: str = "Runtime has not been checked or executed."


@dataclass
class ExtensionCatalog:
    records: list[ExtensionRecord] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def load_extensions(core_names: set[str], *, registry_path: Path | None = None) -> ExtensionCatalog:
    """Read only trusted local metadata; never import owners or resolve projects."""
    registry_path = registry_path or tool_registry_path()
    catalog = ExtensionCatalog()
    try:
        payload = json.loads(registry_path.read_text())
        rows = payload.get("extensions", [])
        if not isinstance(rows, list):
            raise ValueError("extensions must be a list")
    except (OSError, ValueError, AttributeError):
        catalog.diagnostics.append("Malformed or unreadable trusted extension registry.")
        return catalog
    for index, row in enumerate(rows):
        try:
            binding = ExtensionBinding.model_validate(row)
        except ValidationError:
            catalog.diagnostics.append(f"Extension binding {index + 1} is malformed.")
            continue
        record = ExtensionRecord(binding)
        catalog.records.append(record)
        try:
            metadata_path = (registry_path.parent / binding.manifest).resolve()
            if not metadata_path.is_relative_to((registry_path.parent / "extensions").resolve()):
                raise ValueError("metadata outside trusted manifest directory")
            metadata = ExtensionManifest.model_validate_json(metadata_path.read_text())
            if (metadata.id, metadata.owner, metadata.namespace) != (binding.id, binding.owner, binding.namespace):
                raise ValueError("binding identity mismatch")
            record.manifest = metadata
        except (OSError, ValueError):
            record.status, record.diagnostic = "malformed", "Invalid extension manifest; repair its trusted registration."
            continue
        if CONTRACT_VERSION not in metadata.st_contract_versions:
            record.status, record.diagnostic = "incompatible", f"Extension does not support ST contract {CONTRACT_VERSION}."
        elif not binding.grant.enabled or not set(metadata.effects) <= set(binding.grant.effects):
            record.status, record.diagnostic = "denied", "Extension requires an explicit matching ST dispatch grant."
    ids = Counter(record.binding.id for record in catalog.records if record.binding)
    namespaces = Counter(record.binding.namespace for record in catalog.records if record.binding)
    for record in catalog.records:
        binding = record.binding
        if binding and (binding.namespace in core_names or ids[binding.id] > 1 or namespaces[binding.namespace] > 1):
            record.status, record.diagnostic = "collision", "Namespace or extension identity collision; no conflicting extension is dispatched."
    return catalog


def _resolve_executable(record: ExtensionRecord, root_resolver: Callable[[str], str | None] | None = None) -> tuple[Path | None, int, str]:
    if record.status != "unverified" or record.binding is None:
        return None, 2, record.diagnostic
    if root_resolver is None:
        from .config import get_project_root_path

        root_resolver = get_project_root_path
    root = root_resolver(record.binding.owner)
    if not root:
        return None, 127, f"Owner project '{record.binding.owner}' is unavailable in the ST project registry."
    executable = Path(root) / record.binding.executable
    if not executable.is_file():
        return None, 127, f"Install the registered executable for owner '{record.binding.owner}': {record.binding.executable}"
    if not os.access(executable, os.X_OK):
        return None, 126, "Registered extension entrypoint is not executable."
    return executable, 0, "Executable prerequisite exists; runtime compatibility remains unverified."


def extension_diagnostics(catalog: ExtensionCatalog, *, check: bool = False) -> dict[str, Any]:
    rows = []
    for record in catalog.records:
        binding = record.binding
        if not binding:
            continue
        row: dict[str, Any] = {"id": binding.id, "owner": binding.owner, "namespace": binding.namespace,
                               "version": record.manifest.version if record.manifest else None,
                               "status": record.status, "diagnostic": record.diagnostic}
        if check and record.status == "unverified":
            _, code, diagnostic = _resolve_executable(record)
            row.update(status="prerequisites-present" if code == 0 else "missing-dependency", diagnostic=diagnostic)
        rows.append(row)
    return {"contract_version": CONTRACT_VERSION, "extensions": rows, "diagnostics": catalog.diagnostics}


def extension_context(output: Any = None) -> dict[str, Any]:
    from .config import get_agent_hub_url, get_config_optional
    from .output_context import OutputContext

    config = get_config_optional()
    output = output if isinstance(output, OutputContext) else OutputContext()
    return {"contract_version": CONTRACT_VERSION, "project_id": config.project_id or None,
            "project_root": config.project_root, "cwd": str(Path.cwd()),
            "api_base": config.api_base, "agent_hub_url": get_agent_hub_url(),
            "output": {"human": output.human, "compact": output.compact, "progress_only": output.progress_only}}


def _environment(binding: ExtensionBinding, context: dict[str, Any]) -> dict[str, str]:
    # PATH is inherited only for the explicitly trusted owner's own dependencies;
    # ST itself resolves a pinned project-relative entrypoint, never a PATH plugin.
    inherited = {"HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "NO_COLOR", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"}
    env = {key: os.environ[key] for key in inherited | set(binding.environment) if key in os.environ}
    env["ST_EXTENSION_CONTEXT"] = json.dumps(context, separators=(",", ":"))
    return env


def _run_process(argv: list[str], *, env: dict[str, str], cwd: str, capture: bool = False) -> tuple[int, str, str]:
    """Inherit streams; forward cancellation to the owned process group and reap."""
    process: subprocess.Popen | None = None
    previous: dict[int, Any] = {}
    cancelled = 0

    def forward(signum: int, _frame: Any) -> None:
        nonlocal cancelled
        cancelled = signum
        if process is not None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signum)
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, forward)
        if cancelled:
            return 128 + cancelled, "", ""
        process = subprocess.Popen(argv, env=env, cwd=cwd, start_new_session=True,
                                   stdout=subprocess.PIPE if capture else None,
                                   stderr=subprocess.PIPE if capture else None, text=capture)
        if cancelled:
            forward(cancelled, None)
        stdout, stderr = process.communicate()
        code = 128 + cancelled if cancelled else process.returncode
        return (128 - code if code < 0 else code), stdout or "", stderr or ""
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def dispatch_extension(record: ExtensionRecord, argv: list[str], *, context: dict[str, Any] | None = None,
                       root_resolver: Callable[[str], str | None] | None = None) -> int:
    executable, code, diagnostic = _resolve_executable(record, root_resolver)
    if code or executable is None or record.binding is None:
        typer.echo(json.dumps({"error": "st-extension", "status": record.status if code == 2 else "missing-dependency",
                               "message": diagnostic}), err=True)
        return code
    binding = record.binding
    context = context if context is not None else extension_context()
    try:
        arguments = [*binding.arguments, *argv]
        if binding.presentation == "web-details":
            # JSON formatting and benchmark behavior belong to the public owner CLI.
            insertion = arguments.index("--") if "--" in arguments else len(arguments)
            arguments.insert(insertion, "--compact")
        code, stdout, stderr = _run_process([str(executable), *arguments],
                                            env=_environment(binding, context), cwd=context["cwd"],
                                            capture=binding.presentation == "web-details")
        if binding.presentation == "web-details":
            from .extension_presentation import present_web

            present_web(argv, code, stdout, stderr)
        return code
    except OSError as exc:
        code = 127 if isinstance(exc, FileNotFoundError) else 126
        typer.echo(json.dumps({"error": "st-extension", "status": "execution-failed",
                               "message": "Owner entrypoint or its interpreter could not be started.", "errno": exc.errno}), err=True)
        return code


class ExtensionCommand(TyperCommand):
    """Keep the opaque owner argv, including Click's otherwise-consumed `--`."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        ctx.meta["st_extension_argv"] = list(args)
        return super().parse_args(ctx, args)


def _help_path(arguments: list[str], help_pages: dict[str, str]) -> str:
    # Metadata contains command routes, not the owner's argument parser. Select
    # registered command words in order; positional values and flags are not
    # route components. Never interpret tokens after an explicit `--`.
    path = ""
    for value in arguments:
        if value.startswith("-"):
            continue
        candidate = f"{path} {value}".strip()
        if candidate in help_pages:
            path = candidate
    return path


def _callback(record: ExtensionRecord):
    def command(ctx: typer.Context) -> None:
        argv = list(ctx.meta["st_extension_argv"])
        # Never ask the executable for help, even if dependencies are unavailable.
        options = argv[:argv.index("--")] if "--" in argv else argv
        if "--help" in options or "-h" in options:
            metadata = record.manifest
            if metadata is None:
                typer.echo(record.diagnostic)
                raise typer.Exit(2)
            path = _help_path(options, metadata.help)
            typer.echo(metadata.help[path])
            return
        context = extension_context(ctx.find_root().obj) if record.status == "unverified" else None
        if record.status == "unverified" and record.binding and record.binding.policy_adapter == "browser":
            from .commands.browser import run_registered

            assert context is not None
            raise typer.Exit(run_registered(record, argv, context))
        raise typer.Exit(dispatch_extension(record, argv, context=context))
    if record.manifest is not None and record.status != "collision":
        cast(Any, command).__st_usage_specs__ = record.manifest.usage_specs()
    return command


def register_extensions(app: typer.Typer, *, registry_path: Path | None = None) -> ExtensionCatalog:
    names = {row.name or getattr(row.callback, "__name__", "").replace("_", "-") for row in app.registered_commands if row.callback}
    names.update(row.name for row in app.registered_groups if row.name)
    catalog = load_extensions(names, registry_path=registry_path)
    for record in catalog.records:
        if record.binding is None or record.status == "collision":
            continue
        summary = record.manifest.summary if record.manifest else "Unavailable extension"
        app.command(record.binding.namespace, cls=ExtensionCommand, help=summary, add_help_option=False,
                    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []})(_callback(record))
    cast(Any, app)._st_extensions = catalog
    return catalog
