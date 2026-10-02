"""Public deployment observer contracts preserve evidence and reject ambiguity."""

from __future__ import annotations

import copy
import json

import pytest
from st_sdk.native_deployment import (
    NATIVE_DEPLOYMENT_CONTRACT_VERSION,
    NativeDeploymentContractError,
    canonical_json,
    decode_json,
    validate_observation_request,
    validate_observation_response,
)


def request() -> dict:
    return {
        "contract_version": 1,
        "operation": "observe_deployment",
        "challenge": "0123456789abcdef" * 2,
        "task_id": "task-fixture",
        "project": "fixture-owner",
        "accepted_source_commit": "a" * 40,
        "acceptance_id": "acceptance-fixture",
    }


def response() -> dict:
    return {
        **{key: value for key, value in request().items() if key not in ("contract_version", "operation")},
        "schema_version": 1,
        "target_id": "opaque-fixture-target",
        "deployed_source_commit": "b" * 64,
        "checks": [{"id": "owner-check", "state": "success", "evidence": {"detail": "observed"}}],
        "runtime_exclusions": {"rule_version": 1, "prefixes": ["docs/"], "paths": ["README.md"]},
        "runtime_policy_path": "release/runtime-policy.json",
    }


def test_public_contract_roundtrip_preserves_binding_evidence_and_failure() -> None:
    payload = response()
    payload["checks"].append({"id": "owner-second-check", "state": "failed", "evidence": {"exit": 1}})
    validated = validate_observation_response(payload, request=validate_observation_request(request()))
    assert NATIVE_DEPLOYMENT_CONTRACT_VERSION == 1
    assert decode_json(canonical_json(validated).encode()) == payload
    assert validated["checks"][1]["state"] == "failed"
    assert validated["deployed_source_commit"] != validated["accepted_source_commit"]
    validated["checks"][0]["evidence"]["detail"] = "changed copy"
    assert payload["checks"][0]["evidence"]["detail"] == "observed"


def test_canonical_json_is_order_independent_and_preserves_unicode() -> None:
    assert canonical_json({"z": [None, True, 1.25], "a": {"é": "✓"}}) == canonical_json(
        {"a": {"é": "✓"}, "z": [None, True, 1.25]}
    )
    assert "✓" in canonical_json({"a": "✓"})


@pytest.mark.parametrize(("key", "value"), [
    ("contract_version", 2), ("contract_version", True), ("contract_version", 1.0),
    ("operation", "choose_exclusions"), ("challenge", "a" * 31), ("challenge", "G" * 32),
    ("challenge", "00000000-0000-0000-0000-000000000000"),
    ("accepted_source_commit", "a" * 7), ("accepted_source_commit", "A" * 40),
    ("accepted_source_commit", "g" * 64), ("accepted_source_commit", "a" * 41),
    ("task_id", ""), ("project", " padded"), ("acceptance_id", None), ("project", "x\n"),
])
def test_request_rejects_invalid_binding_or_version(key: str, value: object) -> None:
    payload = request()
    payload[key] = value
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_request(payload)


@pytest.mark.parametrize("key", ["challenge", "task_id", "project", "acceptance_id", "accepted_source_commit"])
def test_response_must_match_each_request_binding(key: str) -> None:
    payload = response()
    payload[key] = "c" * (32 if key == "challenge" else 40) if key in (
        "challenge", "accepted_source_commit",
    ) else "different"
    with pytest.raises(NativeDeploymentContractError, match="match"):
        validate_observation_response(payload, request=request())


@pytest.mark.parametrize(("key", "value"), [
    ("schema_version", 2), ("schema_version", True), ("schema_version", "1"),
    ("target_id", ""), ("deployed_source_commit", "short"),
    ("checks", []), ("checks", {}), ("checks", [None]),
    ("checks", [{"id": "same", "state": "success", "evidence": {}}] * 2),
    ("checks", [{"id": "", "state": "success", "evidence": {}}]),
    ("checks", [{"id": "check", "state": "unknown", "evidence": {}}]),
    ("checks", [{"id": "check", "state": "failed", "evidence": []}]),
    ("runtime_exclusions", {"rule_version": 2, "prefixes": ["docs/"], "paths": []}),
    ("runtime_exclusions", {"rule_version": True, "prefixes": ["docs/"], "paths": []}),
    ("runtime_exclusions", {"rule_version": 1, "prefixes": [], "paths": []}),
    ("runtime_exclusions", {"rule_version": 1, "prefixes": "docs/", "paths": []}),
    ("runtime_exclusions", {"rule_version": 1, "prefixes": ["docs/", "docs/"], "paths": []}),
    ("runtime_exclusions", {"rule_version": 1, "prefixes": [], "paths": ["README.md", "README.md"]}),
])
def test_response_rejects_malformed_checks_versions_or_rules(key: str, value: object) -> None:
    payload = response()
    payload[key] = copy.deepcopy(value)
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_response(payload)


