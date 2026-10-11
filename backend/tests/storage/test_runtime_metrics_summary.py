"""Runtime metric summary counts only samples that carry a CPU reading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.storage import runtime_metrics
from app.storage.connection import get_connection


def test_summary_sample_count_ignores_null_cpu_rows(db_schema_initialized: None) -> None:
    service = f"metric-count-{uuid4().hex[:8]}"
    statuses = [{"service": service, "display_name": service, "manager": "systemd",
                 "category": "app", "state": "running", "status": "active", "name": service}]
    try:
        runtime_metrics.record_runtime_metric_samples(
            statuses,
            [{"service": service, "name": service, "cpu_percent": "2.5%", "mem_usage": "1MiB",
              "mem_percent": "0.1%", "net_io": "n/a", "block_io": "n/a"}],
            sampled_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        runtime_metrics.record_runtime_metric_samples(
            statuses,
            [{"service": service, "name": service, "cpu_percent": "n/a", "mem_usage": "1MiB",
              "mem_percent": "0.1%", "net_io": "n/a", "block_io": "n/a"}],
            sampled_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        rows = runtime_metrics.summarize_runtime_metric_samples(service=service, since_minutes=60)

        assert rows[0]["sample_count"] == 1
        assert rows[0]["cpu_percent_avg"] == 2.5
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM runtime_metric_samples WHERE service = %s", (service,))
            conn.commit()
