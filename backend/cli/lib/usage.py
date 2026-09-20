"""@usage decorator + registry for st tool-usage manifest.

Each `st <surface>` command carries its own policy (when/why/precautions/examples)
right next to the implementation. `st tools manifest` walks the Typer app tree at
manifest time and emits the registered specs, filtered by surface/task/agent/profile.

Co-locating policy with code is the single source of truth: changing a command
without updating its `@usage` is a PR-review concern, not a memory-hunting concern.
"""

from __future__ import annotations

from collections.abc import Iterable

from st_sdk.usage import UsageSpec as UsageSpec
from st_sdk.usage import collect_usage_specs as collect_usage_specs
from st_sdk.usage import usage as usage

VALID_MANIFEST_DENSITIES = ("core", "task", "full", "adaptive")

_CORE_SURFACES = {
    "st.pulse",
    "st.search",
    "st.check",
    "st.db",
    "st.service.rebuild",
    "st.memory.search",
    "st.memory.save",
    "st.memory.update",
    "st.tools.status",
    "st.tools.adoption",
    "st.tools.audit",
    "st.tools.cost",
    "st.feedback.report",
    "st.agents.preview",
}

# Always-on floor for the `adaptive` density: lifecycle/destructive surfaces that
# must inject regardless of usage telemetry (telemetry-independent safety net).
_FLOOR_SURFACES = {
    "st.pulse",
    "st.search",
    "st.context",
    "st.check",
    "st.db",
    "st.service.rebuild",
    "st.commit",
    "st.create",
    "st.claim",
    "st.done",
    "st.memory.search",
    "st.memory.save",
    "st.memory.update",
}

# Normalized (0-100) decay score at or above which a non-floor surface is
# injected by the adaptive density. Curation by signal, not a hardcoded count.
_ADAPTIVE_SCORE_THRESHOLD = 15.0


def _surface_score(surface: str, scores: dict[str, float] | None) -> float:
    """Look up a surface's usage score from a usage-key-keyed scores map.

    Scores are produced upstream keyed by `parse_st_command` keys ("db query",
    "pulse", "memory search"), which sit at a different granularity than manifest
    surfaces. Map the surface to its usage prefix ("st.db" -> "db",
    "st.memory.search" -> "memory search") and take the max score over matching
    keys, so a surface aggregates all of its sub-command traffic.
    """
    if not scores:
        return 0.0
    prefix = surface
    if prefix.startswith("st."):
        prefix = prefix[3:]
    prefix = prefix.replace(".", " ")
    best = 0.0
    for key, value in scores.items():
        if key == prefix or key.startswith(prefix + " "):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric > best:
                best = numeric
    return best


def _detail_spec(deferred_workflows: Iterable[str] = ()) -> UsageSpec:
    workflows = sorted(set(deferred_workflows))
    return UsageSpec(
        surface="st.details",
        cmd="st tools manifest --surface <surface>",
        when="before using an omitted surface or starting an on-demand workflow, load its full canonical guidance and follow its precautions; use unfiltered st tools manifest to discover surfaces",
        why="On-demand workflows: " + "; ".join(workflows) if workflows else "",
        tier="mandate",
    )


def _matches_task_type(task_types: Iterable[str], task_type: str) -> bool:
    """CLI hyphens and consumer snake_case identify the same workflow."""
    normalized = task_type.replace("-", "_")
    return any(value.replace("-", "_") == normalized for value in task_types)


def filter_specs(
    specs: Iterable[UsageSpec],
    *,
    surface: str | None = None,
    task_type: str | None = None,
    agent_slug: str | None = None,
    consumer_profile: str | None = None,
) -> list[UsageSpec]:
    """Filter specs by exact surface, declared task_type, agent_slug, or consumer_profile.

    A spec with empty list for a field matches any value for that field.
    """
    out: list[UsageSpec] = []
    for spec in specs:
        if surface is not None and spec.surface != surface:
            continue
        if task_type is not None and spec.task_types and not _matches_task_type(spec.task_types, task_type):
            continue
        if agent_slug is not None and spec.agent_slugs and agent_slug not in spec.agent_slugs:
            continue
        if consumer_profile is not None and spec.consumer_profiles and consumer_profile not in spec.consumer_profiles:
            continue
        out.append(spec)
    return out


