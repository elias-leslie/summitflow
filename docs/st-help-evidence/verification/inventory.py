"""Read-only, runtime-equivalent ST help inventory; never executes non-help routes."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from typer.main import get_command

from cli.main import app


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ST = ROOT / "backend/.venv/bin/st"
MANUAL_HELP = (
    ("check", "help"),
    ("check", "--acceptance", "--help"),
    ("check", "codeql", "--help"),
    ("db", "help"),
    ("db", "tables", "--help"),
    ("db", "schema", "--help"),
    ("db", "count", "--help"),
    ("db", "sample", "--help"),
    ("db", "sizes", "--help"),
    ("db", "indexes", "--help"),
    ("db", "query", "--help"),
    ("db", "exec", "--help"),
    ("db", "ddl", "--help"),
    ("db", "migrate", "--help"),
    ("db", "workbench", "--help"),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_fingerprint() -> dict[str, str]:
    paths = sorted((ROOT / "backend/cli").rglob("*.py"))
    paths += sorted((ROOT / "scripts/lib/extensions").rglob("*.json"))
    paths += [ROOT / "scripts/lib/tool-registry.json"]
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in paths if path.is_file()}


def fingerprint_rows(fingerprint: dict[str, str]) -> list[dict[str, str]]:
    return [{"path": path, "sha256": fingerprint[path]} for path in sorted(fingerprint)]


def safe_default(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return [safe_default(item) for item in value]
    return repr(value)


def param_record(param: click.Parameter) -> dict[str, object]:
    record: dict[str, object] = {
        "name": param.name,
        "kind": type(param).__name__,
        "required": param.required,
        "default": safe_default(param.default),
        "type": str(param.type),
        "nargs": param.nargs,
        "multiple": param.multiple,
    }
    if isinstance(param, click.Option):
        record.update(
            opts=list(param.opts),
            secondary_opts=list(param.secondary_opts),
            is_flag=param.is_flag,
            help=param.help,
            hidden=param.hidden,
        )
    return record


def click_routes(command: click.Command) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(current: click.Command, path: tuple[str, ...]) -> None:
        rows.append(
            {
                "path": list(path),
                "kind": "click",
                "class": type(current).__name__,
                "group": isinstance(current, click.Group),
                "hidden": current.hidden,
                "add_help_option": current.add_help_option,
                "help": current.help,
                "short_help": current.short_help,
                "params": [param_record(param) for param in current.params],
            }
        )
        if isinstance(current, click.Group):
            for name, child in current.commands.items():
                visit(child, (*path, name))

    visit(command, ())
    return rows


def metadata_routes() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    for record in app._st_extensions.records:  # type: ignore[attr-defined]
        binding, manifest = record.binding, record.manifest
        if binding is None:
            continue
        records.append(
            {
                "namespace": binding.namespace,
                "status": record.status,
                "manifest": binding.manifest,
                "executable": binding.executable,
                "help_page_count": len(manifest.help) if manifest else 0,
            }
        )
        if manifest is None:
            continue
        for key, help_text in manifest.help.items():
            parent = " ".join(key.split()[:-1])
            rows.append(
                {
                    "path": [binding.namespace, *key.split()],
                    "kind": "extension_metadata",
                    "metadata_key": key,
                    "metadata_parent_present": not key or parent in manifest.help,
                    "expected_help_sha256": sha(help_text.encode()),
                    "expected_help_bytes": len(help_text.encode()),
                }
            )
    return rows, records


def capture(row: dict[str, object]) -> dict[str, object]:
    path = tuple(row["path"])
    argv = [str(ST), *path]
    if row["kind"] != "manual_help":
        argv.append("--help")
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "100"}
    start = time.perf_counter_ns()
    try:
        result = subprocess.run(argv, cwd="/tmp", env=env, capture_output=True, timeout=20)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code = exc.stdout or b"", exc.stderr or b"", 124
    elapsed = round((time.perf_counter_ns() - start) / 1_000_000, 3)
    content = stdout + stderr
    return {
        "path": list(path),
        "kind": row["kind"],
        "argv": argv,
        "exit_code": code,
        "elapsed_ms": elapsed,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
        "stdout_sha256": sha(stdout),
        "stderr_sha256": sha(stderr),
        "returned_bytes": len(content),
        "estimated_tokens": math.ceil(len(content) / 4),
    }


def manual_dispatch_routes() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Include all audited manual routes, invoking only DB/help branches.

    `st check --quick --help` actually executes gates, so its route must remain
    structural evidence rather than a help subprocess.
    """
    audit_path = OUT.parent / "native-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    structural = audit["manual_dispatch"]
    safe = list(MANUAL_HELP)
    for row in structural:
        words = tuple(str(row["path"]).split())
        if words[:2] == ("st", "db"):
            route = (*words[1:], "--help")
            if route not in safe:
                safe.append(route)
    return ([{"path": list(path), "kind": "manual_help"} for path in safe], structural)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("before", "after"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    before_files = source_fingerprint()
    root = get_command(app)
    click_rows = click_routes(root)
    metadata_rows, extension_records = metadata_routes()
    extension_names = {record["namespace"] for record in extension_records}
    native_rows = [row for row in click_rows if not row["path"] or row["path"][0] not in extension_names]
    manual_rows, manual_structural = manual_dispatch_routes()
    routes = [*native_rows, *metadata_rows, *manual_rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        captures = list(executor.map(capture, routes))
    after_files = source_fingerprint()
    result = {
        "label": args.label,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "executable": str(ST),
        "executable_sha256": sha(ST.read_bytes()),
        "cli_module": __import__("cli.main", fromlist=["__file__"]).__file__,
        "source_fingerprint_before": fingerprint_rows(before_files),
        "source_fingerprint_after": fingerprint_rows(after_files),
        "source_stable": before_files == after_files,
        "click_routes": click_rows,
        "extension_records": extension_records,
        "metadata_routes": metadata_rows,
        "manual_routes": manual_rows,
        "manual_dispatch_structural": manual_structural,
        "captures": captures,
    }
    output = OUT / f"{args.label}.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(output),
        "click_routes": len(click_rows),
        "native_routes": len(native_rows),
        "extension_namespaces": len(extension_records),
        "extension_help_pages": len(metadata_rows),
        "manual_help_routes": len(manual_rows),
        "manual_dispatch_structural": len(manual_structural),
        "captures": len(captures),
        "errors": sum(row["exit_code"] != 0 for row in captures),
        "source_stable": result["source_stable"],
        "estimated_tokens": sum(row["estimated_tokens"] for row in captures),
    }))


if __name__ == "__main__":
    main()
