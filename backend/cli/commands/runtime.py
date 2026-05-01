"""Runtime observability commands for agents."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Any

import typer

from app.services.runtime_metrics_sampler import sample_runtime_metrics_once
from app.storage.runtime_metrics import (
    list_runtime_metric_series,
    summarize_runtime_metric_samples,
)

app = typer.Typer(
    help="Runtime observability. Compact by default for agent troubleshooting.",
    no_args_is_help=True,
)

_SINCE_RE = re.compile(r"^(\d+)(m|h|d)?$")


def _since_minutes(value: str) -> int:
    match = _SINCE_RE.fullmatch(value.strip().lower())
    if match is None:
        raise typer.BadParameter("Use minutes, hours, or days, e.g. 30m, 6h, 2d")
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "d":
        return amount * 24 * 60
    if unit == "h":
        return amount * 60
    return amount


def _fmt_time(value: datetime | str | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _fmt_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _fmt_mib(value: int | None) -> str:
    return "-" if value is None else f"{value / 1024 / 1024:.1f}"


def _sample_count(series: list[dict[str, Any]]) -> int:
    return sum(len(item.get("samples") or []) for item in series)


@app.command()
def sample() -> None:
    """Force one runtime metrics sample into the historical store."""
    stored = asyncio.run(sample_runtime_metrics_once())
    print(f"RUNTIME_SAMPLE:stored={stored}")


@app.command()
def metrics(
    service: Annotated[
        str | None,
        typer.Option("--service", "-s", help="Runtime service id."),
    ] = None,
    since: Annotated[
        str,
        typer.Option("--since", help="Window: Nm, Nh, or Nd."),
    ] = "6h",
    bucket_seconds: Annotated[
        int,
        typer.Option("--bucket-seconds", min=15, max=3600, help="History bucket size."),
    ] = 300,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=200, help="Summary rows or sample points."),
    ] = 40,
    samples: Annotated[
        bool,
        typer.Option("--samples", help="Print recent bucketed points instead of summary."),
    ] = False,
) -> None:
    """Query persisted CPU/memory history."""
    minutes = _since_minutes(since)
    if samples:
        series = list_runtime_metric_series(
            service=service,
            since_minutes=minutes,
            bucket_seconds=bucket_seconds,
            limit=50000,
        )
        print(
            f"RUNTIME_METRIC_SAMPLES:window={since} bucket={bucket_seconds}s "
            f"services={len(series)} points={_sample_count(series)}"
        )
        for item in series:
            service_id = item["service"]
            for sample_item in (item.get("samples") or [])[-limit:]:
                print(
                    "RMS:"
                    f"svc={service_id} "
                    f"t={_fmt_time(sample_item.get('sampled_at'))} "
                    f"state={sample_item.get('state') or '-'} "
                    f"cpu={_fmt_float(sample_item.get('cpu_percent'))} "
                    f"cpu_max={_fmt_float(sample_item.get('cpu_percent_max'))} "
                    f"mem_mib={_fmt_mib(sample_item.get('memory_used_bytes'))} "
                    f"mem_pct={_fmt_float(sample_item.get('memory_percent'))}"
                )
        return

    rows = summarize_runtime_metric_samples(
        service=service,
        since_minutes=minutes,
        limit=limit,
    )
    print(f"RUNTIME_METRICS:window={since} services={len(rows)}")
    for row in rows:
        print(
            "RMS:"
            f"svc={row['service']} "
            f"mgr={row.get('manager') or '-'} "
            f"cat={row.get('category') or '-'} "
            f"state={row.get('state') or '-'} "
            f"samples={row['sample_count']} "
            f"last={_fmt_time(row.get('last_sampled_at'))} "
            f"cpu_avg={_fmt_float(row.get('cpu_percent_avg'))} "
            f"cpu_max={_fmt_float(row.get('cpu_percent_max'))} "
            f"mem_avg_mib={_fmt_mib(row.get('memory_used_bytes_avg'))} "
            f"mem_max_mib={_fmt_mib(row.get('memory_used_bytes_max'))} "
            f"mem_pct_avg={_fmt_float(row.get('memory_percent_avg'))}"
        )
