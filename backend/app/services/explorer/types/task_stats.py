"""Task execution statistics fetching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, text

from ....logging_config import get_logger
from .database_config import get_db_url_for_project

logger = get_logger(__name__)


def fetch_task_stats(project_id: str) -> dict[str, dict[str, Any]]:
    """Fetch task execution stats from celery_taskmeta for the last 7 days.

    Returns dict mapping task_name -> {last_run_at, success_count, failure_count, success_rate_pct}
    """
    db_url = get_db_url_for_project(project_id)
    if not db_url:
        logger.debug(f"No DB URL for {project_id}, skipping task stats")
        return {}

    stats: dict[str, dict[str, Any]] = {}
    seven_days_ago = datetime.now(UTC) - timedelta(days=7)

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        name,
                        MAX(date_done) as last_run,
                        COUNT(*) FILTER (WHERE status = 'SUCCESS') as success_count,
                        COUNT(*) FILTER (WHERE status = 'FAILURE') as failure_count,
                        COUNT(*) as total_count
                    FROM celery_taskmeta
                    WHERE date_done >= :since AND name IS NOT NULL
                    GROUP BY name
                """),
                {"since": seven_days_ago},
            )

            for row in result:
                task_name = row[0]
                last_run = row[1]
                success_count = row[2]
                failure_count = row[3]
                total_count = row[4]

                success_rate = (
                    round(success_count / total_count * 100, 1) if total_count > 0 else None
                )

                stats[task_name] = {
                    "last_run_at": last_run.isoformat() if last_run else None,
                    "success_count_7d": success_count,
                    "failure_count_7d": failure_count,
                    "success_rate_pct": success_rate,
                }

        logger.info(f"Fetched stats for {len(stats)} tasks from celery_taskmeta")

    except Exception as e:
        logger.warning(f"Failed to fetch task stats: {e}")

    return stats
