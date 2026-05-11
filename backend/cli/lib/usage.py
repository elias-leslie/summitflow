"""@usage decorator + registry for st tool-usage manifest.

Each `st <surface>` command carries its own policy (when/why/precautions/examples)
right next to the implementation. `st tools manifest` walks the Typer app tree at
manifest time and emits the registered specs, filtered by surface/task/agent/profile.

Co-locating policy with code is the single source of truth: changing a command
without updating its `@usage` is a PR-review concern, not a memory-hunting concern.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import typer

USAGE_ATTR = "__st_usage__"


@dataclass(frozen=True)
class UsageSpec:
    """Policy metadata for one CLI surface."""

    surface: str
    cmd: str = ""
    when: str = ""
    why: str = ""
    precautions: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    agent_slugs: tuple[str, ...] = ()
    consumer_profiles: tuple[str, ...] = ()
    tier: str = "reference"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"surface": self.surface, "tier": self.tier}
        if self.cmd:
            out["cmd"] = self.cmd
        if self.when:
            out["when"] = self.when
        if self.why:
            out["why"] = self.why
        if self.precautions:
            out["precautions"] = list(self.precautions)
        if self.examples:
            out["examples"] = list(self.examples)
        if self.task_types:
            out["task_types"] = list(self.task_types)
        if self.agent_slugs:
            out["agent_slugs"] = list(self.agent_slugs)
        if self.consumer_profiles:
            out["consumer_profiles"] = list(self.consumer_profiles)
        return out


def usage(
    *,
    surface: str,
    cmd: str = "",
    when: str = "",
    why: str = "",
    precautions: Iterable[str] = (),
    examples: Iterable[str] = (),
    task_types: Iterable[str] = (),
    agent_slugs: Iterable[str] = (),
    consumer_profiles: Iterable[str] = (),
    tier: str = "reference",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a UsageSpec to a Typer command callback.

    Apply *inside* `@app.command()`:

        @app.command()
        @usage(surface="st.service.rebuild", ...)
        def rebuild(...): ...
    """
    if not surface:
        raise ValueError("@usage requires a non-empty surface")
    if tier not in {"mandate", "guardrail", "reference"}:
        raise ValueError(f"@usage tier must be mandate|guardrail|reference, got {tier!r}")

    spec = UsageSpec(
        surface=surface,
        cmd=cmd,
        when=when,
        why=why,
        precautions=tuple(precautions),
        examples=tuple(examples),
        task_types=tuple(task_types),
        agent_slugs=tuple(agent_slugs),
        consumer_profiles=tuple(consumer_profiles),
        tier=tier,
    )

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, USAGE_ATTR, spec)
        return func

    return _decorator


def _walk(app: typer.Typer, seen: set[int]) -> Iterable[UsageSpec]:
    for cmd in getattr(app, "registered_commands", []):
        callback = getattr(cmd, "callback", None)
        if callback is None:
            continue
        spec = getattr(callback, USAGE_ATTR, None)
        if not isinstance(spec, UsageSpec):
            continue
        key = id(callback)
        if key in seen:
            continue
        seen.add(key)
        yield spec
    for group in getattr(app, "registered_groups", []):
        sub = getattr(group, "typer_instance", None)
        if isinstance(sub, typer.Typer):
            yield from _walk(sub, seen)


def collect_usage_specs(app: typer.Typer) -> list[UsageSpec]:
    """Return every UsageSpec reachable from `app`. Dedupes commands registered
    in more than one place (e.g. hoisted to root and re-exposed via add_typer)."""
    return list(_walk(app, set()))


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
        if task_type is not None and spec.task_types and task_type not in spec.task_types:
            continue
        if agent_slug is not None and spec.agent_slugs and agent_slug not in spec.agent_slugs:
            continue
        if consumer_profile is not None and spec.consumer_profiles and consumer_profile not in spec.consumer_profiles:
            continue
        out.append(spec)
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
          st.pulse: {cmd: st pulse --gate, when: session start + risky edits}

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
