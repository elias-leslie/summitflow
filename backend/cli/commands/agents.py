"""Agent management CLI for Agent Hub-backed settings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from ..lib.usage import usage
from ..output import output_error, output_json
from ._memory_crud_helpers import parse_csv_values
from .agents_api import agent_preview_api, agents_api, models_api
from .preview_formatters import print_preview_detail, print_preview_summary

app = typer.Typer(help="Agent management (Agent Hub)")

_SCORE_KEYS = ("coding", "reasoning", "planning", "tool_use", "instruction", "design")
_SCORE_LABELS = {
    "coding": "C",
    "reasoning": "R",
    "planning": "P",
    "tool_use": "T",
    "instruction": "I",
    "design": "D",
    "finance": "F",
    "verification": "V",
    "jenny": "J",
}
_FIT_WEIGHTS = {
    "finance": {"reasoning": 0.60, "planning": 0.25, "instruction": 0.15},
    "verification": {"reasoning": 0.55, "instruction": 0.25, "tool_use": 0.20},
    "jenny": {"planning": 0.45, "reasoning": 0.35, "tool_use": 0.20},
}
_ROUTING_MODES = {"manual_locked", "auto_shadow", "auto_canary", "auto"}
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class _MemoryFlags:
    memory_enabled: bool | None
    include_mandates: bool | None
    include_guardrails: bool | None
    include_references: bool | None
    continuity_enabled: bool | None
    continuity_max_sessions: int | None
    audience_tags: str | None
    add_audience_tags: str | None
    remove_audience_tags: str | None
    clear_audience_tags: bool
    exclude_tags: str | None
    add_exclude_tags: str | None
    remove_exclude_tags: str | None
    clear_exclude_tags: bool

    def any_set(self) -> bool:
        """Return True when any granular memory-config flag was provided."""
        return any(
            v is not None
            for v in (
                self.memory_enabled, self.include_mandates, self.include_guardrails,
                self.include_references, self.continuity_enabled, self.continuity_max_sessions,
                self.audience_tags, self.add_audience_tags, self.remove_audience_tags,
                self.exclude_tags, self.add_exclude_tags, self.remove_exclude_tags,
            )
        ) or self.clear_audience_tags or self.clear_exclude_tags


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        output_error(f"Invalid JSON in {label} file: {exc}")
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        output_error(f"{label} file must contain a JSON object")
        raise typer.Exit(1)
    return data


def _load_text_file(path: Path, label: str) -> str:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    return path.read_text(encoding="utf-8")


def _merge_tag_values(
    *,
    current: list[str],
    replace: str | None,
    add: str | None,
    remove: str | None,
    clear: bool,
    label: str,
) -> list[str] | None:
    """Merge tag update flags into one final ordered list."""
    if replace is not None and (add is not None or remove is not None or clear):
        output_error(f"Use either --{label}, --add-{label}, --remove-{label}, or --clear-{label}")
        raise typer.Exit(1)
    if clear and (add is not None or remove is not None):
        output_error(f"Use either --clear-{label} or add/remove flags, not both")
        raise typer.Exit(1)
    if replace is not None:
        return parse_csv_values(replace) or []
    if clear:
        return []
    if add is None and remove is None:
        return None
    merged = list(current)
    for tag in parse_csv_values(add) or []:
        if tag not in merged:
            merged.append(tag)
    for tag in parse_csv_values(remove) or []:
        if tag in merged:
            merged.remove(tag)
    return merged


def _build_memory_config_patch(slug: str, f: _MemoryFlags) -> dict[str, Any]:
    """Return merged memory_config changes for granular CLI flags."""
    agent = agents_api("GET", f"/{slug}")
    cfg: dict[str, Any] = dict(agent.get("memory_config") or {})

    _SCALAR_MAP = [
        ("injection_enabled", f.memory_enabled),
        ("include_mandates", f.include_mandates),
        ("include_guardrails", f.include_guardrails),
        ("include_references", f.include_references),
        ("continuity_enabled", f.continuity_enabled),
        ("continuity_max_sessions", f.continuity_max_sessions),
    ]
    for key, val in _SCALAR_MAP:
        if val is not None:
            cfg[key] = val

    for field, replace, add, remove, clear, label in [
        ("audience_tags", f.audience_tags, f.add_audience_tags,
         f.remove_audience_tags, f.clear_audience_tags, "audience-tags"),
        ("exclude_tags", f.exclude_tags, f.add_exclude_tags,
         f.remove_exclude_tags, f.clear_exclude_tags, "exclude-tags"),
    ]:
        merged = _merge_tag_values(
            current=[str(t) for t in cfg.get(field) or []],
            replace=replace, add=add, remove=remove, clear=clear, label=label,
        )
        if merged is not None:
            cfg[field] = merged

    return cfg


def _resolve_memory_config(
    slug: str,
    f: _MemoryFlags,
    memory_config_file: Path | None,
    clear_memory_config: bool,
) -> dict[str, Any] | None | bool:
    """Validate and resolve memory-config flags.

    Returns a dict (new config), None (clear), or False (no change).
    """
    granular = f.any_set()
    if memory_config_file is not None and clear_memory_config:
        output_error("Use either --memory-config-file or --clear-memory-config, not both")
        raise typer.Exit(1)
    if granular and (memory_config_file is not None or clear_memory_config):
        output_error("Use either granular memory-config flags or --memory-config-file/--clear-memory-config, not both")
        raise typer.Exit(1)
    if memory_config_file is not None:
        return _load_json_file(memory_config_file, "Memory config")
    if clear_memory_config:
        return None
    if granular:
        return _build_memory_config_patch(slug, f)
    return False


def _print_agent(agent: dict[str, Any]) -> None:
    print(
        f"{agent['slug']} | primary={agent['primary_model_id']} | "
        f"fallbacks={len(agent.get('fallback_models') or [])} | version={agent['version']}"
    )
    print(
        f"  active={agent['is_active']} coding={agent['is_coding_agent']} "
        f"thinking={agent.get('thinking_level') or '-'} temp={agent['temperature']}"
    )
    print(f"  memory_config={json.dumps(agent.get('memory_config'), sort_keys=True)}")


def _agent_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    agents = result.get("agents") if isinstance(result, dict) else None
    return [a for a in agents if isinstance(a, dict)] if isinstance(agents, list) else []


def _score_map() -> dict[str, dict[str, Any]]:
    result = models_api()
    models = result.get("models") if isinstance(result, dict) else None
    if not isinstance(models, list):
        return {}
    return {
        str(model["id"]): model
        for model in models
        if isinstance(model, dict) and model.get("id")
    }


def _focus_score_key(agent: dict[str, Any]) -> str:
    slug = str(agent.get("slug") or "").lower()
    text = f"{slug} {agent.get('name', '')} {agent.get('description', '')}".lower()
    words = set(_WORD_RE.findall(text))
    if slug == "persona" or words & {"jenny"}:
        return "jenny"
    if slug == "verifier" or words & {"verifier", "verification"}:
        return "verification"
    if words & {"design", "ui", "ux", "mockup", "site", "visual", "image", "designer"}:
        return "design"
    if agent.get("is_coding_agent"):
        return "coding"
    if words & {"finance", "financial", "equity", "trade", "trading", "risk", "investment", "market", "portfolio"}:
        return "finance"
    if words & {"plan", "planner", "planning", "triage", "triager", "supervisor", "orchestrator", "committee"}:
        return "planning"
    if words & {"review", "reviewer", "critic", "audit", "auditor", "validator", "extract", "extractor"}:
        return "instruction"
    if words & {"research", "researcher", "analyst", "reason", "reasoner"}:
        return "reasoning"
    return "instruction"


def _model_scores(model: dict[str, Any] | None) -> dict[str, Any]:
    scores = model.get("scores") if isinstance(model, dict) else None
    return scores if isinstance(scores, dict) else {}


def _score_value(model: dict[str, Any] | None, key: str) -> str:
    scores = _model_scores(model)
    weights = _FIT_WEIGHTS.get(key)
    if weights:
        values = [
            float(scores[score_key]) * weight
            for score_key, weight in weights.items()
            if isinstance(scores.get(score_key), (int, float))
        ]
        value = round(sum(values)) if len(values) == len(weights) else None
    else:
        value = scores.get(key)
    return str(value) if value is not None else "-"


def _format_score_vector(model: dict[str, Any] | None) -> str:
    scores = _model_scores(model)
    parts = []
    for key in _SCORE_KEYS:
        value = scores.get(key)
        parts.append(f"{_SCORE_LABELS[key]}{value if value is not None else '-'}")
    return " ".join(parts)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _format_slugs(agents: list[dict[str, Any]], limit: int = 8) -> str:
    slugs = [str(a.get("slug") or "-") for a in sorted(agents, key=lambda a: str(a.get("slug") or ""))]
    if len(slugs) <= limit:
        return ",".join(slugs)
    return f"{','.join(slugs[:limit])},+{len(slugs) - limit}"


def _print_compact_agents(result: dict[str, Any], *, with_scores: bool) -> None:
    agents = _agent_items(result)
    scores_by_model = _score_map()
    total = result.get("total", len(agents))
    print(f"AGENTS[{len(agents)} shown/{total} total]")
    headers = ["slug", "kind", "focus", "fit", "primary", "fb", "esc"]
    if with_scores:
        headers.append("scores")
    rows: list[list[str]] = []
    for agent in agents:
        model_id = str(agent.get("primary_model_id") or "-")
        model = scores_by_model.get(model_id)
        focus = _focus_score_key(agent)
        row = [
            str(agent.get("slug") or "-"),
            "code" if agent.get("is_coding_agent") else "text",
            _SCORE_LABELS[focus],
            _score_value(model, focus),
            model_id,
            str(len(agent.get("fallback_models") or [])),
            str(agent.get("escalation_model_id") or "-"),
        ]
        if with_scores:
            row.append(_format_score_vector(model))
        rows.append(row)
    _print_table(headers, rows)


def _print_agents_by_model(result: dict[str, Any]) -> None:
    agents = _agent_items(result)
    scores_by_model = _score_map()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        grouped.setdefault(str(agent.get("primary_model_id") or "-"), []).append(agent)
    rows: list[list[str]] = []
    for model_id, model_agents in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        model = scores_by_model.get(model_id)
        rows.append([
            model_id,
            str(len(model_agents)),
            _format_score_vector(model),
            _format_slugs(model_agents),
        ])
    print(f"AGENT_MODELS[{len(grouped)} primary models/{len(agents)} agents]")
    _print_table(["primary", "agents", "scores", "slugs"], rows)


def _build_agent_payload(
    *,
    name: str | None,
    description: str | None,
    primary_model: str | None,
    escalation_model: str | None,
    temperature: float | None,
    thinking_level: str | None,
    active: bool | None,
    coding_agent: bool | None,
    fallback_model: list[str] | None,
    change_reason: str | None,
    system_prompt_file: Path | None,
) -> dict[str, Any]:
    """Build the base update payload from scalar CLI flags."""
    payload: dict[str, Any] = {}
    for key, val in [
        ("name", name), ("description", description), ("primary_model_id", primary_model),
        ("escalation_model_id", escalation_model),
        ("temperature", temperature), ("thinking_level", thinking_level),
        ("is_active", active), ("is_coding_agent", coding_agent),
        ("fallback_models", fallback_model), ("change_reason", change_reason),
    ]:
        if val is not None:
            payload[key] = val
    if system_prompt_file is not None:
        payload["system_prompt"] = _load_text_file(system_prompt_file, "System prompt")
    return payload


def _default_manual_route(routing: dict[str, Any]) -> dict[str, Any] | None:
    routes = routing.get("manual_routes")
    if not isinstance(routes, list):
        return None
    for route in routes:
        if isinstance(route, dict) and route.get("workload_profile") is None:
            return route
    return None


def _sync_manual_route(
    slug: str,
    *,
    primary_model: str | None,
    fallback_model: list[str] | None,
    escalation_model: str | None,
    routing_mode: str | None,
    change_reason: str | None,
) -> None:
    """Mirror CLI model flags into Agent Hub routing tables."""
    if routing_mode is not None and routing_mode not in _ROUTING_MODES:
        output_error(f"Invalid routing mode: {routing_mode}")
        raise typer.Exit(1)
    if not any([primary_model, fallback_model is not None, escalation_model, routing_mode]):
        return

    payload: dict[str, Any] = {}
    if routing_mode is not None:
        payload["default_routing_mode"] = routing_mode

    if primary_model or fallback_model is not None or escalation_model:
        payload.setdefault("default_routing_mode", "manual_locked")
        routing = agents_api("GET", f"/{slug}/routing")
        current_route = _default_manual_route(routing) or {}
        current_primary = current_route.get("primary_model_id")
        resolved_primary = primary_model or (str(current_primary) if current_primary else None)
        if not resolved_primary:
            output_error("--primary-model is required when no default manual route exists.")
            raise typer.Exit(1)
        current_fallbacks = current_route.get("fallback_models")
        payload["manual_route"] = {
            "primary_model_id": resolved_primary,
            "fallback_models": fallback_model if fallback_model is not None else list(current_fallbacks or []),
            "escalation_model_id": escalation_model
            if escalation_model is not None
            else current_route.get("escalation_model_id"),
            "reason": change_reason or "st agents update manual route",
            "owner": "st agents update",
            "enabled": True,
        }

    agents_api("PUT", f"/{slug}/routing", json=payload)


def _collect_memory_flags(
    *,
    memory_enabled: bool | None,
    include_mandates: bool | None,
    include_guardrails: bool | None,
    include_references: bool | None,
    continuity_enabled: bool | None,
    continuity_max_sessions: int | None,
    audience_tags: str | None,
    add_audience_tags: str | None,
    remove_audience_tags: str | None,
    clear_audience_tags: bool,
    exclude_tags: str | None,
    add_exclude_tags: str | None,
    remove_exclude_tags: str | None,
    clear_exclude_tags: bool,
) -> _MemoryFlags:
    """Collect memory-related CLI flags into a _MemoryFlags dataclass."""
    return _MemoryFlags(
        memory_enabled=memory_enabled, include_mandates=include_mandates,
        include_guardrails=include_guardrails, include_references=include_references,
        continuity_enabled=continuity_enabled, continuity_max_sessions=continuity_max_sessions,
        audience_tags=audience_tags, add_audience_tags=add_audience_tags,
        remove_audience_tags=remove_audience_tags, clear_audience_tags=clear_audience_tags,
        exclude_tags=exclude_tags, add_exclude_tags=add_exclude_tags,
        remove_exclude_tags=remove_exclude_tags, clear_exclude_tags=clear_exclude_tags,
    )


@app.callback(invoke_without_command=True)
def agents_default(ctx: typer.Context) -> None:
    """List agents by default."""
    if ctx.invoked_subcommand is None:
        list_agents()


@app.command("list")
def list_agents(
    active_only: Annotated[bool, typer.Option("--active-only/--all")] = True,
    coding_only: Annotated[bool | None, typer.Option("--coding-only/--non-coding")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print full API payload.")] = False,
    scores: Annotated[bool, typer.Option("--scores", help="Show compact assignment rows with all score dimensions.")] = False,
    by_model: Annotated[bool, typer.Option("--by-model", help="Group active agents by primary model.")] = False,
) -> None:
    """List agents."""
    params: dict[str, Any] = {
        "active_only": str(active_only).lower(),
        "limit": limit,
        "offset": offset,
    }
    if coding_only is not None:
        params["is_coding_agent"] = str(coding_only).lower()
    result = agents_api("GET", "", params=params)
    if as_json:
        output_json(result)
        return
    if by_model:
        _print_agents_by_model(result)
        return
    _print_compact_agents(result, with_scores=scores)


@app.command("get")
def get_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
) -> None:
    """Get one agent by slug."""
    agent = agents_api("GET", f"/{slug}")
    _print_agent(agent)


@app.command("create")
def create_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    name: Annotated[str, typer.Argument(help="Display name")],
    primary_model: Annotated[str, typer.Option("--primary-model", help="Primary model id.")],
    system_prompt_file: Annotated[Path, typer.Option("--system-prompt-file", help="System prompt file.")],
    description: Annotated[str | None, typer.Option("--description")] = None,
    temperature: Annotated[float, typer.Option("--temperature", min=0.0, max=2.0)] = 0.1,
    thinking_level: Annotated[str | None, typer.Option("--thinking-level")] = None,
    verbosity_level: Annotated[str | None, typer.Option("--verbosity-level")] = None,
    active: Annotated[bool, typer.Option("--active/--inactive")] = True,
    coding_agent: Annotated[bool, typer.Option("--coding-agent/--non-coding-agent")] = False,
    fallback_model: Annotated[list[str] | None, typer.Option("--fallback-model")] = None,
    escalation_model: Annotated[str | None, typer.Option("--escalation-model")] = None,
    memory_config_file: Annotated[Path | None, typer.Option("--memory-config-file")] = None,
) -> None:
    """Create an agent using the Agent Hub API."""
    payload: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "system_prompt": _load_text_file(system_prompt_file, "System prompt"),
        "primary_model_id": primary_model,
        "temperature": temperature,
        "is_active": active,
        "is_coding_agent": coding_agent,
    }
    for key, val in [
        ("description", description),
        ("thinking_level", thinking_level),
        ("verbosity_level", verbosity_level),
        ("fallback_models", fallback_model),
        ("escalation_model_id", escalation_model),
    ]:
        if val is not None:
            payload[key] = val
    if memory_config_file is not None:
        payload["memory_config"] = _load_json_file(memory_config_file, "Memory config")
    _print_agent(agents_api("POST", "", json=payload))


@app.command("preview")
@usage(
    surface="st.agents.preview",
    cmd="st agents preview <slug> --json",
    when="inspect agent prompt/context size; verify injection",
    task_types=("config", "prompt-tuning", "verification"),
    tier="reference",
)
def preview_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    mode: Annotated[str, typer.Option("--mode", "-m", help="Preview mode: chat, heartbeat, wake, review")] = "chat",
    project: Annotated[str | None, typer.Option("--project", "-P", help="Optional project scope")] = None,
    phase: Annotated[str | None, typer.Option("--phase", help="Optional phase/event hint")] = None,
    prompt_input: Annotated[str | None, typer.Option("--input", help="Optional task input placeholder")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON response")] = False,
    full_context_only: Annotated[bool, typer.Option("--full-context-only", help="Print only the effective full context")] = False,
    show_content: Annotated[bool, typer.Option("--show-content", help="Print full section bodies plus full context.")] = False,
) -> None:
    """Show the effective runtime prompt/context preview for an agent."""
    preview = agent_preview_api(
        slug, task_type=mode, project_id=project, phase=phase, prompt_input=prompt_input,
    )
    if as_json:
        output_json(preview)
        return

    full_context = preview.get("full_context") or preview.get("combined_prompt") or ""
    if full_context_only:
        print(full_context)
        return

    if show_content:
        print_preview_detail(preview, mode, project, phase, full_context)
        return

    print_preview_summary(preview, mode, project, phase)


@app.command("update")
def update_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    primary_model: Annotated[str | None, typer.Option("--primary-model")] = None,
    escalation_model: Annotated[str | None, typer.Option("--escalation-model")] = None,
    routing_mode: Annotated[str | None, typer.Option("--routing-mode")] = None,
    temperature: Annotated[float | None, typer.Option("--temperature", min=0.0, max=2.0)] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking-level")] = None,
    active: Annotated[bool | None, typer.Option("--active/--inactive")] = None,
    coding_agent: Annotated[bool | None, typer.Option("--coding-agent/--non-coding-agent")] = None,
    fallback_model: Annotated[list[str] | None, typer.Option("--fallback-model")] = None,
    system_prompt_file: Annotated[Path | None, typer.Option("--system-prompt-file")] = None,
    memory_config_file: Annotated[Path | None, typer.Option("--memory-config-file")] = None,
    clear_memory_config: Annotated[bool, typer.Option("--clear-memory-config")] = False,
    memory_enabled: Annotated[bool | None, typer.Option("--memory-enabled/--memory-disabled")] = None,
    include_mandates: Annotated[bool | None, typer.Option("--include-mandates/--no-include-mandates")] = None,
    include_guardrails: Annotated[bool | None, typer.Option("--include-guardrails/--no-include-guardrails")] = None,
    include_references: Annotated[bool | None, typer.Option("--include-references/--no-include-references")] = None,
    continuity_enabled: Annotated[bool | None, typer.Option("--continuity-enabled/--no-continuity-enabled")] = None,
    continuity_max_sessions: Annotated[int | None, typer.Option("--continuity-max-sessions", min=1, max=20)] = None,
    audience_tags: Annotated[str | None, typer.Option("--audience-tags")] = None,
    add_audience_tags: Annotated[str | None, typer.Option("--add-audience-tags")] = None,
    remove_audience_tags: Annotated[str | None, typer.Option("--remove-audience-tags")] = None,
    clear_audience_tags: Annotated[bool, typer.Option("--clear-audience-tags")] = False,
    exclude_tags: Annotated[str | None, typer.Option("--exclude-tags")] = None,
    add_exclude_tags: Annotated[str | None, typer.Option("--add-exclude-tags")] = None,
    remove_exclude_tags: Annotated[str | None, typer.Option("--remove-exclude-tags")] = None,
    clear_exclude_tags: Annotated[bool, typer.Option("--clear-exclude-tags")] = False,
    change_reason: Annotated[str | None, typer.Option("--change-reason")] = None,
) -> None:
    """Update an agent using the Agent Hub API."""
    payload = _build_agent_payload(
        name=name, description=description, primary_model=primary_model, temperature=temperature,
        escalation_model=escalation_model, thinking_level=thinking_level, active=active, coding_agent=coding_agent,
        fallback_model=fallback_model, change_reason=change_reason, system_prompt_file=system_prompt_file,
    )
    mem = _collect_memory_flags(
        memory_enabled=memory_enabled, include_mandates=include_mandates,
        include_guardrails=include_guardrails, include_references=include_references,
        continuity_enabled=continuity_enabled, continuity_max_sessions=continuity_max_sessions,
        audience_tags=audience_tags, add_audience_tags=add_audience_tags,
        remove_audience_tags=remove_audience_tags, clear_audience_tags=clear_audience_tags,
        exclude_tags=exclude_tags, add_exclude_tags=add_exclude_tags, remove_exclude_tags=remove_exclude_tags, clear_exclude_tags=clear_exclude_tags,
    )
    memory_result = _resolve_memory_config(slug, mem, memory_config_file, clear_memory_config)
    if memory_result is not False:
        payload["memory_config"] = memory_result
    has_routing_update = any([primary_model, fallback_model is not None, escalation_model, routing_mode])
    if not payload and not has_routing_update:
        output_error("Nothing to update. Provide at least one update flag.")
        raise typer.Exit(1)
    updated = agents_api("PUT", f"/{slug}", json=payload) if payload else agents_api("GET", f"/{slug}")
    _sync_manual_route(
        slug,
        primary_model=primary_model,
        fallback_model=fallback_model,
        escalation_model=escalation_model,
        routing_mode=routing_mode,
        change_reason=change_reason,
    )
    _print_agent(updated)
