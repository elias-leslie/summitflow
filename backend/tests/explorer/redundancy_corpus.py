"""Labeled corpus for tuning the redundancy detector.

Seeded with realistic symbols (several drawn from the live index) plus crafted
positives and — most importantly — *hard negatives*: pairs that are lexically
close but legitimately distinct. False positives on these create misinformed
refactor tasks, so the corpus is deliberately dense with them.

``GOLD_CLUSTERS`` lists sets of symbol ids that are TRUE near-duplicates of one
another. Any pair of ids not co-listed in a gold cluster is a true non-duplicate.
"""

from __future__ import annotations

from typing import Any


def _sym(
    sid: str,
    name: str,
    file_path: str,
    *,
    kind: str = "function",
    language: str = "python",
    qualified_name: str | None = None,
    signature: str | None = None,
    summary: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": sid,
        "name": name,
        "qualified_name": qualified_name or name,
        "kind": kind,
        "language": language,
        "signature": signature or f"def {name}() -> None",
        "summary": summary,
        "keywords": keywords or [],
        "file_path": file_path,
    }


SYMBOLS: list[dict[str, Any]] = [
    # --- POSITIVE 1: verbatim copy of a util across two modules ---
    _sym(
        "fmt_dur_a",
        "format_duration",
        "backend/app/utils/timefmt.py",
        signature="def format_duration(seconds: float) -> str",
        summary="Format a duration in seconds as a human string.",
        keywords=["format", "duration", "seconds", "human", "string"],
    ),
    _sym(
        "fmt_dur_b",
        "format_duration",
        "backend/app/services/reporting/dates.py",
        signature="def format_duration(secs: float) -> str",
        summary="Format a duration given in seconds into a readable string.",
        keywords=["format", "duration", "seconds", "readable", "string"],
    ),
    # --- POSITIVE 2: version-suffix copy (must NOT be dismissed as specialization) ---
    _sym(
        "parse_cfg_a",
        "parse_config",
        "backend/app/config/loader.py",
        signature="def parse_config(path: str) -> dict",
        summary="Parse a config file into a dict.",
        keywords=["parse", "config", "file", "dict"],
    ),
    _sym(
        "parse_cfg_b",
        "parse_config_v2",
        "backend/app/config/loader_new.py",
        signature="def parse_config_v2(path: str) -> dict",
        summary="Parse a configuration file into a dict.",
        keywords=["parse", "config", "configuration", "file", "dict"],
    ),
    # --- POSITIVE 3: renamed class duplicate ---
    _sym(
        "retry_a",
        "RetryPolicy",
        "backend/app/clients/http.py",
        kind="class",
        signature="class RetryPolicy",
        summary="Backoff retry policy for HTTP calls.",
        keywords=["retry", "policy", "backoff", "http"],
    ),
    _sym(
        "retry_b",
        "RetryPolicy",
        "backend/app/services/queue/runner.py",
        kind="class",
        signature="class RetryPolicy",
        summary="Retry policy with exponential backoff.",
        keywords=["retry", "policy", "backoff", "exponential"],
    ),
    # --- POSITIVE 4: descriptive rename / SYNONYM (lexical will MISS; measures recall gap) ---
    _sym(
        "humanize_a",
        "humanize_seconds",
        "frontend/lib/utils/human.ts",
        language="typescript",
        signature="function humanize_seconds(s: number): string",
        summary="Turn a number of seconds into a friendly duration label.",
        keywords=["seconds", "duration", "friendly", "label"],
    ),
    _sym(
        "humanize_b",
        "prettyDuration",
        "frontend/lib/format/duration.ts",
        language="typescript",
        signature="function prettyDuration(s: number): string",
        summary="Render seconds as a pretty duration label.",
        keywords=["seconds", "duration", "pretty", "label"],
    ),
    # --- POSITIVE 5: copy with minor tweak ---
    _sym(
        "calc_pri_a",
        "compute_refactor_priority",
        "backend/app/services/explorer/analyzers/priority.py",
        signature="def compute_refactor_priority(metrics: dict) -> float",
        summary="Compute a refactor priority score from file metrics.",
        keywords=["compute", "refactor", "priority", "score", "metrics"],
    ),
    _sym(
        "calc_pri_b",
        "compute_refactor_priority",
        "backend/app/services/scoring/priority.py",
        signature="def compute_refactor_priority(m: dict) -> float",
        summary="Compute refactor priority from metrics.",
        keywords=["compute", "refactor", "priority", "metrics"],
    ),
    # --- POSITIVE 6: genuine duplicate WITHIN one layer (storage <-> storage).
    #     Must still be caught: the cross-layer rule only suppresses pairs that
    #     SPAN delegation layers, never same-layer copies. ---
    _sym(
        "gen_mockup_a",
        "generate_mockup_id",
        "backend/app/storage/mockups/core.py",
        signature="def generate_mockup_id(prefix: str) -> str",
        summary="Generate a unique mockup id.",
        keywords=["generate", "mockup", "id", "unique"],
    ),
    _sym(
        "gen_mockup_b",
        "generate_mockup_id",
        "backend/app/storage/mockup_helpers.py",
        signature="def generate_mockup_id(prefix: str) -> str",
        summary="Generate a unique id for a mockup.",
        keywords=["generate", "mockup", "id", "unique"],
    ),

    # --- HARD NEGATIVE: singular vs plural ---
    _sym(
        "get_user",
        "get_user",
        "backend/app/api/users.py",
        signature="def get_user(user_id: str) -> User",
        summary="Fetch a single user by id.",
        keywords=["get", "user", "fetch", "id"],
    ),
    _sym(
        "get_users",
        "get_users",
        "backend/app/api/users_list.py",
        signature="def get_users(limit: int) -> list[User]",
        summary="List multiple users.",
        keywords=["get", "users", "list", "multiple"],
    ),
    # --- HARD NEGATIVE: specialization ---
    _sym(
        "create_task",
        "create_task",
        "backend/app/storage/tasks/core.py",
        signature="def create_task(project_id: str, title: str) -> dict",
        summary="Create a new task and return its dict.",
        keywords=["create", "task", "project", "title"],
    ),
    _sym(
        "create_refactor_task",
        "create_refactor_task",
        "backend/app/tasks/autonomous/task_builders.py",
        signature="def create_refactor_task(project_id: str, path: str) -> tuple",
        summary="Create a refactor task linked to a QA issue.",
        keywords=["create", "refactor", "task", "issue", "qa"],
    ),
    # --- HARD NEGATIVE: shared verb, different object ---
    _sym(
        "format_date",
        "format_date",
        "backend/app/utils/dates.py",
        signature="def format_date(d: date) -> str",
        summary="Format a date as ISO string.",
        keywords=["format", "date", "iso", "string"],
    ),
    _sym(
        "parse_date",
        "parse_date",
        "backend/app/utils/dates.py",
        signature="def parse_date(s: str) -> date",
        summary="Parse an ISO date string.",
        keywords=["parse", "date", "iso", "string"],
    ),
    # --- HARD NEGATIVE: same head, different tail (real index names) ---
    _sym(
        "list_project_roots",
        "list_project_roots",
        "backend/app/api/project_permissions.py",
        signature="def list_project_roots() -> dict",
        summary="List canonical project roots keyed by project id.",
        keywords=["list", "project", "roots", "canonical"],
    ),
    _sym(
        "list_project_paths",
        "list_project_paths",
        "backend/app/api/project_paths.py",
        signature="def list_project_paths() -> list[str]",
        summary="List filesystem paths for a project.",
        keywords=["list", "project", "paths", "filesystem"],
    ),
    # --- HARD NEGATIVE: same common method name on unrelated classes ---
    _sym(
        "to_dict_a",
        "to_dict",
        "backend/app/models/task.py",
        kind="method",
        qualified_name="Task.to_dict",
        signature="def to_dict(self) -> dict",
        summary="Serialize the task to a dict.",
        keywords=["serialize", "task", "dict"],
    ),
    _sym(
        "to_dict_b",
        "to_dict",
        "backend/app/models/project.py",
        kind="method",
        qualified_name="Project.to_dict",
        signature="def to_dict(self) -> dict",
        summary="Serialize the project to a dict.",
        keywords=["serialize", "project", "dict"],
    ),
    # --- HARD NEGATIVE: cross-layer delegation (the #1 real-world false-positive
    #     class from the live dry run). An API handler and the storage function it
    #     calls share a name by design; consolidating them would be wrong. ---
    _sym(
        "create_rule_api",
        "create_rule",
        "backend/app/api/design_standards_routes.py",
        signature="def create_rule(body: RuleIn) -> RuleOut",
        summary="Create a design rule via the API.",
        keywords=["create", "rule", "design", "api"],
    ),
    _sym(
        "create_rule_storage",
        "create_rule",
        "backend/app/storage/design_rules.py",
        signature="def create_rule(project_id: str, body: dict) -> dict",
        summary="Insert a design rule row and return it.",
        keywords=["create", "rule", "design", "insert", "row"],
    ),
    # --- HARD NEGATIVE: three-layer delegation (api -> services -> storage). No
    #     pair among these should survive. ---
    _sym(
        "get_stats_api",
        "get_stats",
        "backend/app/api/explorer.py",
        signature="def get_stats(project_id: str) -> dict",
        summary="Return explorer stats via the API.",
        keywords=["get", "stats", "explorer", "api"],
    ),
    _sym(
        "get_stats_service",
        "get_stats",
        "backend/app/services/explorer/__init__.py",
        signature="def get_stats(project_id: str) -> dict",
        summary="Gather explorer stats.",
        keywords=["get", "stats", "explorer"],
    ),
    _sym(
        "get_stats_storage",
        "get_stats",
        "backend/app/storage/explorer_entries.py",
        signature="def get_stats(project_id: str) -> dict",
        summary="Query explorer entry stats.",
        keywords=["get", "stats", "explorer", "query"],
    ),
    # --- HARD NEGATIVE: React component-local handlers (handleX/onX). Recur
    #     across unrelated components by convention; never shared surface. ---
    _sym(
        "handle_kd_a",
        "handleKeyDown",
        "frontend/components/kanban/ExecutionPanel.tsx",
        language="typescript",
        keywords=["handle", "key", "down"],
    ),
    _sym(
        "handle_kd_b",
        "handleKeyDown",
        "frontend/components/tasks/DiscussionChat.tsx",
        language="typescript",
        keywords=["handle", "key", "down"],
    ),
    # --- HARD NEGATIVE: argparse boilerplate repeated across scripts ---
    _sym(
        "parse_args_a",
        "parse_args",
        "scripts/agent-observability-sync.py",
        summary="Parse command-line arguments.",
        keywords=["parse", "args", "argparse"],
    ),
    _sym(
        "parse_args_b",
        "parse_args",
        "scripts/codex-session-sync.py",
        summary="Parse command-line arguments.",
        keywords=["parse", "args", "argparse"],
    ),
    # --- POSITIVE 7: a genuinely copy-pasted React COMPONENT (PascalCase). Must
    #     stay in scope — only handlers are excluded, not components. ---
    _sym(
        "collapsible_a",
        "CollapsibleSection",
        "frontend/components/tasks/CollapsibleSection.tsx",
        kind="function",
        language="typescript",
        signature="function CollapsibleSection(props: Props): JSX.Element",
        summary="Collapsible section wrapper component.",
        keywords=["collapsible", "section", "component", "wrapper"],
    ),
    _sym(
        "collapsible_b",
        "CollapsibleSection",
        "frontend/components/backup/CollapsibleSection.tsx",
        kind="function",
        language="typescript",
        signature="function CollapsibleSection(props: Props): JSX.Element",
        summary="A collapsible section wrapper component.",
        keywords=["collapsible", "section", "component", "wrapper"],
    ),
    # --- HARD NEGATIVE: API-client mirror. The cli HTTP client mirrors the
    #     endpoint name by design; not a consolidation target. ---
    _sym(
        "get_session_api",
        "get_session",
        "backend/app/api/agent_sessions.py",
        signature="def get_session(session_id: str) -> dict",
        summary="Return an agent session via the API.",
        keywords=["get", "session", "agent", "api"],
    ),
    _sym(
        "get_session_client",
        "get_session",
        "backend/cli/_client_execution.py",
        signature="def get_session(session_id: str) -> dict",
        summary="Fetch an agent session from the API.",
        keywords=["get", "session", "agent", "client"],
    ),
    # --- HARD NEGATIVE: published client-SDK model mirror. The client package
    #     re-declares server wire-types by design; consolidating would couple the
    #     SDK to the backend. ---
    _sym(
        "usageinfo_server",
        "UsageInfo",
        "backend/app/api/complete/usage_schemas.py",
        kind="class",
        signature="class UsageInfo",
        summary="Token usage info.",
        keywords=["usage", "info", "tokens"],
    ),
    _sym(
        "usageinfo_client",
        "UsageInfo",
        "packages/agent-hub-client/agent_hub/models/usage.py",
        kind="class",
        signature="class UsageInfo",
        summary="Token usage info.",
        keywords=["usage", "info", "tokens"],
    ),
    # --- HARD NEGATIVE: universal React local prop-type name ---
    _sym(
        "props_a",
        "Props",
        "frontend/components/money/DeleteAccountDialog.tsx",
        kind="type",
        language="typescript",
        keywords=["props"],
    ),
    _sym(
        "props_b",
        "Props",
        "frontend/components/money/AccountAccordionItem.tsx",
        kind="type",
        language="typescript",
        keywords=["props"],
    ),
    # --- HARD NEGATIVE: Next.js route-handler verb exports ---
    _sym(
        "get_route_a",
        "GET",
        "frontend/app/api/[...path]/route.ts",
        kind="function",
        language="typescript",
        keywords=["get", "route"],
    ),
    _sym(
        "get_route_b",
        "GET",
        "frontend/app/health/[...path]/route.ts",
        kind="function",
        language="typescript",
        keywords=["get", "route"],
    ),
    # --- HARD NEGATIVE: same name, different kind ---
    _sym(
        "status_fn",
        "status",
        "backend/app/api/health.py",
        kind="function",
        signature="def status() -> dict",
        summary="Return service status.",
        keywords=["status", "service", "health"],
    ),
    _sym(
        "status_const",
        "status",
        "backend/app/constants.py",
        kind="constant",
        signature="status = 'ok'",
        summary=None,
        keywords=["status"],
    ),

    # --- ELIGIBILITY TRAPS: must be filtered out before scoring ---
    # vendored duplicate
    _sym(
        "vendor_init_a",
        "__init__",
        ".dev-tools/cleanroom-pydeps/numpy/__init__.py",
        kind="method",
        keywords=["init"],
    ),
    _sym(
        "vendor_init_b",
        "__init__",
        ".dev-tools/cleanroom-pydeps/pydantic/__init__.py",
        kind="method",
        keywords=["init"],
    ),
    # alembic migrations at the REPO ROOT (no backend/ prefix). Every migration
    # has upgrade/downgrade; they are append-only and never consolidation targets.
    _sym(
        "mig_up_a",
        "upgrade",
        "alembic/versions/5cdb3c9dc987_add_notes.py",
        signature="def upgrade() -> None",
        keywords=["upgrade", "alembic"],
    ),
    _sym(
        "mig_up_b",
        "upgrade",
        "alembic/versions/6cf65b9ca525_add_panes.py",
        signature="def upgrade() -> None",
        keywords=["upgrade", "alembic"],
    ),
    # test-file duplicate names
    _sym(
        "test_dup_a",
        "test_creates_subtask",
        "backend/tests/tasks/test_review_routing.py",
        kind="method",
        keywords=["test", "creates", "subtask"],
    ),
    _sym(
        "test_dup_b",
        "test_creates_subtask",
        "backend/tests/tasks/test_other.py",
        kind="method",
        keywords=["test", "creates", "subtask"],
    ),
    # private helper duplicate (not public surface)
    _sym(
        "priv_a",
        "_normalize",
        "backend/app/utils/a.py",
        signature="def _normalize(x): ...",
        keywords=["normalize"],
    ),
    _sym(
        "priv_b",
        "_normalize",
        "backend/app/utils/b.py",
        signature="def _normalize(x): ...",
        keywords=["normalize"],
    ),

    # --- EASY NEGATIVES: unrelated real-ish symbols ---
    _sym(
        "approve_run",
        "approve_run",
        "backend/app/api/committee_runs.py",
        summary="Execute the paper trade for an approved decision.",
        keywords=["approve", "run", "decision", "trade"],
    ),
    _sym(
        "archive_age_days",
        "archive_age_days",
        "backend/app/tasks/backup_native_restore.py",
        summary="Return whole days since archive mtime.",
        keywords=["archive", "age", "days", "mtime"],
    ),
    _sym(
        "fetch_task_data",
        "_fetch_task_data",
        "backend/cli/commands/exec_monitor.py",
        summary="Fetch task, subtasks, and events from the API.",
        keywords=["fetch", "task", "subtasks", "events"],
    ),
    _sym(
        "thesis_resp",
        "ThesisResponse",
        "frontend/lib/api/thesis.ts",
        kind="type",
        language="typescript",
        keywords=["thesis", "response"],
    ),
    _sym(
        "step_type",
        "Step",
        "frontend/lib/api/tasks-types-enrichment.ts",
        kind="type",
        language="typescript",
        keywords=["step"],
    ),
    _sym(
        "git_revision",
        "git_revision",
        "backend/app/utils/gitinfo.py",
        summary="Get the SHA-1 of the HEAD of a git repository.",
        keywords=["git", "revision", "sha", "head", "repository"],
    ),
    _sym(
        "approve_decision",
        "approve_decision",
        "backend/app/api/decisions.py",
        summary="Approve a pending committee decision.",
        keywords=["approve", "decision", "committee", "pending"],
    ),

    # --- NEW POSITIVE: copy marked by a *different* version/copy suffix (_new,
    #     not v2). Proves suffix normalization generalizes past the v2 case. ---
    _sym(
        "ser_payload_a",
        "serialize_payload",
        "backend/app/transport/codec.py",
        signature="def serialize_payload(payload: dict) -> bytes",
        summary="Serialize a request payload to bytes.",
        keywords=["serialize", "payload", "bytes", "request"],
    ),
    _sym(
        "ser_payload_b",
        "serialize_payload_new",
        "backend/app/transport/codec_new.py",
        signature="def serialize_payload_new(payload: dict) -> bytes",
        summary="Serialize a request payload into bytes.",
        keywords=["serialize", "payload", "bytes", "request"],
    ),
    # --- NEW HARD NEGATIVE: a real specialization that LOOKS suffix-like but the
    #     extra token (`validator`) carries design intent. Must stay rejected,
    #     proving we strip only version noise, not every trailing token. ---
    _sym(
        "import_csv",
        "import_csv",
        "backend/app/io/csv_import.py",
        signature="def import_csv(path: str) -> list[dict]",
        summary="Read rows from a CSV file into dicts.",
        keywords=["import", "csv", "rows", "file"],
    ),
    _sym(
        "import_csv_validator",
        "import_csv_validator",
        "backend/app/io/csv_validate.py",
        signature="def import_csv_validator(path: str) -> list[str]",
        summary="Validate a CSV file and report row errors.",
        keywords=["import", "csv", "validator", "errors", "rows"],
    ),
    # --- NEW POSITIVE: genuinely duplicated method on two different classes. The
    #     polymorphism guard must NOT suppress this: it shares strong *domain*
    #     corroboration (discount/percentage) beyond the generic name. ---
    _sym(
        "apply_discount_a",
        "apply_discount",
        "backend/app/billing/cart.py",
        kind="method",
        qualified_name="Cart.apply_discount",
        signature="def apply_discount(self, percent: float) -> float",
        summary="Apply a percentage discount to the cart total.",
        keywords=["apply", "discount", "percent", "total"],
    ),
    _sym(
        "apply_discount_b",
        "apply_discount",
        "backend/app/billing/order.py",
        kind="method",
        qualified_name="Order.apply_discount",
        signature="def apply_discount(self, percent: float) -> float",
        summary="Apply a percentage discount to the order total.",
        keywords=["apply", "discount", "percent", "total"],
    ),
    # --- NEW HARD NEGATIVE: another generic conversion method name on unrelated
    #     classes. Like to_dict, this is polymorphism and must stay unflagged. ---
    _sym(
        "from_json_a",
        "from_json",
        "backend/app/models/invoice.py",
        kind="method",
        qualified_name="Invoice.from_json",
        signature="def from_json(cls, data: dict) -> Invoice",
        summary="Build an invoice from a json dict.",
        keywords=["from", "json", "invoice", "dict"],
    ),
    _sym(
        "from_json_b",
        "from_json",
        "backend/app/models/customer.py",
        kind="method",
        qualified_name="Customer.from_json",
        signature="def from_json(cls, data: dict) -> Customer",
        summary="Build a customer from a json dict.",
        keywords=["from", "json", "customer", "dict"],
    ),

    # --- LIVE FP CLASS 1: same-name wire-model classes, matching OUTER shape but
    #     different fields / inner element types, in different API domains. The
    #     index stores class signatures declaration-only (``class X(BaseModel)``),
    #     so fields are invisible — name + framework boilerplate is all that's
    #     shared. Must be rejected on weak domain corroboration. (agent-hub
    #     ``ClientListResponse`` scored the detector's MAX 1.000 before this.) ---
    _sym(
        "client_list_resp_a",
        "ClientListResponse",
        "backend/app/api/clients/schemas.py",
        kind="class",
        signature="class ClientListResponse(BaseModel)",
        summary="List of clients.",
        keywords=["client", "list", "response"],
    ),
    _sym(
        "client_list_resp_b",
        "ClientListResponse",
        "backend/app/api/control/schemas.py",
        kind="class",
        signature="class ClientListResponse(BaseModel)",
        summary="List of client controls.",
        keywords=["client", "list", "response"],
    ),
    # Same FP class: ``HealthResponse`` — disjoint field sets, only the name and
    # framework base are shared in the index.
    _sym(
        "health_resp_a",
        "HealthResponse",
        "backend/app/api/health.py",
        kind="class",
        signature="class HealthResponse(BaseModel)",
        summary="Service health check response.",
        keywords=["health", "response"],
    ),
    _sym(
        "health_resp_b",
        "HealthResponse",
        "backend/app/api/memory/schemas.py",
        kind="class",
        signature="class HealthResponse(BaseModel)",
        summary="Memory subsystem health response.",
        keywords=["health", "response"],
    ),
    # Same FP class: ``VariantMetrics`` — a stdlib ``dataclass`` deliberately kept
    # separate from the app's Pydantic model (the script copy avoids importing the
    # app's Pydantic chain). Disjoint fields; only name shared.
    _sym(
        "variant_metrics_a",
        "VariantMetrics",
        "scripts/experiments/variant_report.py",
        kind="class",
        signature="class VariantMetrics",
        summary="Metrics for one experiment variant.",
        keywords=["variant", "metrics"],
    ),
    _sym(
        "variant_metrics_b",
        "VariantMetrics",
        "backend/app/api/experiments/schemas.py",
        kind="class",
        signature="class VariantMetrics(BaseModel)",
        summary="Variant metrics wire model.",
        keywords=["variant", "metrics"],
    ),

    # --- LIVE FP CLASS 2: facade/impl pairs with DIFFERENT parameter arity. A
    #     high-level facade resolves args then delegates to a same-named low-level
    #     impl; the arg lists differ. These sit in the SAME package/tree, so the
    #     cross-layer rule does not catch them — the arity gate must. ---
    _sym(
        "get_eff_rules_facade",
        "get_effective_rules",
        "backend/app/storage/design_standards.py",
        signature="def get_effective_rules(project_id: str, category: str) -> list[dict]",
        summary="Resolve effective rules for a project and category.",
        keywords=["effective", "rules", "project", "category"],
    ),
    _sym(
        "get_eff_rules_impl",
        "get_effective_rules",
        "backend/app/storage/design_rules.py",
        signature=(
            "def get_effective_rules(base_standard_id: str, "
            "project_standard_id: str, category: str) -> list[dict]"
        ),
        summary="Merge base and project standard rules for a category.",
        keywords=["effective", "rules", "standard", "category"],
    ),
    _sym(
        "validate_rules_facade",
        "validate_against_rules",
        "backend/app/storage/design_standards.py",
        signature=(
            "def validate_against_rules(project_id: str, "
            "element_data: dict, category: str) -> list[dict]"
        ),
        summary="Validate an element against a project's effective rules.",
        keywords=["validate", "rules", "project", "element"],
    ),
    _sym(
        "validate_rules_impl",
        "validate_against_rules",
        "backend/app/storage/design_validation.py",
        signature="def validate_against_rules(rules: list[dict], element_data: dict) -> list[dict]",
        summary="Validate element data against a list of rules.",
        keywords=["validate", "rules", "element", "data"],
    ),
    _sym(
        "run_scan_facade",
        "run_scan_with_tracking",
        "backend/app/services/explorer/__init__.py",
        signature="def run_scan_with_tracking(project_id: str, paths: list[str]) -> dict",
        summary="Run an explorer scan with progress tracking.",
        keywords=["run", "scan", "tracking", "project"],
    ),
    _sym(
        "run_scan_impl",
        "run_scan_with_tracking",
        "backend/app/services/explorer/_scan_tracking.py",
        signature=(
            "def run_scan_with_tracking(project_id: str, paths: list[str], "
            "scan_fn: Callable) -> dict"
        ),
        summary="Run a scan with tracking using an injectable scan function.",
        keywords=["run", "scan", "tracking", "inject"],
    ),

    # --- NEW POSITIVE: a genuinely copy-pasted schema CLASS that shares concrete
    #     DOMAIN corroboration beyond name + framework boilerplate (``hmac``,
    #     ``signature``). The class domain-corroboration gate must NOT suppress
    #     this — proving the gate rejects only framework-shaped name collisions,
    #     not real class copies. ---
    _sym(
        "webhook_payload_a",
        "WebhookPayload",
        "backend/app/api/billing/webhooks.py",
        kind="class",
        signature="class WebhookPayload(BaseModel)",
        summary="Incoming webhook payload verified by an hmac signature.",
        keywords=["webhook", "payload", "hmac", "signature", "verify"],
    ),
    _sym(
        "webhook_payload_b",
        "WebhookPayload",
        "backend/app/api/notifications/webhooks.py",
        kind="class",
        signature="class WebhookPayload(BaseModel)",
        summary="Webhook payload with an hmac signature for verification.",
        keywords=["webhook", "payload", "hmac", "signature", "verify"],
    ),
    # --- LIVE FP CLASS 3: same-package hub/spoke facade. A hub module
    #     (``subtasks.py``) aggregates and delegates to same-directory split-outs
    #     (``subtasks_crud.py``); the same-named symbol in the hub is a thin facade
    #     over the spoke's impl, with the SAME parameter arity — so the arity gate
    #     misses it. The sibling-module gate must reject it. ---
    _sym(
        "get_subtask_hub",
        "get_subtask",
        "backend/app/storage/subtasks.py",
        signature="def get_subtask(task_id: str, subtask_id: str) -> dict | None",
        summary="Return a subtask by task and subtask id.",
        keywords=["get", "subtask", "task", "id"],
    ),
    _sym(
        "get_subtask_spoke",
        "get_subtask",
        "backend/app/storage/subtasks_crud.py",
        signature="def get_subtask(task_id: str, subtask_id: str) -> dict | None",
        summary="Fetch a subtask row by task and subtask id.",
        keywords=["get", "subtask", "task", "id"],
    ),
    # Hub/spoke with no params (db_workbench pattern) — still rejected by the
    # sibling gate, not the arity gate.
    _sym(
        "project_db_url_hub",
        "project_db_url",
        "backend/app/services/db_workbench.py",
        signature="def project_db_url() -> str",
        summary="Return the project database url.",
        keywords=["project", "db", "url", "database"],
    ),
    _sym(
        "project_db_url_spoke",
        "project_db_url",
        "backend/app/services/db_workbench_targets.py",
        signature="def project_db_url() -> str",
        summary="Resolve the project database url from targets.",
        keywords=["project", "db", "url", "database"],
    ),

    # --- NEW POSITIVE: a CONSTANT re-declared across sibling modules. Unlike a
    #     callable facade, a constant cannot delegate — the sibling that
    #     re-declares it should import the shared value, so this IS a genuine
    #     duplicate and must stay flagged (the sibling-module gate is callable-only). ---
    _sym(
        "default_ttl_a",
        "DEFAULT_INDEX_TTL_SECONDS",
        "backend/app/services/memory/adaptive_index.py",
        kind="constant",
        signature="DEFAULT_INDEX_TTL_SECONDS = 300",
        summary=None,
        keywords=["default", "index", "ttl", "seconds"],
    ),
    _sym(
        "default_ttl_b",
        "DEFAULT_INDEX_TTL_SECONDS",
        "backend/app/services/memory/adaptive_index_models.py",
        kind="constant",
        signature="DEFAULT_INDEX_TTL_SECONDS = 300",
        summary=None,
        keywords=["default", "index", "ttl", "seconds"],
    ),

    # --- NEW POSITIVE: a genuine function copy whose params were RENAMED but arity
    #     PRESERVED. The arity gate must not fire here (same arity), so it stays a
    #     true positive — guards against the gate over-rejecting real copies. ---
    _sym(
        "slugify_a",
        "slugify_title",
        "backend/app/utils/text.py",
        signature="def slugify_title(title: str) -> str",
        summary="Turn a title into a url-safe slug.",
        keywords=["slugify", "title", "slug", "url"],
    ),
    _sym(
        "slugify_b",
        "slugify_title",
        "backend/app/services/publishing/slugs.py",
        signature="def slugify_title(heading: str) -> str",
        summary="Convert a heading into a url-safe slug.",
        keywords=["slugify", "title", "slug", "url"],
    ),
]


