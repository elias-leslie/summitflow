"""Design standards validation logic.

Validates UI elements against design rules with support for:
- Exact value matching
- Range validation (min/max)
- Allowed values enumeration
"""

from typing import Any


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

            # Check for exact match requirement
            if isinstance(req_value, dict):
                if "exact" in req_value and actual != req_value["exact"]:
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule["name"],
                            "category": rule["category"],
                            "requirement": req_key,
                            "expected": req_value["exact"],
                            "actual": actual,
                            "severity": req_value.get("severity", "warning"),
                        }
                    )
                # Check for range requirement
                elif "min" in req_value or "max" in req_value:
                    try:
                        val = float(actual) if not isinstance(actual, int | float) else actual
                        if "min" in req_value and val < req_value["min"]:
                            violations.append(
                                {
                                    "rule_id": rule["rule_id"],
                                    "rule_name": rule["name"],
                                    "category": rule["category"],
                                    "requirement": req_key,
                                    "expected": f">= {req_value['min']}",
                                    "actual": actual,
                                    "severity": req_value.get("severity", "warning"),
                                }
                            )
                        if "max" in req_value and val > req_value["max"]:
                            violations.append(
                                {
                                    "rule_id": rule["rule_id"],
                                    "rule_name": rule["name"],
                                    "category": rule["category"],
                                    "requirement": req_key,
                                    "expected": f"<= {req_value['max']}",
                                    "actual": actual,
                                    "severity": req_value.get("severity", "warning"),
                                }
                            )
                    except (ValueError, TypeError):
                        pass
                # Check for allowed values
                elif "allowed" in req_value and actual not in req_value["allowed"]:
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule["name"],
                            "category": rule["category"],
                            "requirement": req_key,
                            "expected": f"one of {req_value['allowed']}",
                            "actual": actual,
                            "severity": req_value.get("severity", "warning"),
                        }
                    )

    return violations
