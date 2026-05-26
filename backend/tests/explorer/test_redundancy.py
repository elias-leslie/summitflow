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
    _is_sibling_module_delegation,
    _param_arity,
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


class TestArityGate:
    """Facade/impl pairs differ in parameter arity even within one package/tree."""

    def test_facade_impl_arity_mismatch_rejected(self) -> None:
        # get_effective_rules: facade (project_id, category) vs impl
        # (base_standard_id, project_standard_id, category) — both storage layer,
        # so the cross-layer rule does NOT catch it; the arity gate must.
        ps = score_pair(_by_id("get_eff_rules_facade"), _by_id("get_eff_rules_impl"))
        assert ps.reason == "signature-arity-mismatch"
        assert ps.score == 0.0

    def test_validate_against_rules_arity_mismatch_rejected(self) -> None:
        ps = score_pair(_by_id("validate_rules_facade"), _by_id("validate_rules_impl"))
        assert ps.reason == "signature-arity-mismatch"

    def test_injectable_impl_arity_mismatch_rejected(self) -> None:
        ps = score_pair(_by_id("run_scan_facade"), _by_id("run_scan_impl"))
        assert ps.reason == "signature-arity-mismatch"

    def test_renamed_params_same_arity_still_scored(self) -> None:
        # A real copy that renamed its parameter but kept the same arity must NOT
        # be rejected by the arity gate.
        ps = score_pair(_by_id("slugify_a"), _by_id("slugify_b"))
        assert ps.reason == "scored"
        assert ps.score >= DEFAULT_CONFIG.decision_threshold

    def test_gate_can_be_disabled(self) -> None:
        cfg = SimilarityConfig(reject_signature_arity_mismatch=False)
        ps = score_pair(_by_id("get_eff_rules_facade"), _by_id("get_eff_rules_impl"), cfg)
        assert ps.reason != "signature-arity-mismatch"


class TestSiblingModuleDelegation:
    """A hub module and a same-dir split-out it delegates to are not duplicates."""

    def test_hub_spoke_same_arity_rejected(self) -> None:
        # get_subtask facade in subtasks.py vs impl in subtasks_crud.py — SAME
        # arity, so only the sibling-module gate can catch it.
        ps = score_pair(_by_id("get_subtask_hub"), _by_id("get_subtask_spoke"))
        assert ps.reason == "sibling-module-delegation"
        assert ps.score == 0.0

    def test_noarg_hub_spoke_rejected(self) -> None:
        ps = score_pair(_by_id("project_db_url_hub"), _by_id("project_db_url_spoke"))
        assert ps.reason == "sibling-module-delegation"

    def test_version_suffix_sibling_is_not_delegation(self) -> None:
        # codec.py vs codec_new.py is a version copy, NOT a domain split — it must
        # remain a true positive (ser_payload), so the gate must not fire.
        ps = score_pair(_by_id("ser_payload_a"), _by_id("ser_payload_b"))
        assert ps.reason == "scored"
        assert ps.score >= DEFAULT_CONFIG.decision_threshold

    def test_helper_predicate(self) -> None:
        s = _is_sibling_module_delegation
        assert s("a/b/subtasks.py", "a/b/subtasks_crud.py")
        assert s("a/b/db_workbench.py", "a/b/db_workbench_targets.py")
        assert not s("a/b/codec.py", "a/b/codec_new.py")  # version suffix
        assert not s("a/b/codec.py", "a/b/codec_v2.py")  # version suffix
        assert not s("a/b/foo.py", "a/c/foo_bar.py")  # different directory
        assert not s("a/b/parser.py", "a/b/lexer.py")  # unrelated stems
        assert not s("a/b/backups.ts", "a/b/backup-sources.ts")  # not a prefix sibling

    def test_sibling_constant_is_genuine_duplicate(self) -> None:
        # A CONSTANT cannot delegate — re-declared in a sibling module it is a real
        # duplicate (should import the shared value), so it stays flagged.
        ps = score_pair(_by_id("default_ttl_a"), _by_id("default_ttl_b"))
        assert ps.reason == "scored"
        assert ps.score >= DEFAULT_CONFIG.decision_threshold

    def test_gate_can_be_disabled(self) -> None:
        cfg = SimilarityConfig(reject_sibling_module_delegation=False)
        ps = score_pair(_by_id("get_subtask_hub"), _by_id("get_subtask_spoke"), cfg)
        assert ps.reason != "sibling-module-delegation"


