"""Phase-1 wiring tests: redundancy clusters -> consolidate-duplicate tasks.

The detector's precision + the 2-3-member cap are the gate (proven in
tests/explorer/test_redundancy.py). These tests cover the *pipeline* contract:
one task per live cluster, dedupe on re-run, retire when a cluster is no longer
live, the per-scan creation cap, and the create_consolidation_task payload.

Mock-based, matching the existing test_task_generation.py style (no DB).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.explorer.redundancy import DuplicateCluster, cluster_signature
from app.tasks.autonomous.refactor_generation import (
    _consolidation_enabled,
    generate_consolidation_tasks_internal,
)


def _sym(name: str, path: str, kind: str = "function") -> dict[str, object]:
    return {"name": name, "file_path": path, "kind": kind}


def _cluster(members: list[dict[str, object]], score: float = 0.92) -> DuplicateCluster:
    return DuplicateCluster(members=members, score=score, reason="consolidate-duplicate")


_CLUSTER_A = _cluster(
    [_sym("is_subtask_id", "backend/app/a.py"), _sym("is_subtask_id", "backend/app/b.py")]
)
_CLUSTER_B = _cluster(
    [_sym("humanize", "frontend/x.ts"), _sym("humanize", "frontend/y.ts")]
)


def _key(cluster: DuplicateCluster) -> str:
    return f"upkeep:consolidate-duplicate:{cluster_signature(cluster)}"


class TestClusterSignature:
    def test_stable_and_order_independent(self) -> None:
        members = [_sym("foo", "a.py"), _sym("foo", "b.py")]
        sig1 = cluster_signature(_cluster(members))
        sig2 = cluster_signature(_cluster(list(reversed(members))))
        assert sig1 == sig2

    def test_distinct_clusters_differ(self) -> None:
        assert cluster_signature(_CLUSTER_A) != cluster_signature(_CLUSTER_B)


class TestConsolidationRolloutGate:
    """The per-project denylist that gates consolidate-duplicate filing."""

    def test_global_by_default_for_layered_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONSOLIDATION_PROJECT_DENYLIST", raising=False)
        assert _consolidation_enabled("summitflow") is True
        assert _consolidation_enabled("agent-hub") is True
        assert _consolidation_enabled("portfolio-ai") is True

    def test_default_denylist_excludes_domain_ambiguous_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CONSOLIDATION_PROJECT_DENYLIST", raising=False)
        assert _consolidation_enabled("monkey-fight") is False

    def test_empty_denylist_enables_every_project(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONSOLIDATION_PROJECT_DENYLIST", "")
        assert _consolidation_enabled("monkey-fight") is True

    def test_explicit_denylist_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONSOLIDATION_PROJECT_DENYLIST", "vantage, sha")
        assert _consolidation_enabled("vantage") is False
        assert _consolidation_enabled("monkey-fight") is True  # no longer denied

    def test_denied_project_files_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONSOLIDATION_PROJECT_DENYLIST", raising=False)
        with patch(
            "app.tasks.autonomous.refactor_generation.find_redundancy_candidates"
        ) as mock_find:
            result = generate_consolidation_tasks_internal("monkey-fight", project_root="/tmp/mf")
        assert result == {
            "consolidation_created": 0,
            "consolidation_candidates": 0,
            "consolidation_pruned": 0,
        }
        mock_find.assert_not_called()  # gated out before the detector even runs


@pytest.fixture(autouse=True)
def _open_rollout_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pipeline-contract tests below use the placeholder project "proj"; pin an
    empty denylist so they exercise filing rather than the gate short-circuit."""
    monkeypatch.setenv("CONSOLIDATION_PROJECT_DENYLIST", "")


