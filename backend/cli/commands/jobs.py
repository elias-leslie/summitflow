"""``st jobs`` — agent-facing CLI surface for Jobinator-4000.

Each subcommand is a thin client over Jobinator's HTTP routers; no scoring,
tailoring or tracking logic lives here. The backend owns the contract, and the
CLI passes it through unchanged in JSON mode, rendering a terminal summary only
under ``--human``.

Nothing on this surface contacts an employer. ``apply`` and ``status`` record
what the candidate did; submission stays manual by design.

Exit codes, matching ``st portfolio``:

* ``0`` success
* ``1`` HTTP / business error (the server returned a response)
* ``2`` connection failure (the Jobinator backend is unreachable)
* ``3`` invalid input flags
"""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Annotated, Any

import typer

from .._client_base import APIError
from .._jobs_client import (
    AGENT_TIMEOUT,
    JobsClient,
    JobsConnectError,
    ResolvedURL,
    resolve_jobs_api_url,
)
from ..lib.usage import usage
from ..output import output_error, output_json

SCHEMA_VERSION = 1

EP_TODAY = "/api/today"
EP_POSTINGS = "/api/postings"
EP_POSTING_STATES = "/api/postings/stats/states"
EP_EVALUATIONS = "/api/evaluations"
EP_SCAN_SYNC = "/api/sources/scan/sync"
EP_SCAN_ASYNC = "/api/sources/scan"
EP_APPLICATIONS = "/api/applications"
EP_FUNNEL = "/api/applications/stats/funnel"
EP_ARTIFACT_GENERATE = "/api/artifacts/generate"
EP_FOLLOWUPS = "/api/followups"
EP_PROFILE = "/api/profile"

#: Recorded on every write this surface makes, so the application timeline
#: distinguishes an agent working through `st` from a person clicking in the UI.
SOURCE = "st"

STATUSES = (
    "evaluated",
    "applied",
    "responded",
    "interview",
    "offer",
    "rejected",
    "discarded",
    "skip",
    "hired",
)
KINDS = ("resume", "cover_letter", "both")

app = typer.Typer(help="Find, evaluate, tailor for, and track job applications")


# ─── helpers ────────────────────────────────────────────────────────────────────

def _client(remote: bool, *, timeout: float = 30.0) -> tuple[JobsClient, ResolvedURL]:
    resolved = resolve_jobs_api_url(remote=remote)
    return JobsClient(resolved.url, timeout=timeout), resolved


def _handle_connect(exc: JobsConnectError) -> None:
    """Emit the unreachable envelope and exit ``2``."""
    payload = {
        "ok": False,
        "error": "jobs_api_unreachable",
        "url": exc.url,
        "detail": exc.detail,
        "hint": "Set ST_JOBS_API_URL or start the jobinator-4000 backend",
    }
    print(json.dumps(payload), file=sys.stderr)
    raise typer.Exit(2)


def _handle_api_error(exc: APIError) -> None:
    """Emit the HTTP-error envelope and exit ``1``."""
    detail = exc.detail
    if isinstance(detail, dict):
        error_code = detail.get("error") or "http_error"
        message = detail.get("detail") or detail.get("message") or json.dumps(detail)
        payload: dict[str, Any] = {
            "ok": False,
            "status": exc.status_code,
            "error": error_code,
            "detail": message,
        }
        # A blocked fact check is the one error an agent must be able to act on:
        # it names the claims the model invented, and half of a requested pair
        # may still have been written. Passing it through as an opaque string
        # would make the surface useless for the case it exists to catch.
        for key in ("invented", "forbidden", "produced"):
            if key in detail:
                payload[key] = detail[key]
    else:
        payload = {
            "ok": False,
            "status": exc.status_code,
            "error": "http_error",
            "detail": str(detail),
        }
    print(json.dumps(payload), file=sys.stderr)
    raise typer.Exit(1)


def _request(
    remote: bool,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    try:
        with _client(remote, timeout=timeout)[0] as client:
            if method == "POST":
                return client.post(path, params=params, json_body=json_body)
            if method == "PATCH":
                return client.patch(path, json_body=json_body)
            return client.get(path, params=params)
    except JobsConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)