class TestParamArity:
    def test_simple_args(self) -> None:
        assert _param_arity("def f(a: int, b: str) -> None") == 2

    def test_empty_args(self) -> None:
        assert _param_arity("def f() -> dict") == 0

    def test_drops_self_and_cls(self) -> None:
        assert _param_arity("def m(self, x: int) -> None") == 1
        assert _param_arity("def m(cls, x, y) -> None") == 2

    def test_nested_brackets_not_counted(self) -> None:
        # Commas inside annotations/defaults must not inflate the count.
        assert _param_arity("def f(a: dict[str, int], b: list[tuple[int, int]]) -> None") == 2
        assert _param_arity("def f(a=g(1, 2), b={'k': 'v'}) -> None") == 2

    def test_no_parens_is_unknown(self) -> None:
        # No argument list -> unknown arity (None), so it is never compared.
        assert _param_arity("class HealthResponse") is None
        assert _param_arity("status = 'ok'") is None
        assert _param_arity("") is None
        assert _param_arity(None) is None

    def test_class_base_does_not_match_baseless_class(self) -> None:
        # ``class X`` (None) vs ``class X(BaseModel)`` (parses to 1) must NOT fire
        # the arity gate as a mismatch — None short-circuits the comparison, so
        # the pair falls through to the domain-corroboration gate instead.
        cfg = DEFAULT_CONFIG
        a = {
            "name": "VariantMetrics", "qualified_name": "VariantMetrics", "kind": "class",
            "language": "python", "signature": "class VariantMetrics",
            "summary": "Metrics.", "keywords": ["variant", "metrics"],
            "file_path": "scripts/x.py",
        }
        b = {**a, "signature": "class VariantMetrics(BaseModel)",
             "file_path": "backend/app/api/y.py"}
        ps = score_pair(a, b, cfg)
        assert ps.reason != "signature-arity-mismatch"

    def test_varargs_count_as_params(self) -> None:
        assert _param_arity("def f(*args, **kwargs) -> None") == 2


class TestClassDomainCorroboration:
    """Same-name wire-model classes share only name + framework boilerplate."""

    def test_schema_class_name_collision_rejected(self) -> None:
        # ClientListResponse in two API domains: matching outer shape, different
        # inner element types — invisible to the index (fields aren't captured),
        # so only name + framework tokens are shared. Must be rejected.
        ps = score_pair(_by_id("client_list_resp_a"), _by_id("client_list_resp_b"))
        assert ps.reason == "weak-domain-corroboration"
        assert ps.score == 0.0

    def test_health_response_collision_rejected(self) -> None:
        ps = score_pair(_by_id("health_resp_a"), _by_id("health_resp_b"))
        assert ps.reason == "weak-domain-corroboration"

    def test_dataclass_vs_pydantic_collision_rejected(self) -> None:
        ps = score_pair(_by_id("variant_metrics_a"), _by_id("variant_metrics_b"))
        assert ps.reason == "weak-domain-corroboration"

    def test_genuine_class_copy_with_domain_corroboration_scored(self) -> None:
        # WebhookPayload copies share concrete domain words (hmac, signature, verify)
        # beyond name + framework boilerplate, so the gate must let them through.
        ps = score_pair(_by_id("webhook_payload_a"), _by_id("webhook_payload_b"))
        assert ps.reason == "scored"
        assert ps.score >= DEFAULT_CONFIG.decision_threshold
