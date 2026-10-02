"""Versioned observation wire contracts for trusted deployment observers.

Validation checks structure and request binding, not deployment success or
receipt authority. ST owns source verification and canonical receipt issuance.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

NATIVE_DEPLOYMENT_CONTRACT_VERSION = 1
_BINDING_KEYS = {
    "challenge", "task_id", "project", "accepted_source_commit", "acceptance_id",
}
_REQUEST_KEYS = _BINDING_KEYS | {"contract_version", "operation"}
_RESPONSE_KEYS = _BINDING_KEYS | {
    "schema_version", "target_id", "deployed_source_commit", "checks", "runtime_exclusions",
    "runtime_policy_path",
}


class NativeDeploymentContractError(ValueError):
    """An observation does not satisfy the supported wire contract."""


def _json_value(value: Any, active: set[int]) -> Any:
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise NativeDeploymentContractError("JSON strings must be valid UTF-8") from exc
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping) or type(value) is list:
        identity = id(value)
        if identity in active:
            raise NativeDeploymentContractError("JSON must not contain cycles")
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                if any(not isinstance(key, str) for key in value):
                    raise NativeDeploymentContractError("JSON object keys must be strings")
                return {_json_value(key, active): _json_value(item, active) for key, item in value.items()}
            return [_json_value(item, active) for item in value]
        finally:
            active.remove(identity)
    raise NativeDeploymentContractError("Observations must contain only finite JSON values")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeDeploymentContractError(f"{label} must be a JSON object")
    try:
        return _json_value(value, set())
    except RecursionError as exc:
        raise NativeDeploymentContractError("JSON nesting is too deep") from exc


def canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize an observation deterministically, rejecting non-JSON values."""
    return json.dumps(_object(value, "payload"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeDeploymentContractError("JSON object contains duplicate keys")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> Any:
    raise NativeDeploymentContractError("JSON must contain only finite numbers")


def decode_json(raw: str | bytes) -> dict[str, Any]:
    """Decode one JSON object, rejecting duplicate keys at every nesting level."""
    if not isinstance(raw, (str, bytes)):
        raise NativeDeploymentContractError("payload must be JSON text or UTF-8 bytes")
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except NativeDeploymentContractError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise NativeDeploymentContractError("payload must contain valid JSON") from exc
    return _object(value, "payload")


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise NativeDeploymentContractError(f"{label} must contain exactly {sorted(expected)}")


def _version(value: Any, label: str) -> None:
    if type(value) is not int or value != NATIVE_DEPLOYMENT_CONTRACT_VERSION:
        raise NativeDeploymentContractError(f"unsupported {label}")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise NativeDeploymentContractError(f"{label} must be a non-empty unpadded string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise NativeDeploymentContractError(f"{label} must not contain control characters")
    return value


def _commit(value: Any, label: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise NativeDeploymentContractError(f"{label} must be a full lowercase Git commit identity")


def _binding(value: dict[str, Any]) -> None:
    challenge = value["challenge"]
    if not isinstance(challenge, str) or re.fullmatch(r"[0-9a-f]{32}", challenge) is None:
        raise NativeDeploymentContractError("challenge must be a lowercase UUID hex identity")
    for key in ("task_id", "project", "acceptance_id"):
        _string(value[key], key)
    _commit(value["accepted_source_commit"], "accepted_source_commit")


def validate_observation_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the fixed observer operation; callers cannot select exclusions."""
    result = _object(value, "request")
    _keys(result, _REQUEST_KEYS, "request")
    _version(result["contract_version"], "contract_version")
    if result["operation"] != "observe_deployment":
        raise NativeDeploymentContractError("unsupported observation operation")
    _binding(result)
    return result


def _relative_path(value: Any, *, prefix: bool) -> str:
    label = "exclusion prefix" if prefix else "exclusion path"
    path = _string(value, label)
    if path.endswith("/") != prefix:
        raise NativeDeploymentContractError(f"{label} has an invalid trailing slash")
    components = (path[:-1] if prefix else path).split("/")
    if any(part in ("", ".", "..") for part in components) or any(
        character in path for character in "\\:*?[]"
    ):
        raise NativeDeploymentContractError(f"{label} must be a literal relative POSIX path")
    return path


def _exclusions(value: Any) -> None:
    if not isinstance(value, dict):
        raise NativeDeploymentContractError("runtime_exclusions must be a JSON object")
    _keys(value, {"rule_version", "prefixes", "paths"}, "runtime_exclusions")
    _version(value["rule_version"], "runtime exclusion rule_version")
    for key in ("prefixes", "paths"):
        entries = value[key]
        if not isinstance(entries, list):
            raise NativeDeploymentContractError(f"runtime_exclusions.{key} must be a list")
        normalized = [_relative_path(entry, prefix=key == "prefixes") for entry in entries]
        if len(set(normalized)) != len(normalized):
            raise NativeDeploymentContractError(f"runtime_exclusions.{key} must not contain duplicates")
    if not value["prefixes"] and not value["paths"]:
        raise NativeDeploymentContractError("runtime_exclusions must not be empty")


def validate_observation_response(
    value: Mapping[str, Any], *, request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate observations and optionally enforce exact request binding.

    Check identifiers belong to the observer's domain. Failed checks remain
    valid observations and must be evaluated by ST before issuing a receipt.
    """
    result = _object(value, "response")
    _keys(result, _RESPONSE_KEYS, "response")
    _version(result["schema_version"], "schema_version")
    _binding(result)
    if request is not None:
        expected = validate_observation_request(request)
        if any(result[key] != expected[key] for key in _BINDING_KEYS):
            raise NativeDeploymentContractError("response does not match its observation request")
    _string(result["target_id"], "target_id")
    if result["deployed_source_commit"] is not None:
        _commit(result["deployed_source_commit"], "deployed_source_commit")
    _relative_path(result["runtime_policy_path"], prefix=False)
    checks = result["checks"]
    if not isinstance(checks, list) or not checks:
        raise NativeDeploymentContractError("checks must be a non-empty list")
    identifiers: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            raise NativeDeploymentContractError("each check must be a JSON object")
        _keys(check, {"id", "state", "evidence"}, "check")
        identifier = _string(check["id"], "check.id")
        if identifier in identifiers:
            raise NativeDeploymentContractError("check identifiers must be unique")
        identifiers.add(identifier)
        if check["state"] not in ("success", "failed"):
            raise NativeDeploymentContractError("check.state must be success or failed")
        if not isinstance(check["evidence"], dict):
            raise NativeDeploymentContractError("check.evidence must be a JSON object")
    _exclusions(result["runtime_exclusions"])
    if result["deployed_source_commit"] is None and all(check["state"] == "success" for check in checks):
        raise NativeDeploymentContractError("successful observations require a deployed source commit")
    return result