def select_specs_for_density(
    specs: Iterable[UsageSpec],
    *,
    density: str = "full",
    task_type: str | None = None,
    scores: dict[str, float] | None = None,
    score_threshold: float = _ADAPTIVE_SCORE_THRESHOLD,
) -> list[UsageSpec]:
    """Select a context-density slice while keeping @usage as the source of truth.

    Specialized on-demand workflows require a declared task match. History
    alone cannot activate them. Omitted guidance stays discoverable and must
    be loaded before use; the implementation floor is always retained.
    """
    if density not in VALID_MANIFEST_DENSITIES:
        expected = "|".join(VALID_MANIFEST_DENSITIES)
        raise ValueError(f"density must be {expected}, got {density!r}")

    spec_list = list(specs)
    if density == "full":
        return spec_list

    out: list[UsageSpec] = []
    seen: set[str] = set()
    deferred_workflows: set[str] = set()
    for spec in spec_list:
        include_task = bool(task_type and _matches_task_type(spec.task_types, task_type))
        if density == "adaptive":
            include = (
                spec.surface in _FLOOR_SURFACES
                or include_task
                or (not spec.on_demand and _surface_score(spec.surface, scores) >= score_threshold)
            )
        else:
            include_core = spec.surface in _CORE_SURFACES and not spec.on_demand
            include = include_core or (density != "core" and include_task)
        if not include:
            if spec.on_demand:
                deferred_workflows.add(spec.on_demand)
            continue
        if spec.surface in seen:
            continue
        seen.add(spec.surface)
        out.append(spec)

    if "st.details" not in seen:
        out.append(_detail_spec(deferred_workflows))
    return out


_TIER_GROUP = {"mandate": "mandates", "guardrail": "guardrails", "reference": "references"}


def _quote_yaml(value: str) -> str:
    """Quote a YAML scalar only when required by structure-sensitive characters."""
    needs_quote = (
        not value
        or value[0] in "!&*?|>%@`,[]{}#"
        or ": " in value
        or value.endswith(":")
        or value.strip() != value
    )
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_inject(specs: Iterable[UsageSpec]) -> str:
    """Render specs in the token-optimal injection form.

    Shape:
        mandates:
          st.service.rebuild:
            cmd: st service rebuild <project> --detach
            when: service/config/worker change
            careful: st pulse --gate first; explicit project; --include-all-workers only when intentional
        references:
          st.pulse: {cmd: st pulse --gate, when: implementation ownership + lane state}

    Rules:
      - Group by tier as `mandates|guardrails|references:`
      - Surfaces with only `cmd` (+ optional `when`) inline as flow-mapping
      - Precautions collapse into one `dont:` line, semicolon-joined
      - `examples`, `task_types`, `agent_slugs`, `consumer_profiles`, and per-entry tier are stripped
    """
    grouped: dict[str, list[UsageSpec]] = {"mandates": [], "guardrails": [], "references": []}
    for spec in specs:
        grouped[_TIER_GROUP.get(spec.tier, "references")].append(spec)

    lines: list[str] = []
    for group in ("mandates", "guardrails", "references"):
        bucket = grouped[group]
        if not bucket:
            continue
        lines.append(f"{group}:")
        for spec in bucket:
            inline_ok = spec.cmd and not spec.precautions and not spec.why
            if inline_ok and not spec.when:
                lines.append(f"  {spec.surface}: {_quote_yaml(spec.cmd)}")
                continue
            if inline_ok:
                lines.append(
                    f"  {spec.surface}: {{cmd: {_quote_yaml(spec.cmd)}, when: {_quote_yaml(spec.when)}}}"
                )
                continue
            lines.append(f"  {spec.surface}:")
            if spec.cmd:
                lines.append(f"    cmd: {_quote_yaml(spec.cmd)}")
            if spec.when:
                lines.append(f"    when: {_quote_yaml(spec.when)}")
            if spec.why:
                lines.append(f"    why: {_quote_yaml(spec.why)}")
            if spec.precautions:
                joined = "; ".join(spec.precautions)
                lines.append(f"    careful: {_quote_yaml(joined)}")
    return "\n".join(lines)
