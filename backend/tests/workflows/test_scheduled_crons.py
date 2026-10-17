"""Each scheduled workflow registers its cron from the schedule registry, the one literal."""

from __future__ import annotations

import ast
from pathlib import Path

from app.services.schedule_registry import list_schedule_definitions

SCHEDULED = Path(__file__).resolve().parents[2] / "app" / "workflows" / "scheduled.py"


def test_scheduled_workflows_read_every_cron_from_the_registry() -> None:
    ids: list[str] = []
    for node in ast.walk(ast.parse(SCHEDULED.read_text())):
        if isinstance(node, ast.keyword) and node.arg == "on_crons":
            assert isinstance(node.value, ast.List)
            for element in node.value.elts:
                assert isinstance(element, ast.Call) and getattr(element.func, "id", "") == "schedule_cron", (
                    f"literal cron in scheduled.py: {ast.unparse(element)}")
                ids.append(ast.literal_eval(element.args[0]))
    assert sorted(ids) == sorted(definition.schedule_id for definition in list_schedule_definitions())
