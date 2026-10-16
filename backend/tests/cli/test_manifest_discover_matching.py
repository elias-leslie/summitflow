"""st tools manifest --discover word/substring matching and ranked suggestions."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cli.commands.tools import app as tools_app
from cli.lib.usage import UsageSpec, discover_matches, discover_suggestions

runner = CliRunner()

REGISTRY = [
    UsageSpec(surface="st.service.rebuild", cmd="st service rebuild <project>"),
    UsageSpec(surface="st.service.observe", cmd="st service observe <project>"),
    UsageSpec(surface="st.sessions.send", cmd="st sessions send", when="message another agent"),
    UsageSpec(surface="st.neri.hunt.begin", cmd="st neri hunt begin"),
    UsageSpec(surface="st.neri.report.review_packet", cmd="st neri report review-packet",
              why="commercial submission packet"),
    UsageSpec(surface="st.monitor.status", cmd="st monitor status", on_demand="host and project troubleshooting"),
    UsageSpec(surface="st.vm.repair", cmd="st vm repair", on_demand="VM repair"),
]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> list[UsageSpec]:
    from cli.commands import tools

    monkeypatch.setattr(tools, "collect_usage_specs", lambda app: REGISTRY)
    return REGISTRY


def _discover(query: str) -> tuple[int, dict | None, str]:
    result = runner.invoke(tools_app, ["manifest", "--discover", query, "--format", "json"])
    payload = json.loads(result.output) if result.exit_code == 0 else None
    return result.exit_code, payload, result.output


@pytest.mark.parametrize(("query", "surfaces", "matched"), [
    # Word of a workflow label, any case and delimiter.
    ("host", ["st.monitor.status"], ["workflow 'host and project troubleshooting'"]),
    ("Troubleshooting", ["st.monitor.status"], ["workflow 'host and project troubleshooting'"]),
    ("host-troubleshooting", ["st.monitor.status"], ["workflow 'host and project troubleshooting'"]),
    # Words naming a nested family path.
    ("neri hunt", ["st.neri.hunt.begin"], ["st.neri.hunt"]),
    ("neri-hunt", ["st.neri.hunt.begin"], ["st.neri.hunt"]),
    ("hunts", ["st.neri.hunt.begin"], ["st.neri.hunt"]),
    # Plural and singular name the same family.
    ("services", ["st.service.rebuild", "st.service.observe"], ["st.service"]),
    ("session", ["st.sessions.send"], ["st.sessions"]),
    # Substring of a label word when no whole word matches.
    ("troubleshoot", ["st.monitor.status"], ["workflow 'host and project troubleshooting'"]),
    ("packet", ["st.neri.report.review_packet"], ["st.neri.report.review_packet"]),
])
def test_discover_matches_label_words_and_names_what_matched(registry, query, surfaces, matched) -> None:
    code, payload, output = _discover(query)
    assert code == 0, output
    assert payload is not None
    assert [row["surface"] for row in payload["tools"]] == surfaces
    assert payload["discovery_matched"] == matched
    assert payload["discovery_query"] == query


def test_exact_family_keeps_its_unchanged_payload(registry) -> None:
    code, payload, output = _discover("service")
    assert code == 0, output
    assert payload is not None
    assert payload.keys() == {"manifest_version", "discovery_query", "tools"}


def test_whole_word_matches_win_over_substrings() -> None:
    specs = [UsageSpec(surface="st.vm.repair", on_demand="VM repair"), UsageSpec(surface="st.vmware.sync")]
    found, matched = discover_matches(specs, "vm")
    assert [spec.surface for spec in found] == ["st.vm.repair"]
    assert matched == []  # "st.vm" is an exact family
    found, matched = discover_matches(specs, "repai")
    assert [spec.surface for spec in found] == ["st.vm.repair"]
    # Two-letter words never match inside longer words.
    assert discover_matches([UsageSpec(surface="st.vmware.sync")], "vm") == ([], [])


@pytest.mark.parametrize(("query", "suggested"), [("sevice", "st.service"), ("nerii", "st.neri")])
def test_unknown_topic_lists_ranked_suggestions_without_substituting(registry, query, suggested) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", query, "--format", "json"])
    assert result.exit_code == 1
    assert "Unknown --discover topic" in result.output
    assert f"Did you mean: {suggested}" in result.output
    assert '"tools"' not in result.output


def test_unknown_topic_names_mentioning_surfaces_and_workflows(registry) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "commercial"])
    assert result.exit_code == 1
    assert "Surfaces mentioning it: st.neri.report.review_packet." in result.output
    # No near-miss label: list the workflows so a placeholder query still learns the vocabulary.
    assert "Workflows: VM repair, host and project troubleshooting." in result.output
    assert "--density full lists the complete catalogue." in result.output


def test_suggestions_rank_closest_label_first() -> None:
    labels, surfaces = discover_suggestions(REGISTRY, "sesions")
    assert labels[0] == "st.sessions"
    assert surfaces == []


def test_markdown_discovery_shows_matched_labels(registry) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "host", "--format", "markdown"])
    assert result.exit_code == 0, result.output
    assert "Matched: workflow 'host and project troubleshooting'" in result.output
