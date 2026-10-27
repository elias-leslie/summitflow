"""Agent-only tool-usage text stays terse (owner directive 2026-10-11).

Every manifest line (core + extensions) is delivered to agents. Ratchet: new or
trimmed surfaces must fit LINE_CAP; listed legacy surfaces may only shrink below
LEGACY_CAP; the full catalogue may not grow past TOTAL_CAP. Lower caps as text is
trimmed; never raise them to fit new text.
"""

from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from cli.commands.tools import app as tools_app

LINE_CAP = 120
LEGACY_CAP = 450
TOTAL_CAP = 23_500
LEGACY_OVER_CAP = frozenset({
    "st.aico.create", "st.aico.root.end", "st.aico.root.position", "st.aico.root.show",
    "st.aico.root.status", "st.aico.root.title", "st.aico.roots", "st.aico.widget.position",
    "st.aico.widget.status", "st.aico.widget.title", "st.browser", "st.design",
    "st.jobs.record-posting-source", "st.jobs.search", "st.learn.work", "st.monitor.logs",
    "st.monitor.status", "st.service.rebuild", "st.sessions.verify",
    "st.slopminer", "st.ui.gif", "st.web",
})
PADDING = re.compile(
    r"(?i)\b(please|it is (?:important|essential|crucial) (?:to|that)|make sure (?:to|that)|be sure to|"
    r"in order to|keep in mind|note that|remember to|don't forget|feel free|as mentioned)\b"
)


def _lines() -> dict[str, str]:
    result = CliRunner().invoke(tools_app, ["manifest", "--density", "full", "--format", "json"])
    assert result.exit_code == 0, result.output
    out = {}
    for row in json.loads(result.output)["tools"]:
        parts = [row.get("cmd") or row["surface"], row.get("when", ""), row.get("why", ""),
                 "; ".join(row.get("precautions") or ())]
        out[row["surface"]] = " — ".join(part for part in parts if part)
    return out


def _tokens(text: str) -> int:
    return len(text) // 4


def test_usage_lines_have_no_padding() -> None:
    hits = {surface: PADDING.findall(line) for surface, line in _lines().items() if PADDING.search(line)}
    assert not hits


def test_usage_lines_fit_token_caps() -> None:
    lines = _lines()
    over = {s: _tokens(line) for s, line in lines.items()
            if _tokens(line) > (LEGACY_CAP if s in LEGACY_OVER_CAP else LINE_CAP)}
    assert not over
    assert sum(_tokens(line) for line in lines.values()) <= TOTAL_CAP
