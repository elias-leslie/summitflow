"""Compare installed manifest route/option/default inventory with frozen owner captures."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cli.main import app


HERE = Path(__file__).resolve().parent
OWNER_CAPTURES = HERE.parent / "extensions"


def flags(text: str) -> set[str]:
    section = text.split("Options:", 1)[-1] if "Options:" in text else ""
    section = section.split("Commands:", 1)[0]
    return set(re.findall(r"(?<![\w])--[a-z][a-z0-9-]*", section))


def defaults(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", value.strip())
        for value in re.findall(r"\[default:(.*?)\]", text, re.I | re.S)
    ]


rows = []
for record in app._st_extensions.records:  # type: ignore[attr-defined]
    binding, manifest = record.binding, record.manifest
    if binding is None or manifest is None:
        continue
    capture = json.loads((OWNER_CAPTURES / f"{binding.namespace}.json").read_text())
    owner_help = capture["owner_description"]["help"]
    manifest_help = manifest.help
    route_differences = {
        "owner_only": sorted(owner_help.keys() - manifest_help.keys()),
        "manifest_only": sorted(manifest_help.keys() - owner_help.keys()),
    }
    option_differences = []
    default_value_differences = []
    for route in owner_help.keys() & manifest_help.keys():
        owner_flags, manifest_flags = flags(owner_help[route]), flags(manifest_help[route])
        if owner_flags != manifest_flags:
            option_differences.append(
                {"route": route, "owner_only": sorted(owner_flags - manifest_flags), "manifest_only": sorted(manifest_flags - owner_flags)}
            )
        owner_defaults = defaults(owner_help[route])
        manifest_defaults = defaults(manifest_help[route])
        if owner_defaults != manifest_defaults:
            default_value_differences.append(
                {"route": route, "owner": owner_defaults, "manifest": manifest_defaults}
            )
    rows.append(
        {
            "namespace": binding.namespace,
            "owner_revision_at_capture": capture["owner_revision"],
            "owner_help_routes": len(owner_help),
            "manifest_help_routes": len(manifest_help),
            "route_differences": route_differences,
            "option_name_differences": sorted(option_differences, key=lambda row: row["route"]),
            "default_value_differences": sorted(default_value_differences, key=lambda row: row["route"]),
        }
    )

destination = HERE / "owner-option-parity.json"
destination.write_text(json.dumps({"rows": rows}, indent=2) + "\n")
print(destination)
print(
    json.dumps(
        {
            "namespaces": len(rows),
            "owner_help_routes": sum(row["owner_help_routes"] for row in rows),
            "manifest_help_routes": sum(row["manifest_help_routes"] for row in rows),
            "route_differences": sum(bool(row["route_differences"]["owner_only"] or row["route_differences"]["manifest_only"]) for row in rows),
            "option_name_differences": sum(len(row["option_name_differences"]) for row in rows),
            "default_value_differences": sum(len(row["default_value_differences"]) for row in rows),
        }
    )
)
