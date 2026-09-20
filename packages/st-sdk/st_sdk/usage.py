"""Portable usage metadata authored beside owner command callbacks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import typer

USAGE_ATTR = "__st_usage__"
USAGE_SPECS_ATTR = "__st_usage_specs__"


@dataclass(frozen=True)
class UsageSpec:
    surface: str
    cmd: str = ""
    when: str = ""
    why: str = ""
    precautions: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    agent_slugs: tuple[str, ...] = ()
    consumer_profiles: tuple[str, ...] = ()
    on_demand: str = ""
    tier: str = "reference"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"surface": self.surface, "tier": self.tier}
        for name in ("cmd", "when", "why"):
            if value := getattr(self, name):
                out[name] = value
        for name in (
            "precautions",
            "examples",
            "task_types",
            "agent_slugs",
            "consumer_profiles",
        ):
            if value := getattr(self, name):
                out[name] = list(value)
        if self.on_demand:
            out["on_demand"] = self.on_demand
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
    on_demand: str = "",
    tier: str = "reference",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach portable usage guidance to a Typer callback."""
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
        on_demand=on_demand,
        tier=tier,
    )

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, USAGE_ATTR, spec)
        return func

    return _decorator


def _callback_specs(callback: Callable[..., Any]) -> Iterable[UsageSpec]:
    """Yield legacy decorator metadata plus static multi-surface metadata."""
    spec = getattr(callback, USAGE_ATTR, None)
    if isinstance(spec, UsageSpec):
        yield spec
    specs = getattr(callback, USAGE_SPECS_ATTR, ())
    if isinstance(specs, (list, tuple)):
        yield from (item for item in specs if isinstance(item, UsageSpec))


def _walk(app: typer.Typer, seen: set[int]) -> Iterable[UsageSpec]:
    callback_info = getattr(app, "registered_callback", None)
    callback = getattr(callback_info, "callback", None) if callback_info is not None else None
    if callback is not None:
        for spec in _callback_specs(callback):
            if id(spec) not in seen:
                seen.add(id(spec))
                yield spec
    for command in getattr(app, "registered_commands", []):
        callback = getattr(command, "callback", None)
        if callback is None:
            continue
        for spec in _callback_specs(callback):
            if id(spec) not in seen:
                seen.add(id(spec))
                yield spec
    for group in getattr(app, "registered_groups", []):
        sub = getattr(group, "typer_instance", None)
        if isinstance(sub, typer.Typer):
            yield from _walk(sub, seen)


def collect_usage_specs(app: typer.Typer) -> list[UsageSpec]:
    """Return every unique UsageSpec reachable from a Typer app."""
    return list(_walk(app, set()))
