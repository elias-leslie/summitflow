"""Feature Scanner - Feature capability scanner for projects.

Validates features in feature_capabilities table:
- Calculates completion from feature_tasks table (all-in-DB approach)
- Verification status calculated dynamically from tasks + acceptance criteria

Agent permissions (corruption protection):
- Scanner can only modify: last_verified_at, acceptance_criteria
- Other fields (name, description) are read-only
- Features can only be added via /task_it, deleted manually
- Subtasks can be added/toggled via API

All-in-DB architecture:
- feature_capabilities: Features with acceptance_criteria
- feature_tasks: Subtasks with completion status
- Progress = COUNT(completed=true) / COUNT(*) from feature_tasks
- Verified = tasks=0 AND all acceptance_criteria.passed=true (dynamic)

Extracted from portfolio-ai/backend/app/services/capability_feature_scanner.py
Changes from source:
  - Added project_id parameter to constructor and all methods
  - Uses get_connection() context manager instead of ConnectionManager
  - All SQL queries filter by project_id
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)


class FeatureScanner:
    """Scans and validates features in feature_capabilities table.

    Unlike other scanners that discover capabilities, this scanner validates
    existing features by checking their linked task files and completion status.

    Implements Anthropic's long-running agent patterns:
    - Restricted field modification (last_verified_at, acceptance_criteria only)
    - Verification status calculated dynamically
    - Section completion parsing from markdown
    """

    def __init__(self, project_id: str) -> None:
        """Initialize feature scanner.

        Args:
            project_id: Project ID for scoping all operations
        """
        self.project_id = project_id

    def scan(self) -> list[dict[str, Any]]:
        """Scan all features and validate their completion status.

        Uses all-in-DB approach: calculates completion from feature_tasks table.

        Returns:
            List of feature dicts with validation results:
                - feature_id: str
                - name: str
                - category: str
                - total_tasks: int (from DB)
                - completed_tasks: int (from DB)
                - completion_pct: int
                - health_status: str
                - tasks: list[dict] (subtasks from DB)
                - acceptance_criteria: list[dict] (with passed status)
        """
        logger.info("scanning_features", project_id=self.project_id)

        features = []

        with get_connection() as conn, conn.cursor() as cur:
            # Get all features with task counts from database
            cur.execute(
                """
                SELECT
                    f.id, f.feature_id, f.name, f.category, f.description,
                    f.last_verified_at, f.created_at, f.updated_at,
                    COALESCE(t.total_tasks, 0) as db_total_tasks,
                    COALESCE(t.completed_tasks, 0) as db_completed_tasks,
                    CASE WHEN f.verification_layers IS NULL OR f.verification_layers = '{}'
                         THEN ARRAY['Frontend', 'Backend', 'UI']
                         ELSE f.verification_layers END as layers,
                    COALESCE(f.layer_results, '{}'::jsonb) as layer_results,
                    f.priority,
                    COALESCE(f.acceptance_criteria, '[]'::jsonb) as acceptance_criteria,
                    COALESCE(f.vision_goals, '{}') as vision_goals
                FROM feature_capabilities f
                LEFT JOIN (
                    SELECT
                        feature_id,
                        COUNT(*) as total_tasks,
                        COUNT(*) FILTER (WHERE completed = true) as completed_tasks
                    FROM feature_tasks
                    GROUP BY feature_id
                ) t ON t.feature_id = f.id
                WHERE f.project_id = %s
                ORDER BY f.category, f.feature_id
                """,
                (self.project_id,),
            )
            rows = cur.fetchall()

            # Batch load ALL tasks in one query to avoid N+1
            cur.execute(
                """
                SELECT
                    ft.feature_id, ft.task_id, ft.description, ft.completed,
                    ft.order_num, ft.completed_at, ft.completed_by,
                    ft.files, ft.notes, ft.status, ft.effort, ft.task_type
                FROM feature_tasks ft
                JOIN feature_capabilities fc ON ft.feature_id = fc.id
                WHERE fc.project_id = %s
                ORDER BY ft.feature_id, ft.order_num, ft.task_id
                """,
                (self.project_id,),
            )
            all_tasks_rows = cur.fetchall()

            # Index tasks by feature DB id for O(1) lookup
            tasks_by_feature: dict[int, list[dict[str, Any]]] = {}
            for task_row in all_tasks_rows:
                feature_db_id_raw = task_row[0]
                if not isinstance(feature_db_id_raw, int):
                    logger.warning("unexpected_feature_id_type", value=feature_db_id_raw)
                    continue
                feature_db_id = feature_db_id_raw
                task_dict: dict[str, Any] = {
                    "task_id": task_row[1],
                    "description": task_row[2],
                    "completed": task_row[3],
                    "order_num": task_row[4],
                    "completed_at": task_row[5],
                    "completed_by": task_row[6],
                    "files": task_row[7] if task_row[7] else [],
                    "notes": task_row[8],
                    "status": task_row[9] or "pending",
                    "effort": task_row[10],
                    "task_type": task_row[11] or "implementation",
                }
                if feature_db_id not in tasks_by_feature:
                    tasks_by_feature[feature_db_id] = []
                tasks_by_feature[feature_db_id].append(task_dict)

            for row in rows:
                feature = self._validate_feature(row, tasks_by_feature)
                features.append(feature)

        logger.info(
            "feature_scan_complete", project_id=self.project_id, features_scanned=len(features)
        )

        return features

    def _validate_feature(
        self, row: tuple[Any, ...], tasks_by_feature: dict[int, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Validate a single feature's completion status.

        Args:
            row: Database row tuple with task counts
            tasks_by_feature: Pre-fetched tasks indexed by feature DB id

        Returns:
            Feature dict with validation results
        """
        (
            db_id,
            feature_id,
            name,
            category,
            description,
            last_verified_at,
            created_at,
            updated_at,
            db_total_tasks,
            db_completed_tasks,
            layers,
            layer_results,
            priority,
            acceptance_criteria,
            vision_goals,
        ) = row

        total_tasks = db_total_tasks
        completed_tasks = db_completed_tasks

        # Get subtasks from pre-fetched dict
        tasks = tasks_by_feature.get(db_id, [])

        # Calculate completion percentage
        completion_pct = 0
        if total_tasks > 0:
            completion_pct = int((completed_tasks / total_tasks) * 100)

        # Calculate health status
        calculated_health = self._calculate_health_status(
            has_tasks=db_total_tasks > 0,
            completion_pct=completion_pct,
        )

        # Calculate effective priority
        effective_priority = self._calculate_effective_priority(
            priority=priority,
            layers=layers,
            layer_results=layer_results,
            acceptance_criteria=acceptance_criteria,
        )

        return {
            "id": db_id,
            "feature_id": feature_id,
            "name": name,
            "category": category,
            "description": description,
            "layers": layers if layers else ["Frontend", "Backend", "UI"],
            "layer_results": layer_results if layer_results else {},
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "completion_pct": completion_pct,
            "health_status": calculated_health,
            "last_verified_at": last_verified_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "tasks": tasks,
            "priority": priority,
            "effective_priority": effective_priority,
            "acceptance_criteria": acceptance_criteria if acceptance_criteria else [],
            "vision_goals": vision_goals if vision_goals else [],
        }

    def _calculate_health_status(
        self,
        has_tasks: bool,
        completion_pct: int,
    ) -> str:
        """Calculate health status based on task state.

        Args:
            has_tasks: Whether has DB tasks
            completion_pct: Completion percentage of tasks

        Returns:
            Health status: 'active', 'orphaned'
        """
        if not has_tasks:
            return "orphaned"
        return "active"

    def _calculate_effective_priority(
        self,
        priority: int | None,
        layers: list[str] | None,
        layer_results: dict[str, Any] | None,
        acceptance_criteria: list[dict[str, Any]] | None,
    ) -> int:
        """Calculate effective priority based on verification state.

        Args:
            priority: User override priority (1-5), or None for auto
            layers: List of verification layers
            layer_results: Dict of layer verification results
            acceptance_criteria: List of acceptance criteria dicts

        Returns:
            Effective priority 1-5:
                1 = Critical (failing criteria)
                2 = High (almost verified)
                3 = Medium (partially verified)
                4 = Low (started)
                5 = Backlog (not started)
        """
        if priority is not None:
            return priority

        criteria = acceptance_criteria if acceptance_criteria else []
        if criteria and any(c.get("passed") is False for c in criteria):
            return 1

        layers_list = layers if layers else []
        results = layer_results if layer_results else {}
        total_layers = len(layers_list)
        verified_layers = len(results)

        if total_layers == 0:
            return 5

        verification_pct = (verified_layers / total_layers) * 100

        if verification_pct >= 80:
            return 2
        if verification_pct >= 50:
            return 3
        if verification_pct > 0:
            return 4
        return 5

    def update_last_verified(self, feature_id: str) -> bool:
        """Update last_verified_at timestamp.

        Args:
            feature_id: Feature ID (e.g., "FEAT-001")

        Returns:
            True if update succeeded, False otherwise
        """
        logger.info(
            "updating_last_verified",
            project_id=self.project_id,
            feature_id=feature_id,
        )

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE feature_capabilities
                SET last_verified_at = %s,
                    updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                """,
                (datetime.now(UTC), self.project_id, feature_id),
            )
            conn.commit()

            return cur.rowcount > 0

    def add_feature(
        self,
        feature_id: str,
        name: str,
        category: str,
        description: str | None = None,
    ) -> bool:
        """Add a new feature to the registry.

        Args:
            feature_id: Feature ID (e.g., "FEAT-001")
            name: Feature name
            category: Category (Dashboard, Watchlist, etc.)
            description: Optional description

        Returns:
            True if insert succeeded, False otherwise
        """
        logger.info(
            "adding_feature",
            project_id=self.project_id,
            feature_id=feature_id,
            name=name,
            category=category,
        )

        with get_connection() as conn, conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO feature_capabilities (
                        project_id, feature_id, name, category, description,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                    """,
                    (
                        self.project_id,
                        feature_id,
                        name,
                        category,
                        description,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(
                    "add_feature_failed",
                    project_id=self.project_id,
                    feature_id=feature_id,
                    error=str(e),
                )
                return False

    def get_next_feature_id(self) -> str:
        """Get the next available feature ID for this project.

        Returns:
            Next feature ID in format FEAT-XXX
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(
                    CAST(SUBSTRING(feature_id FROM 'FEAT-([0-9]+)') AS INTEGER)
                )
                FROM feature_capabilities
                WHERE project_id = %s AND feature_id LIKE 'FEAT-%'
                """,
                (self.project_id,),
            )
            row = cur.fetchone()

            max_num = row[0] if row and row[0] else 0
            return f"FEAT-{int(max_num) + 1:03d}"

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics for features in this project.

        Returns:
            Summary dict with counts and breakdowns
        """
        with get_connection() as conn, conn.cursor() as cur:
            # Total count
            cur.execute(
                "SELECT COUNT(*) FROM feature_capabilities WHERE project_id = %s",
                (self.project_id,),
            )
            total_row = cur.fetchone()
            total = total_row[0] if total_row else 0

            # By category
            cur.execute(
                """
                SELECT category, COUNT(*)
                FROM feature_capabilities
                WHERE project_id = %s
                GROUP BY category
                ORDER BY COUNT(*) DESC
                """,
                (self.project_id,),
            )
            category_rows = cur.fetchall()
            category_breakdown = {row[0] or "Uncategorized": row[1] for row in category_rows}

            # By health status
            cur.execute(
                """
                SELECT
                    CASE
                        WHEN t.total_tasks = 0 OR t.total_tasks IS NULL THEN 'orphaned'
                        ELSE 'active'
                    END as health_status,
                    COUNT(*)
                FROM feature_capabilities f
                LEFT JOIN (
                    SELECT feature_id, COUNT(*) as total_tasks
                    FROM feature_tasks
                    GROUP BY feature_id
                ) t ON t.feature_id = f.id
                WHERE f.project_id = %s
                GROUP BY 1
                """,
                (self.project_id,),
            )
            health_rows = cur.fetchall()
            health_breakdown = {row[0] or "unknown": row[1] for row in health_rows}

            return {
                "project_id": self.project_id,
                "total": total,
                "category_breakdown": category_breakdown,
                "health_breakdown": health_breakdown,
            }
