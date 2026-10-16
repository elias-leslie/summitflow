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
    "st.search",
    "st.check",
    "st.db",
    "st.service.rebuild",
    "st.tools.status",
    "st.tools.adoption",
    "st.tools.audit",
    "st.tools.cost",
    "st.feedback.report",
    "st.agents.preview",
}

# Implementation floor for compact discovery and `adaptive` density. Ordinary
# task work must not require retrieving the complete catalogue.
_FLOOR_SURFACES = {
    "st.search",
    "st.context",
    "st.check",
    "st.db",
    "st.service.rebuild",
    "st.commit",
    "st.create",
    "st.claim",
    "st.done",
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
        cmd="st tools manifest --surface <exact-surface-id>",
        when="load precautions before using an omitted surface or on-demand workflow; IDs via --discover <family-or-workflow>",
        why="on-demand workflows: " + ", ".join(workflows) if workflows else "",
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


def discover_specs(specs: Iterable[UsageSpec], query: str) -> list[UsageSpec]:
    """Index registered ID families and normalized on-demand labels in registry order."""
    query = query.strip()
    if not query:
        raise ValueError("discovery query must not be empty")
    family = query if query.startswith("st.") else f"st.{query}"
    workflow = " ".join(query.casefold().replace("-", " ").replace("_", " ").split())
    out: list[UsageSpec] = []
    seen: set[str] = set()
    for spec in specs:
        label = " ".join(spec.on_demand.casefold().replace("-", " ").replace("_", " ").split())
        matches = spec.surface == family or spec.surface.startswith(family + ".") or (label and label == workflow)
        if matches and spec.surface not in seen:
            seen.add(spec.surface)
            out.append(spec)
    return out


def _words(value: str) -> list[str]:
    return value.casefold().replace("-", " ").replace("_", " ").replace(".", " ").split()


def _discovery_labels(specs: list[UsageSpec]) -> dict[str, tuple[tuple[str, ...], list[UsageSpec]]]:
    """Every family ID prefix ("st.neri.hunt") and workflow label, with its words and specs."""
    labels: dict[str, tuple[tuple[str, ...], list[UsageSpec]]] = {}
    for spec in specs:
        parts = spec.surface.split(".")
        for depth in range(2, len(parts) + 1):
            family = ".".join(parts[:depth])
            words = tuple(word for word in _words(family) if word != "st")
            labels.setdefault(family, (words, []))[1].append(spec)
        if spec.on_demand:
            label = f"workflow '{' '.join(_words(spec.on_demand))}'"
            labels.setdefault(label, (tuple(_words(spec.on_demand)), []))[1].append(spec)
    return labels


def _word_matches(query: str, word: str, *, exact: bool) -> bool:
    # Short query words ("vm", "ui", "db") match whole words only; singular and
    # plural ("service"/"services", "session"/"sessions") name the same word.
    if query in {word, word + "s"} or word == query + "s":
        return True
    return not exact and len(query) >= 3 and query in word


def discover_matches(specs: Iterable[UsageSpec], query: str) -> tuple[list[UsageSpec], list[str]]:
    """Exact discovery first; otherwise every label containing each query word.

    Returns the specs plus the labels that matched by word or substring (empty
    for an exact family or workflow match). Whole-word matches win over
    substrings. A surface is never substituted silently: callers show the
    matched labels, and manifest --surface still needs the exact ID.
    """
    spec_list = list(specs)
    exact = discover_specs(spec_list, query)
    if exact:
        return exact, []
    wanted = [word for word in _words(query) if word != "st"]
    if not wanted:
        return [], []
    labels = _discovery_labels(spec_list)
    for whole_words in (True, False):
        matched = [label for label, (words, _) in labels.items()
                   if all(any(_word_matches(item, word, exact=whole_words) for word in words) for item in wanted)]
        if matched:
            break
    # A family whose parent family also matched adds nothing to the index.
    shown = [label for label in matched
             if not any(other != label and label.startswith(other + ".") for other in matched)]
    selected = {id(spec) for label in shown for spec in labels[label][1]}
    out: list[UsageSpec] = []
    seen: set[str] = set()
    for spec in spec_list:
        if id(spec) in selected and spec.surface not in seen:
            seen.add(spec.surface)
            out.append(spec)
    return out, shown


def discover_suggestions(specs: Iterable[UsageSpec], query: str, limit: int = 5) -> tuple[list[str], list[str]]:
    """Ranked near-miss labels plus surfaces whose guidance mentions the query words."""
    from difflib import SequenceMatcher

    spec_list = list(specs)
    wanted = [word for word in _words(query) if word != "st"]
    joined = " ".join(wanted)
    if not wanted:
        return [], []
    scored: list[tuple[float, str]] = []
    for label, (words, _) in _discovery_labels(spec_list).items():
        # Suggest top-level families and workflows; deeper IDs come from the family index.
        if not label.startswith("workflow ") and label.count(".") > 1:
            continue
        score = max([SequenceMatcher(None, joined, " ".join(words)).ratio(),
                     *(SequenceMatcher(None, item, word).ratio() for item in wanted for word in words)])
        if score >= 0.75:
            scored.append((score, label))
    labels = [label for _, label in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]]
    mentions: list[tuple[int, str]] = []
    for spec in spec_list:
        text = " ".join([spec.cmd, spec.when, spec.why, *spec.precautions]).casefold()
        hits = sum(item in text for item in wanted if len(item) >= 4)
        if hits:
            mentions.append((hits, spec.surface))
    surfaces = [surface for _, surface in sorted(mentions, key=lambda item: -item[0])[:3]]
    return labels, surfaces


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
            include_core = spec.surface in _FLOOR_SURFACES or (spec.surface in _CORE_SURFACES and not spec.on_demand)
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


def render_inject(specs: Iterable[UsageSpec]) -> str:
    """Render specs in the token-lean injection form, one line per command.

    Shape:
        mandates:
        - st service rebuild <project> --detach — service/config/worker change — careful: explicit project; ...
        references:
        - st search "query" — optional ranked discovery

    Rules:
      - Group by tier as `mandates|guardrails|references:`
      - Each line is `cmd — when — why — careful: precautions`, omitting empty parts;
        surface ids stay out (`st tools manifest --surface` serves them)
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
            parts = [spec.cmd or spec.surface, spec.when, spec.why]
            if spec.precautions:
                parts.append("careful: " + "; ".join(spec.precautions))
            lines.append("- " + " — ".join(part for part in parts if part))
    return "\n".join(lines)