def _get(remote: bool, path: str, *, params: dict[str, Any] | None = None) -> Any:
    return _request(remote, "GET", path, params=params)


def _post(
    remote: bool,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    return _request(remote, "POST", path, params=params, json_body=json_body, timeout=timeout)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _envelope(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "schema_version": SCHEMA_VERSION, "data": data, "meta": meta or {}}


def _emit(data: Any, meta: dict[str, Any] | None, *, human: bool, summary: str | None) -> None:
    if human and summary is not None:
        typer.echo(summary)
        return
    output_json(_envelope(data, meta))


def _require(value: str, *, flag: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        output_error(f"{flag} must be one of {', '.join(allowed)}; got {value!r}")
        raise typer.Exit(3)


def _score(value: Any) -> str:
    return "  - " if value is None else f"{float(value):>4.1f}"


def _where(row: dict[str, Any]) -> str:
    company = row.get("company") or row.get("company_name") or "?"
    title = row.get("title") or "(untitled)"
    return f"{title} — {company}"


# ─── discovery ──────────────────────────────────────────────────────────────────

@app.command()
@usage(
    surface="st.jobs.ready",
    cmd="st jobs ready --limit 10",
    when="pick the next job worth acting on; start of any job-search working session",
    why="scored, still-open postings with no application yet — the actual queue, not the whole board",
    precautions=("read-only; postings already applied to are excluded, not ranked low",),
    examples=("st jobs ready --limit 5 --min-score 4.0",),
    task_types=("jobs", "career"),
    tier="mandate",
)
def ready(
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    min_score: Annotated[float, typer.Option("--min-score", min=0, max=5)] = 3.5,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Top-scoring open postings with no application on them yet."""
    data = _as_dict(_get(remote, EP_TODAY, params={"limit": limit, "min_score": min_score}))
    leads = _as_list(data.get("leads"))
    scan = _as_dict(data.get("scan"))
    meta = {
        "unevaluated_new": data.get("unevaluated_new"),
        "last_scan": scan.get("started_at"),
        "min_score": data.get("min_score"),
    }
    lines = [f"{_score(row.get('score'))}  #{row.get('id')}  {_where(row)}" for row in leads]
    if not lines:
        lines = [f"No leads at or above {min_score}."]
    unevaluated = data.get("unevaluated_new") or 0
    if unevaluated:
        lines.append(f"({unevaluated} new postings not yet evaluated — st jobs evaluate <id>)")
    _emit(leads, meta, human=human, summary="\n".join(lines))


@app.command()
@usage(
    surface="st.jobs.show",
    cmd="st jobs show <posting-id>",
    when="read one posting in full before evaluating, tailoring, or deciding to skip it",
    why="returns the job description together with its evaluation, skill gap and legitimacy flags",
    precautions=("read-only; description can be long — use --no-description when only the verdict matters",),
    task_types=("jobs", "career"),
    tier="mandate",
)
def show(
    posting_id: Annotated[int, typer.Argument(help="Posting id from st jobs ready")],
    description: Annotated[bool, typer.Option("--description/--no-description")] = True,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Posting detail: description, evaluation report, skill gap, legitimacy."""
    data = _as_dict(_get(remote, f"{EP_POSTINGS}/{posting_id}"))
    if not description:
        data.pop("description", None)
    evaluation = _as_dict(data.get("evaluation"))
    gap = _as_dict(data.get("skill_gap"))
    lines = [
        f"#{data.get('id')}  {_where(data)}",
        f"  {data.get('location') or 'location unknown'} · {data.get('remote')} · "
        f"{data.get('seniority')} · state={data.get('state')}",
        f"  score {_score(evaluation.get('score')).strip()}",
    ]
    if data.get("url"):
        lines.append(f"  {data['url']}")
    if gap.get("gaps"):
        lines.append("  gaps: " + ", ".join(str(g) for g in gap["gaps"][:8]))
    if evaluation.get("red_flags"):
        lines.append("  red flags: " + "; ".join(str(f) for f in evaluation["red_flags"]))
    if evaluation.get("report_md"):
        lines.extend(["", str(evaluation["report_md"])])
    _emit(data, None, human=human, summary="\n".join(lines))


@app.command()
@usage(
    surface="st.jobs.scan",
    cmd="st jobs scan --source greenhouse",
    when="pull new postings from the tracked boards before triaging",
    why="one run fetches, filters, de-duplicates and persists; counters say what was dropped and why",
    precautions=(
        "a full sweep takes minutes — narrow with --source or --company, or use --background",
        "network-bound; writes new postings but never modifies existing applications",
    ),
    examples=("st jobs scan --company Anthropic", "st jobs scan --background"),
    task_types=("jobs", "career"),
    tier="mandate",
)
def scan(
    source: Annotated[str | None, typer.Option("--source", help="Limit to one source slug")] = None,
    company: Annotated[str | None, typer.Option("--company", help="Limit to one company")] = None,
    background: Annotated[
        bool, typer.Option("--background", help="Return immediately; read results from the UI")
    ] = False,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Run a scan across the enabled sources and report its counters."""
    params: dict[str, Any] = {}
    if source:
        params["source"] = source
    if company:
        params["company"] = company
    if background:
        data = _as_dict(_post(remote, EP_SCAN_ASYNC, params=params))
        _emit(data, None, human=human, summary="Scan started.")
        return
    data = _as_dict(_post(remote, EP_SCAN_SYNC, params=params, timeout=AGENT_TIMEOUT))
    summary = (
        f"run {data.get('run_id')}: {data.get('found')} found, {data.get('added')} added "
        f"across {data.get('boards')} boards / {data.get('companies')} companies"
    )
    if data.get("errors"):
        summary += f"\nerrors: {json.dumps(data['errors'])}"
    _emit(data, None, human=human, summary=summary)


@app.command()
@usage(
    surface="st.jobs.evaluate",
    cmd="st jobs evaluate <posting-id>",
    when="score a posting for fit before spending a tailoring run on it",
    why="persists the full report, subscores, legitimacy signal and skill gap against the posting",
    precautions=(
        "spends an Agent Hub call and takes tens of seconds; free-tier quota resets midnight Pacific",
        "re-running records another evaluation rather than replacing the last one",
    ),
    task_types=("jobs", "career"),
    tier="mandate",
)
def evaluate(
    posting_id: Annotated[int, typer.Argument(help="Posting id")],
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Run the evaluator agent over one posting and persist the report."""
    data = _as_dict(_post(remote, f"{EP_EVALUATIONS}/{posting_id}", timeout=AGENT_TIMEOUT))
    lines = [f"posting {posting_id}: score {_score(data.get('score')).strip()}"]
    if data.get("red_flags"):
        lines.append("red flags: " + "; ".join(str(f) for f in data["red_flags"]))
    if data.get("report_md"):
        lines.extend(["", str(data["report_md"])])
    _emit(data, None, human=human, summary="\n".join(lines))


# ─── documents ──────────────────────────────────────────────────────────────────

@app.command()
@usage(
    surface="st.jobs.tailor",
    cmd="st jobs tailor <posting-id>",
    when="produce the resume and cover letter for a posting you intend to submit",
    why="writes both documents against this job description and stores them as versioned artifacts on the application",
    precautions=(
        "spends Agent Hub calls and takes up to a minute per document",
        "a blocked fact check exits 1 with the invented claims listed — fix the CV facts or regenerate, never hand-edit past it",
        "generating opens an application record if the posting has none",
    ),
    examples=("st jobs tailor 41 --kind cover_letter",),
    task_types=("jobs", "career"),
    tier="mandate",
)
def tailor(
    posting_id: Annotated[int, typer.Argument(help="Posting id")],
    kind: Annotated[str, typer.Option("--kind", help="resume | cover_letter | both")] = "both",
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Generate a tailored resume and/or cover letter for one posting."""
    _require(kind, flag="--kind", allowed=KINDS)
    kinds = ["resume", "cover_letter"] if kind == "both" else [kind]
    data = _as_dict(
        _post(
            remote,
            EP_ARTIFACT_GENERATE,
            json_body={"posting_id": posting_id, "kinds": kinds, "source": SOURCE},
            timeout=AGENT_TIMEOUT,
        )
    )
    lines = [f"application {data.get('application_id')}"]
    for document in _as_list(data.get("documents")):
        ids = f"html={document.get('html_artifact_id')} pdf={document.get('pdf_artifact_id')}"
        lines.append(f"  {document.get('kind')}: {ids}")
        if document.get("pdf_error"):
            lines.append(f"    pdf failed: {document['pdf_error']}")
        for warning in document.get("warnings") or []:
            lines.append(f"    warning: {warning}")
    _emit(data, None, human=human, summary="\n".join(lines))


# ─── tracking ───────────────────────────────────────────────────────────────────

@app.command()
@usage(
    surface="st.jobs.apply",
    cmd="st jobs apply <posting-id>",
    when="you have submitted an application and it needs to be on the record",
    why="opens the application, dates it, and moves the posting out of the discovery queue",
    precautions=(
        "records state only — nothing is submitted to an employer from here",
        "idempotent per posting: a second call re-uses the existing application",
        "use --no-submit to open an application you have not sent yet",
    ),
    examples=("st jobs apply 41 -m 'referred by a former colleague'",),
    task_types=("jobs", "career"),
    tier="mandate",
)
def apply(
    posting_id: Annotated[int, typer.Argument(help="Posting id")],
    note: Annotated[str | None, typer.Option("--note", "-m", help="Note on the transition")] = None,
    on: Annotated[
        str | None, typer.Option("--on", help="Submission date (YYYY-MM-DD); defaults to today")
    ] = None,
    submit: Annotated[
        bool, typer.Option("--submit/--no-submit", help="Mark it submitted")
    ] = True,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Record an application against a posting."""
    applied_on: str | None = None
    if on:
        try:
            applied_on = date.fromisoformat(on).isoformat()
        except ValueError:
            output_error(f"--on must be an ISO date (YYYY-MM-DD); got {on!r}")
            raise typer.Exit(3) from None

    opened = _as_dict(
        _post(remote, EP_APPLICATIONS, json_body={"posting_id": posting_id, "source": SOURCE})
    )
    application_id = opened.get("id")
    if not submit:
        _emit(
            opened,
            {"submitted": False},
            human=human,
            summary=f"application {application_id} open ({opened.get('status')})",
        )
        return

    body: dict[str, Any] = {"status": "applied", "source": SOURCE}
    if note:
        body["note"] = note
    if applied_on:
        body["applied_on"] = applied_on
    moved = _as_dict(_post(remote, f"{EP_APPLICATIONS}/{application_id}/status", json_body=body))
    data = {**opened, **moved}
    _emit(
        data,
        {"submitted": True},
        human=human,
        summary=f"application {application_id} applied on {moved.get('applied_on')}",
    )


@app.command()
@usage(
    surface="st.jobs.status",
    cmd="st jobs status <app-id> <status> -m 'note'",
    when="an application moved — a reply arrived, an interview was scheduled, a rejection landed",
    why="writes a timeline transition as well as the new status, so funnel analytics stay truthful",
    precautions=(
        "records state only; nothing is sent to an employer",
        "statuses: evaluated applied responded interview offer rejected discarded skip hired",
    ),
    examples=("st jobs status 9 interview -m 'panel scheduled for the 12th'",),
    task_types=("jobs", "career"),
    tier="mandate",
)
def status(
    application_id: Annotated[int, typer.Argument(help="Application id from st jobs track")],
    to_status: Annotated[str, typer.Argument(metavar="STATUS", help="New status")],
    note: Annotated[str | None, typer.Option("--note", "-m", help="Note on the transition")] = None,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Move an application to a new status and record the transition."""
    _require(to_status, flag="STATUS", allowed=STATUSES)
    body: dict[str, Any] = {"status": to_status, "source": SOURCE}
    if note:
        body["note"] = note
    data = _as_dict(_post(remote, f"{EP_APPLICATIONS}/{application_id}/status", json_body=body))
    _emit(
        data,
        None,
        human=human,
        summary=f"application {application_id} → {data.get('status')}",
    )


@app.command()
@usage(
    surface="st.jobs.track",
    cmd="st jobs track --status interview",
    when="review what is in flight, or find the application id for a status change",
    precautions=("read-only",),
    task_types=("jobs", "career"),
    tier="reference",
)
def track(
    status_filter: Annotated[
        str | None, typer.Option("--status", help="Filter to one status")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """List applications, most recently moved first."""
    params: dict[str, Any] = {"limit": limit}
    if status_filter:
        _require(status_filter, flag="--status", allowed=STATUSES)
        params["status"] = status_filter
    data = _as_dict(_get(remote, EP_APPLICATIONS, params=params))
    rows = _as_list(data.get("applications"))
    lines = [
        f"#{row.get('id')}  {row.get('status')!s:<10} {_score(row.get('score'))}  {_where(row)}"
        for row in rows
    ]
    _emit(
        rows,
        {"total": data.get("total")},
        human=human,
        summary="\n".join(lines) or "No applications.",
    )


@app.command()
@usage(
    surface="st.jobs.followups",
    cmd="st jobs followups --due",
    when="check which applications are owed a nudge",
    precautions=("read-only; sending is manual — mark one sent from the UI after you send it",),
    task_types=("jobs", "career"),
    tier="reference",
)
def followups(
    due: Annotated[bool, typer.Option("--due", help="Only follow-ups already due")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Pending follow-ups, earliest due first."""
    data = _as_dict(_get(remote, EP_FOLLOWUPS, params={"due": due, "limit": limit}))
    rows = _as_list(data.get("followups"))
    lines = [
        f"{'DUE ' if row.get('overdue') else '    '}#{row.get('application_id')}  "
        f"{row.get('due_at')}  {row.get('kind')}  {_where(row)}"
        for row in rows
    ]
    _emit(
        rows,
        {"total": data.get("total"), "overdue": data.get("overdue")},
        human=human,
        summary="\n".join(lines) or "Nothing due.",
    )


@app.command()
@usage(
    surface="st.jobs.stats",
    cmd="st jobs stats",
    when="report on the search: how many applications sit at each stage, and what the board holds",
    precautions=("read-only; counts are current state, not a time series",),
    task_types=("jobs", "career"),
    tier="reference",
)
def stats(
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """Application funnel and posting-state counts."""
    funnel = _as_dict(_get(remote, EP_FUNNEL))
    postings = _as_dict(_get(remote, EP_POSTING_STATES))
    counts = _as_dict(funnel.get("counts"))
    order = [str(s) for s in (funnel.get("order") or []) if isinstance(s, str)]
    # `order` is the funnel's happy path and stops at `hired`; the terminal
    # statuses off it still hold applications, and a summary that drops them
    # understates the total it prints beside them.
    rest = sorted(name for name in counts if name not in order)
    lines = ["applications:"]
    lines += [f"  {name:<10} {counts.get(name, 0)}" for name in [*order, *rest]]
    lines.append("postings:")
    lines += [f"  {name:<12} {value}" for name, value in sorted(postings.items())]
    _emit(
        {"funnel": funnel, "postings": postings},
        {"applications": funnel.get("total")},
        human=human,
        summary="\n".join(lines),
    )


@app.command()
@usage(
    surface="st.jobs.profile",
    cmd="st jobs profile",
    when="before writing anything on the candidate's behalf — targets, comp, authorization, allowed metrics",
    why="the same candidate block the screener and tailor agents are given, so an agent-written draft cannot drift from theirs",
    precautions=(
        "read-only; cv_facts.allow_metrics is the only set of numbers permitted in generated documents",
    ),
    task_types=("jobs", "career"),
    tier="reference",
)
def profile(
    human: Annotated[bool, typer.Option("--human", help="Plain-text rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use hosts.production_api")] = False,
) -> None:
    """The candidate profile every agent prompt is built from."""
    data = _as_dict(_get(remote, EP_PROFILE))
    facts = _as_dict(data.get("cv_facts"))
    cv = _as_dict(data.get("cv"))
    lines = [str(data.get("summary") or "No candidate profile is on file.")]
    lines.append(f"CV on file: {'yes' if cv.get('available') else 'no'}")
    if facts.get("allow_metrics"):
        lines.append("Permitted metrics: " + "; ".join(str(m) for m in facts["allow_metrics"]))
    if facts.get("forbidden_phrases"):
        lines.append("Forbidden: " + "; ".join(str(p) for p in facts["forbidden_phrases"]))
    _emit(data, None, human=human, summary="\n".join(lines))