# Sets of symbol ids that are TRUE near-duplicates of one another AND in scope
# for v1 (top-level public surface). Method/class-member duplicates are out of
# scope (see ``apply_discount`` below), so they are intentionally NOT listed here.
GOLD_CLUSTERS: list[set[str]] = [
    {"fmt_dur_a", "fmt_dur_b"},
    {"parse_cfg_a", "parse_cfg_b"},
    {"retry_a", "retry_b"},
    {"humanize_a", "humanize_b"},  # synonym pair: lexical detector expected to MISS
    {"calc_pri_a", "calc_pri_b"},
    {"ser_payload_a", "ser_payload_b"},  # copy via _new suffix
    {"gen_mockup_a", "gen_mockup_b"},  # genuine same-layer (storage<->storage) dup
    {"collapsible_a", "collapsible_b"},  # genuine copy-pasted React component
    {"webhook_payload_a", "webhook_payload_b"},  # real schema-class copy w/ domain corroboration
    {"slugify_a", "slugify_b"},  # real function copy, params renamed but arity preserved
    {"default_ttl_a", "default_ttl_b"},  # constant re-declared in sibling module (genuine dup)
]

# Out of scope for v1: a genuine method duplicate. The detector deliberately does
# NOT flag class members (interface/override polymorphism dominates that class on
# real data), so this pair is tracked here for documentation, not in GOLD.
OUT_OF_SCOPE_METHOD_CLUSTERS: list[set[str]] = [
    {"apply_discount_a", "apply_discount_b"},
]

# Subset of gold pairs that are pure synonyms (no shared name tokens). Recall on
# these is NOT expected from a lexical detector; tracked separately so the bar is
# honest and the embeddings escape-hatch decision is data-driven.
SYNONYM_GOLD_CLUSTERS: list[set[str]] = [
    {"humanize_a", "humanize_b"},
]
