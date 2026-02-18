"""Design standards validation logic.

Validates UI elements against design rules with support for:
- Exact value matching
- Range validation (min/max)
- Allowed values enumeration
"""

from typing import Any


def _build_violation(
    rule: dict[str, Any],
    req_key: str,
    req_value: dict[str, Any],
    expected: Any,
    actual: Any,
) -> dict[str, Any]:
    """Build a violation dict from rule context and mismatch details."""
    return {
        "rule_id": rule["rule_id"],
        "rule_name": rule["name"],
        "category": rule["category"],
        "requirement": req_key,
        "expected": expected,
        "actual": actual,
        "severity": req_value.get("severity", "warning"),
    }


def _check_exact(
    rule: dict[str, Any],
    req_key: str,
    req_value: dict[str, Any],
    actual: Any,
) -> list[dict[str, Any]]:
    """Return violations if actual does not match the required exact value."""
    if actual != req_value["exact"]:
        return [_build_violation(rule, req_key, req_value, req_value["exact"], actual)]
    return []


def _check_range(
    rule: dict[str, Any],
    req_key: str,
    req_value: dict[str, Any],
    actual: Any,
) -> list[dict[str, Any]]:
    """Return violations if actual falls outside the required min/max range."""
    try:
        val = float(actual) if not isinstance(actual, int | float) else actual
    except (ValueError, TypeError):
        return []

    violations = []
    if "min" in req_value and val < req_value["min"]:
        violations.append(
            _build_violation(rule, req_key, req_value, f">= {req_value['min']}", actual)
        )
    if "max" in req_value and val > req_value["max"]:
        violations.append(
            _build_violation(rule, req_key, req_value, f"<= {req_value['max']}", actual)
        )
    return violations


def _check_allowed(
    rule: dict[str, Any],
    req_key: str,
    req_value: dict[str, Any],
    actual: Any,
) -> list[dict[str, Any]]:
    """Return violations if actual is not in the list of allowed values."""
    if actual not in req_value["allowed"]:
        return [
            _build_violation(
                rule, req_key, req_value, f"one of {req_value['allowed']}", actual
            )
        ]
    return []


def _check_requirement(
    rule: dict[str, Any],
    req_key: str,
    req_value: Any,
    actual: Any,
) -> list[dict[str, Any]]:
    """Dispatch to the appropriate check based on req_value structure."""
    if not isinstance(req_value, dict):
        return []

    if "exact" in req_value:
        return _check_exact(rule, req_key, req_value, actual)
    if "min" in req_value or "max" in req_value:
        return _check_range(rule, req_key, req_value, actual)
    if "allowed" in req_value:
        return _check_allowed(rule, req_key, req_value, actual)
    return []


def validate_against_rules(
    rules: list[dict[str, Any]],
    element_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate element data against design rules.

    Args:
        rules: List of design rules to validate against
        element_data: Element properties to validate

    Returns:
        List of violations with rule details
    """
    violations = []

    for rule in rules:
        requirements = rule.get("requirements", {})
        for req_key, req_value in requirements.items():
            actual = element_data.get(req_key)
            if actual is None:
                continue
            violations.extend(_check_requirement(rule, req_key, req_value, actual))

    return violations
