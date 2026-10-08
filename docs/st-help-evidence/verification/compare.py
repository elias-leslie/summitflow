"""Compare read-only installed help captures and frozen command signatures."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from cli.main import app


HERE = Path(__file__).resolve().parent
BEFORE = json.loads((HERE / "before.json").read_text())
AFTER = json.loads((HERE / "after.json").read_text())


def route_key(row: dict[str, object]) -> tuple[str, ...]:
    return tuple(row["path"])


def signature(row: dict[str, object]) -> dict[str, object]:
    stable = {key: row[key] for key in ("path", "class", "group", "hidden", "add_help_option")}
    stable["params"] = [
        {
            key: re.sub(r" at 0x[0-9a-f]+", " at 0xADDR", value) if key == "type" and isinstance(value, str) else value
            for key, value in param.items() if key != "help"
        }
        for param in row["params"]
    ]
    return stable


def costs(captures: list[dict[str, object]]) -> dict[str, object]:
    values = sorted(row["estimated_tokens"] for row in captures)
    return {
        "routes": len(captures),
        "bytes": sum(row["returned_bytes"] for row in captures),
        "estimated_tokens": sum(values),
        "median_estimated_tokens": statistics.median(values),
        "p90_estimated_tokens": values[int(len(values) * 0.9)] if values else 0,
    }


old_click = {route_key(row): row for row in BEFORE["click_routes"]}
new_click = {route_key(row): row for row in AFTER["click_routes"]}
old_extensions = {row["namespace"]: row for row in BEFORE["extension_records"]}
new_extensions = {row["namespace"]: row for row in AFTER["extension_records"]}
old_metadata = {route_key(row): row for row in BEFORE["metadata_routes"]}
new_metadata = {route_key(row): row for row in AFTER["metadata_routes"]}
new_captures = {(row["kind"], route_key(row)): row for row in AFTER["captures"]}
old_captures = {(row["kind"], route_key(row)): row for row in BEFORE["captures"]}
live_manifests = {
    record.binding.namespace: record.manifest
    for record in app._st_extensions.records  # type: ignore[attr-defined]
    if record.binding and record.manifest
}

findings: dict[str, object] = {}
findings["source_stable"] = AFTER["source_stable"]
findings["removed_click_routes"] = [list(path) for path in sorted(old_click.keys() - new_click.keys())]
findings["added_click_routes"] = [list(path) for path in sorted(new_click.keys() - old_click.keys())]
findings["changed_click_signatures"] = [
    list(path) for path in sorted(old_click.keys() & new_click.keys())
    if signature(old_click[path]) != signature(new_click[path])
]
findings["removed_extension_namespaces"] = sorted(old_extensions.keys() - new_extensions.keys())
findings["added_extension_namespaces"] = sorted(new_extensions.keys() - old_extensions.keys())
findings["changed_extension_bindings"] = [
    namespace for namespace in sorted(old_extensions.keys() & new_extensions.keys())
    if {key: old_extensions[namespace][key] for key in ("namespace", "status", "executable")}
    != {key: new_extensions[namespace][key] for key in ("namespace", "status", "executable")}
]
findings["removed_metadata_routes"] = [list(path) for path in sorted(old_metadata.keys() - new_metadata.keys())]
findings["added_metadata_routes"] = [list(path) for path in sorted(new_metadata.keys() - old_metadata.keys())]
findings["metadata_missing_parents"] = [row["path"] for row in new_metadata.values() if not row["metadata_parent_present"]]
findings["failed_or_empty_help"] = [
    {"path": row["path"], "kind": row["kind"], "exit_code": row["exit_code"]}
    for row in AFTER["captures"]
    if row["exit_code"] != 0 or not row["stdout"].strip()
]
metadata_mismatch = []
for path, row in new_metadata.items():
    namespace, *route = path
    manifest = live_manifests[namespace]
    expected = manifest.help[" ".join(route)].rstrip("\n")
    captured = new_captures[("extension_metadata", path)]["stdout"].rstrip("\n")
    if captured != expected:
        metadata_mismatch.append(list(path))
findings["metadata_output_mismatch"] = metadata_mismatch
findings["costs"] = {
    label: {
        kind: costs([row for row in data["captures"] if row["kind"] == kind])
        for kind in ("click", "extension_metadata", "manual_help")
    }
    for label, data in (("before", BEFORE), ("after", AFTER))
}
representative = (
    (), ("create",), ("claim",), ("check",), ("db",), ("search",),
    ("graph",), ("graph", "query"),
    ("jobs",), ("jobs", "search"), ("browser",), ("service",),
)
findings["representative_costs"] = [
    {
        "path": list(path),
        "before_estimated_tokens": next(
            (row["estimated_tokens"] for (kind, key), row in old_captures.items() if key == path), None
        ),
        "after_estimated_tokens": next(
            (row["estimated_tokens"] for (kind, key), row in new_captures.items() if key == path), None
        ),
    }
    for path in representative
]

destination = HERE / "comparison.json"
destination.write_text(json.dumps(findings, indent=2) + "\n")
print(json.dumps({key: value for key, value in findings.items() if key not in {"costs", "representative_costs"}}))
print(destination)
