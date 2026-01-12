"""Seed base design standards from JSON file.

This module loads the base design standard from a JSON file and populates
the database with the standard and its rules.
"""

import json
import logging
from pathlib import Path
from typing import Any

from . import design_standards

logger = logging.getLogger(__name__)

BASE_STANDARD_FILE = Path(__file__).parent / "base_design_standard.json"


def load_base_standard_json() -> dict[str, Any]:
    """Load base standard from JSON file."""
    if not BASE_STANDARD_FILE.exists():
        raise FileNotFoundError(f"Base standard file not found: {BASE_STANDARD_FILE}")

    with open(BASE_STANDARD_FILE) as f:
        data: dict[str, Any] = json.load(f)
        return data


def seed_base_standard(force: bool = False) -> dict[str, Any] | None:
    """Seed the base design standard if it doesn't exist.

    Args:
        force: If True, delete existing base standard and re-seed

    Returns:
        The created/existing base standard, or None if skipped
    """
    existing = design_standards.get_base_standard()

    if existing and not force:
        logger.info("Base standard already exists (id=%s), skipping seed", existing["id"])
        return existing

    if existing and force:
        logger.info("Force mode: deleting existing base standard (id=%s)", existing["id"])
        design_standards.delete_standard(existing["id"])

    data = load_base_standard_json()

    standard = design_standards.create_standard(
        name=data["name"],
        description=data["description"],
        is_base=True,
    )
    logger.info("Created base standard: %s (id=%s)", standard["name"], standard["id"])

    categories = data.get("categories", {})
    rule_count = 0

    for category, category_data in categories.items():
        rules = category_data.get("rules", [])
        for rule in rules:
            design_standards.create_rule(
                standard_id=standard["id"],
                category=category,
                rule_id=rule["rule_id"],
                name=rule["name"],
                requirements=rule.get("requirements", {}),
            )
            rule_count += 1

    logger.info("Created %d rules across %d categories", rule_count, len(categories))
    return standard


def ensure_base_standard() -> dict[str, Any]:
    """Ensure base standard exists, creating if needed.

    This is safe to call multiple times - it will only create if missing.

    Returns:
        The base standard dict
    """
    standard = seed_base_standard(force=False)
    if not standard:
        standard = design_standards.get_base_standard()
    if not standard:
        raise RuntimeError("Failed to create or retrieve base standard")
    return standard


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    force = "--force" in sys.argv
    result = seed_base_standard(force=force)

    if result:
        print(f"Base standard: {result['name']} (id={result['id']})")
    else:
        print("No changes made")
