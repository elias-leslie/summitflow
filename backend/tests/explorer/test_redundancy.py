"""Tests for the redundancy detector — locks the Phase-0 precision bar in CI.

The corpus/harness encode the precision-first contract: zero false positives on a
hard-negative-rich labeled set (including the false-positive classes found on the
live index — cross-layer delegation, interface methods, frontend handlers,
script boilerplate). Recall on lexically-reachable duplicates must stay perfect;
pure synonyms are an accepted miss.
"""

from __future__ import annotations

from app.services.explorer.redundancy import (
    DEFAULT_CONFIG,
    SimilarityConfig,
    is_eligible,
    is_first_party,
    score_pair,
    tokenize_name,
)

from .redundancy_corpus import SYMBOLS
from .redundancy_harness import evaluate


def _by_id(sid: str) -> dict:
    return next(s for s in SYMBOLS if s["id"] == sid)


class TestHarnessBar:
    """The headline Phase-0 gate."""

    def test_zero_false_positives(self) -> None:
        result = evaluate()
        assert result.fp_count == 0, [
            (sorted(p), f"{score:.3f}", reason)
            for p, score, reason, _ in result.false_positives
        ]
        assert result.precision == 1.0

    def test_perfect_lexical_recall(self) -> None:
        # Missing a lexically-reachable duplicate would mean the detector is too
        # timid; pure synonyms are excluded from this metric by design.
        assert evaluate().achievable_recall == 1.0


class TestTokenize:
    def test_camel_and_snake_equivalent(self) -> None:
        assert tokenize_name("formatDuration") == tokenize_name("format_duration")

    def test_strips_version_and_copy_markers(self) -> None:
        assert tokenize_name("parse_config_v2") == tokenize_name("parse_config")
        assert tokenize_name("serialize_payload_new") == tokenize_name("serialize_payload")

    def test_degenerate_all_version_name_not_emptied(self) -> None:
        assert tokenize_name("v2") != set()


class TestEligibility:
    def test_vendored_excluded(self) -> None:
        assert not is_first_party(".dev-tools/cleanroom-pydeps/numpy/__init__.py")
        assert is_first_party("backend/app/utils/dates.py")

    def test_migrations_excluded_at_any_depth(self) -> None:
        # Root-level (a-term) and nested (summitflow) alembic must both be caught.
        assert not is_first_party("alembic/versions/5cdb_add_notes.py")
        assert not is_first_party("backend/alembic/versions/abcd_x.py")
        # A real dir that merely contains an exclusion substring must NOT be caught.
        assert is_first_party("backend/app/services/redistribute/core.py")

    def test_root_migration_symbols_not_eligible(self) -> None:
        assert not is_eligible(_by_id("mig_up_a"))

    def test_convention_names_not_eligible(self) -> None:
        assert not is_eligible(_by_id("props_a"))  # React ``type Props``
        assert not is_eligible(_by_id("get_route_a"))  # Next.js ``GET`` route verb

    def test_client_sdk_mirror_rejected(self) -> None:
        ps = score_pair(_by_id("usageinfo_server"), _by_id("usageinfo_client"))
        assert ps.score == 0.0
        assert ps.reason == "client-mirror"

    def test_private_and_test_and_method_and_handler_excluded(self) -> None:
        assert not is_eligible(_by_id("priv_a"))  # _normalize
        assert not is_eligible(_by_id("test_dup_a"))  # test file + test_ name
        assert not is_eligible(_by_id("to_dict_a"))  # method kind
        assert not is_eligible(_by_id("handle_kd_a"))  # handleKeyDown
        assert not is_eligible(_by_id("parse_args_a"))  # boilerplate

    def test_public_top_level_eligible(self) -> None:
        assert is_eligible(_by_id("fmt_dur_a"))
        assert is_eligible(_by_id("collapsible_a"))  # PascalCase component stays in


class TestScoreGates:
    def test_cross_layer_delegation_rejected(self) -> None:
        ps = score_pair(_by_id("create_rule_api"), _by_id("create_rule_storage"))
        assert ps.reason == "cross-layer-delegation"
        assert ps.score == 0.0

    def test_cross_layer_takes_precedence_for_create_task(self) -> None:
        # create_task (storage) vs create_refactor_task (tasks) is rejected — here
        # the cross-layer gate fires before the specialization check; either way
        # it must score 0.0.
        ps = score_pair(_by_id("create_task"), _by_id("create_refactor_task"))
        assert ps.score == 0.0
        assert ps.reason in {"specialization", "cross-layer-delegation"}

    def test_specialization_rejected_same_layer(self) -> None:
        # Same-layer pair so the specialization gate (not cross-layer) is tested.
        base = {
            "name": "load_config", "qualified_name": "load_config", "kind": "function",
            "language": "python", "signature": "def load_config() -> dict",
            "summary": "Load config.", "keywords": ["load", "config"],
            "file_path": "backend/app/utils/cfg.py",
        }
        special = {**base, "name": "load_config_overrides",
                   "qualified_name": "load_config_overrides",
                   "file_path": "backend/app/utils/cfg_overrides.py"}
        ps = score_pair(base, special)
        assert ps.score == 0.0
        assert ps.reason == "specialization"

    def test_singular_plural_not_flagged(self) -> None:
        ps = score_pair(_by_id("get_user"), _by_id("get_users"))
        assert ps.score < DEFAULT_CONFIG.decision_threshold

    def test_genuine_same_layer_duplicate_scored(self) -> None:
        ps = score_pair(_by_id("gen_mockup_a"), _by_id("gen_mockup_b"))
        assert ps.reason == "scored"
        assert ps.score >= DEFAULT_CONFIG.decision_threshold

    def test_cross_layer_gate_can_be_disabled(self) -> None:
        cfg = SimilarityConfig(reject_cross_layer_delegation=False)
        ps = score_pair(_by_id("create_rule_api"), _by_id("create_rule_storage"), cfg)
        assert ps.reason != "cross-layer-delegation"
