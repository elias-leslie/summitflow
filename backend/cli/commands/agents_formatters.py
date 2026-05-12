"""Formatting helpers for the Agent Hub agents CLI."""

from __future__ import annotations

import re
from typing import Any

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
_WORD_RE = re.compile(r"[a-z0-9]+")


def agent_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    agents = result.get("agents") if isinstance(result, dict) else None
    return [a for a in agents if isinstance(a, dict)] if isinstance(agents, list) else []


def score_map(models_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    models = models_result.get("models") if isinstance(models_result, dict) else None
    if not isinstance(models, list):
        return {}
    return {
        str(model["id"]): model
        for model in models
        if isinstance(model, dict) and model.get("id")
    }


def focus_score_key(agent: dict[str, Any]) -> str:
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


def model_scores(model: dict[str, Any] | None) -> dict[str, Any]:
    scores = model.get("scores") if isinstance(model, dict) else None
    return scores if isinstance(scores, dict) else {}


def score_value(model: dict[str, Any] | None, key: str) -> str:
    scores = model_scores(model)
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


def format_score_vector(model: dict[str, Any] | None) -> str:
    scores = model_scores(model)
    parts = []
    for key in _SCORE_KEYS:
        value = scores.get(key)
        parts.append(f"{_SCORE_LABELS[key]}{value if value is not None else '-'}")
    return " ".join(parts)


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def format_slugs(agents: list[dict[str, Any]], limit: int = 8) -> str:
    slugs = [str(a.get("slug") or "-") for a in sorted(agents, key=lambda a: str(a.get("slug") or ""))]
    if len(slugs) <= limit:
        return ",".join(slugs)
    return f"{','.join(slugs[:limit])},+{len(slugs) - limit}"


def print_compact_agents(
    result: dict[str, Any],
    *,
    with_scores: bool,
    scores_by_model: dict[str, dict[str, Any]],
) -> None:
    agents = agent_items(result)
    total = result.get("total", len(agents))
    print(f"AGENTS[{len(agents)} shown/{total} total]")
    headers = ["slug", "kind", "focus", "fit", "primary", "fb", "esc"]
    if with_scores:
        headers.append("scores")
    rows: list[list[str]] = []
    for agent in agents:
        model_id = str(agent.get("primary_model_id") or "-")
        model = scores_by_model.get(model_id)
        focus = focus_score_key(agent)
        row = [
            str(agent.get("slug") or "-"),
            "code" if agent.get("is_coding_agent") else "text",
            _SCORE_LABELS[focus],
            score_value(model, focus),
            model_id,
            str(len(agent.get("fallback_models") or [])),
            str(agent.get("escalation_model_id") or "-"),
        ]
        if with_scores:
            row.append(format_score_vector(model))
        rows.append(row)
    print_table(headers, rows)


def print_agents_by_model(
    result: dict[str, Any],
    *,
    scores_by_model: dict[str, dict[str, Any]],
) -> None:
    agents = agent_items(result)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        grouped.setdefault(str(agent.get("primary_model_id") or "-"), []).append(agent)
    rows: list[list[str]] = []
    for model_id, model_agents in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        model = scores_by_model.get(model_id)
        rows.append([
            model_id,
            str(len(model_agents)),
            format_score_vector(model),
            format_slugs(model_agents),
        ])
    print(f"AGENT_MODELS[{len(grouped)} primary models/{len(agents)} agents]")
    print_table(["primary", "agents", "scores", "slugs"], rows)