@pytest.mark.parametrize("path", [
    "", "/docs", "../docs", "docs/../file", "./docs", "docs//file", "docs\\file",
    "C:/docs", "docs/*", "docs/?", "docs/[ab]", " docs", "docs\x00file", "docs/",
])
def test_exclusions_reject_unsafe_exact_paths(path: str) -> None:
    payload = response()
    payload["runtime_exclusions"]["paths"] = [path]
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_response(payload)


@pytest.mark.parametrize("path", ["", "/policy.json", "../policy.json", "policy/*.json", "policy/", "./policy"])
def test_response_rejects_unsafe_runtime_policy_path(path: str) -> None:
    payload = response()
    payload["runtime_policy_path"] = path
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_response(payload)


@pytest.mark.parametrize("prefix", ["docs", "/", "../", "docs/../", "docs//", "docs*/", "./", ""])
def test_exclusions_reject_unsafe_prefixes(prefix: str) -> None:
    payload = response()
    payload["runtime_exclusions"]["prefixes"] = [prefix]
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_response(payload)


def test_paths_only_rule_and_full_sha256_request_are_supported() -> None:
    expected = request()
    expected["accepted_source_commit"] = "a" * 64
    payload = response()
    payload["accepted_source_commit"] = expected["accepted_source_commit"]
    payload["runtime_exclusions"]["prefixes"] = []
    assert validate_observation_response(payload, request=expected) == payload


@pytest.mark.parametrize("raw", [
    '{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"x":NaN}', '{"x":Infinity}',
    '{"x":-Infinity}', '{"x":1e999}', '[]', 'null', '{', b'\xff', '{"x":"\\ud800"}',
])
def test_decode_rejects_ambiguous_nonfinite_or_invalid_json(raw: str | bytes) -> None:
    with pytest.raises(NativeDeploymentContractError):
        decode_json(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), (1,), {1}, b"bytes", object()])
def test_observation_evidence_rejects_non_json_values(value: object) -> None:
    payload = response()
    payload["checks"][0]["evidence"]["value"] = value
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_response(payload)


def test_json_rejects_cycles_and_non_string_keys() -> None:
    cyclic = {}
    cyclic["self"] = cyclic
    for payload in (cyclic, {1: "value"}):
        with pytest.raises(NativeDeploymentContractError):
            canonical_json(payload)  # ty: ignore[invalid-argument-type]


def test_contracts_reject_extra_or_missing_fields_and_caller_selected_rules() -> None:
    for validator, fixture in (
        (validate_observation_request, request), (validate_observation_response, response),
    ):
        payload = fixture()
        payload["unexpected"] = True
        with pytest.raises(NativeDeploymentContractError):
            validator(payload)
        payload = fixture()
        del payload["challenge"]
        with pytest.raises(NativeDeploymentContractError):
            validator(payload)
    payload = request()
    payload["runtime_exclusions"] = response()["runtime_exclusions"]
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_request(payload)


def test_wire_parser_does_not_coerce_non_json_text_or_objects() -> None:
    for value in (None, {}, 1):
        with pytest.raises(NativeDeploymentContractError):
            decode_json(value)  # ty: ignore[invalid-argument-type]
    with pytest.raises(NativeDeploymentContractError):
        validate_observation_request(json.dumps(request()))  # ty: ignore[invalid-argument-type]


def test_failed_observation_can_retain_an_unknown_deployed_identity() -> None:
    payload = response()
    payload["deployed_source_commit"] = None
    payload["checks"][0]["state"] = "failed"
    payload["checks"][0]["evidence"] = {"error": "binary_observation_required"}
    assert validate_observation_response(payload, request=request()) == payload
    payload["checks"][0]["state"] = "success"
    with pytest.raises(NativeDeploymentContractError, match="require a deployed source"):
        validate_observation_response(payload)
