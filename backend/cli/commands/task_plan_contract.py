"""Shared plan.json contract hints for task CLI help and validation messaging."""

from __future__ import annotations

PLAN_SCHEMA_ENDPOINT = "/schemas/plan"
PLAN_SCHEMA_SOURCE = "backend/app/schemas/plan.schema.json"
PLAN_SCHEMA_ID = "https://summitflow.dev/schemas/plan.json"
PLAN_VERIFY_EXAMPLE = "st verify plan.json"
PLAN_CREATE_EXAMPLE = "st -P <project> create --plan plan.json"
MINIMAL_PLAN_SHAPE = (
    '{"title":"...","objective":"...","task_type":"task","complexity":"SIMPLE",'
    '"subtasks":[{"id":"1.1","description":"..."}]}'
)

PLAN_DISCOVERY_HINT = (
    f"Validate execution-ready plans with `{PLAN_VERIFY_EXAMPLE}`. "
    f"Live schema: `{PLAN_SCHEMA_ENDPOINT}` "
    f"(source: `{PLAN_SCHEMA_SOURCE}`, id: `{PLAN_SCHEMA_ID}`)."
)

CREATE_COMMAND_HELP = f"""Create an execution-ready task from plan or batch import tasks from file.

Use `st capture` for lightweight task intake that still needs shaping.

{PLAN_DISCOVERY_HINT}
"""

VERIFY_COMMAND_HELP = f"""Verify a plan.json file against the live schema and task-domain rules.

The CLI fetches the schema from `{PLAN_SCHEMA_ENDPOINT}`; the checked-in source
of truth lives at `{PLAN_SCHEMA_SOURCE}`.

Minimal shape:
{MINIMAL_PLAN_SHAPE}
"""

PLAN_OPTION_HELP = (
    f"Execution-ready plan.json. Validate first with `{PLAN_VERIFY_EXAMPLE}`; "
    f"live schema is `{PLAN_SCHEMA_ENDPOINT}`."
)

FROM_FILE_OPTION_HELP = "Batch-create tasks from a JSON file containing a `tasks` array."

VERIFY_FILE_ARGUMENT_HELP = (
    f"Path to plan.json. The CLI validates against the live schema at "
    f"`{PLAN_SCHEMA_ENDPOINT}`. Minimal shape: {MINIMAL_PLAN_SHAPE}"
)

CREATE_ERROR_HINT = (
    "st create requires --plan for single-task creation. "
    f"Use `{PLAN_CREATE_EXAMPLE}` for execution-ready work after "
    f"`{PLAN_VERIFY_EXAMPLE}`, or `st -P <project> capture <task|bug|idea> "
    '"..."` for lightweight intake.'
)
