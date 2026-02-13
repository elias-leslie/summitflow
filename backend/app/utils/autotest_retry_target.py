from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any


def transform_record(data: dict[str, Any]) -> dict[str, Any]:
    """
    Transforms and validates a record.

    - lowercases email
    - converts age str to int
    - adds processed_at ISO timestamp (UTC)
    - validates email has @ and domain with TLD
    - raises ValueError mentioning the field name for invalid input
    - preserves extra fields
    """
    # Create a copy to preserve extra fields and avoid side effects
    result = data.copy()

    # Validate name
    name = result.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        raise ValueError("Field 'name' is required and cannot be empty")

    # Validate and transform email
    email = result.get("email")
    if email is None:
        raise ValueError("Field 'email' is missing")

    email_str = str(email).lower()
    # Regex requiring @ and at least one dot in the domain part (TLD)
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email_str):
        raise ValueError(f"Field 'email' is invalid: {email_str}")

    result["email"] = email_str

    # Validate and transform age
    age = result.get("age")
    if age is None:
        raise ValueError("Field 'age' is missing")

    try:
        result["age"] = int(age)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Field 'age' must be numeric, got: {age}") from e

    # Add processed_at
    result["processed_at"] = datetime.now(UTC).isoformat()

    return result