@patch("app.tasks.autonomous.refactor_generation.create_consolidation_task")
@patch("app.tasks.autonomous.refactor_generation._open_consolidation_source_keys")
@patch("app.tasks.autonomous.refactor_generation.prune_obsolete_upkeep_signal_tasks")
@patch("app.tasks.autonomous.refactor_generation.find_redundancy_candidates")
@patch("app.tasks.autonomous.refactor_generation.Path")
class TestGenerateConsolidationTasks:
    @staticmethod
    def _prune_zero() -> dict[str, int]:
        return {"deleted": 0, "completed": 0, "cancelled": 0, "skipped": 0, "skipped_active": 0}

    def test_creates_one_task_per_live_cluster(
        self,
        mock_path: MagicMock,
        mock_find: MagicMock,
        mock_prune: MagicMock,
        mock_open_keys: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_path.return_value.exists.return_value = True
        mock_find.return_value = [_CLUSTER_A, _CLUSTER_B]
        mock_prune.return_value = self._prune_zero()
        mock_open_keys.return_value = set()
        mock_create.side_effect = ["task-1", "task-2"]

        result = generate_consolidation_tasks_internal("proj", project_root="/tmp/proj")

        assert result["consolidation_created"] == 2
        assert result["consolidation_candidates"] == 2
        created_keys = {call.args[2] for call in mock_create.call_args_list}
        assert created_keys == {_key(_CLUSTER_A), _key(_CLUSTER_B)}

    def test_dedupes_against_open_tasks(
        self,
        mock_path: MagicMock,
        mock_find: MagicMock,
        mock_prune: MagicMock,
        mock_open_keys: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_path.return_value.exists.return_value = True
        mock_find.return_value = [_CLUSTER_A, _CLUSTER_B]
        mock_prune.return_value = self._prune_zero()
        mock_open_keys.return_value = {_key(_CLUSTER_A)}  # A already has an open task
        mock_create.return_value = "task-2"

        result = generate_consolidation_tasks_internal("proj", project_root="/tmp/proj")

        assert result["consolidation_created"] == 1
        assert mock_create.call_count == 1
        assert mock_create.call_args.args[2] == _key(_CLUSTER_B)

    def test_retires_via_prune_with_live_source_keys(
        self,
        mock_path: MagicMock,
        mock_find: MagicMock,
        mock_prune: MagicMock,
        mock_open_keys: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_path.return_value.exists.return_value = True
        mock_find.return_value = [_CLUSTER_A]
        mock_prune.return_value = self._prune_zero()
        mock_open_keys.return_value = set()
        mock_create.return_value = "task-1"

        generate_consolidation_tasks_internal("proj", project_root="/tmp/proj")

        mock_prune.assert_called_once()
        args, kwargs = mock_prune.call_args
        assert args[0] == "proj"
        assert args[1] == "consolidate-duplicate"
        assert kwargs["active_source_keys"] == {_key(_CLUSTER_A)}

    def test_respects_per_scan_cap(
        self,
        mock_path: MagicMock,
        mock_find: MagicMock,
        mock_prune: MagicMock,
        mock_open_keys: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_path.return_value.exists.return_value = True
        third = _cluster([_sym("dup", "p/c.py"), _sym("dup", "p/d.py")])
        mock_find.return_value = [_CLUSTER_A, _CLUSTER_B, third]
        mock_prune.return_value = self._prune_zero()
        mock_open_keys.return_value = set()
        mock_create.side_effect = ["task-1"]

        result = generate_consolidation_tasks_internal(
            "proj", project_root="/tmp/proj", create_limit=1
        )

        assert result["consolidation_created"] == 1
        assert mock_create.call_count == 1

    def test_excludes_cluster_whose_files_are_gone(
        self,
        mock_path: MagicMock,
        mock_find: MagicMock,
        mock_prune: MagicMock,
        mock_open_keys: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_path.return_value.exists.return_value = False  # no member file on disk
        mock_find.return_value = [_CLUSTER_A]
        mock_prune.return_value = self._prune_zero()
        mock_open_keys.return_value = set()

        result = generate_consolidation_tasks_internal("proj", project_root="/tmp/proj")

        assert result["consolidation_candidates"] == 0
        assert result["consolidation_created"] == 0
        mock_create.assert_not_called()
        # The now-empty live set is still handed to prune so the stale task retires.
        assert mock_prune.call_args.kwargs["active_source_keys"] == set()


class TestCreateConsolidationTask:
    @patch("app.tasks.autonomous.task_builders.create_task_with_spirit")
    def test_payload_carries_upkeep_contract(self, mock_create: MagicMock) -> None:
        from app.tasks.autonomous.task_builders import create_consolidation_task

        mock_create.return_value = "task-xyz"
        members = [
            _sym("is_subtask_id", "backend/app/b.py"),
            _sym("is_subtask_id", "backend/app/a.py"),
        ]
        source_key = "upkeep:consolidate-duplicate:deadbeef"

        task_id = create_consolidation_task("proj", members, source_key)

        assert task_id == "task-xyz"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["task_type"] == "refactor"  # no new TaskType
        assert "consolidate-duplicate" in kwargs["labels"]
        upkeep = kwargs["context"]["upkeep"]
        assert upkeep["source_key"] == source_key
        assert upkeep["signal_type"] == "consolidate-duplicate"
        # All member files become the task scope, sorted+deduped.
        assert kwargs["context"]["files_to_modify"] == ["backend/app/a.py", "backend/app/b.py"]


class TestFindRedundancyCandidatesCap:
    @patch("app.storage.explorer_symbols._load_symbols_for_detection")
    def test_drops_clusters_larger_than_cap(self, mock_load: MagicMock) -> None:
        from app.storage.explorer_symbols import find_redundancy_candidates

        # Four verbatim copies of the same public function across four files: a
        # 4-member cluster, which exceeds the default 2-3 cap and must be dropped.
        mock_load.return_value = [
            {
                "name": "compute_hash", "file_path": f"backend/app/m{i}.py",
                "kind": "function", "qualified_name": "compute_hash",
                "signature": "def compute_hash(data)", "language": "python",
                "summary": "compute a hash of data", "keywords": ["hash", "data"],
            }
            for i in range(4)
        ]

        assert find_redundancy_candidates("proj", max_cluster_size=3) == []
        assert len(find_redundancy_candidates("proj", max_cluster_size=4)) == 1
