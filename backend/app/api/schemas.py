"""Schemas API - JSON Schema endpoints for validation.

Provides JSON schemas that can be used by CLI tools for validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()

# Schema directory (relative to this file)
SCHEMA_DIR = Path(__file__).parent.parent / "schemas"

# Available schemas
AVAILABLE_SCHEMAS = {
    "plan": "plan.schema.json",
}


@router.get("/schemas/{schema_name}")
async def get_schema(schema_name: str) -> dict[str, Any]:
    """Get a JSON schema by name.

    Args:
        schema_name: Schema name (e.g., "plan")

    Returns:
        JSON schema object

    Raises:
        HTTPException(404): If schema not found
    """
    if schema_name not in AVAILABLE_SCHEMAS:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_name}' not found. Available: {list(AVAILABLE_SCHEMAS.keys())}",
        )

    schema_file = SCHEMA_DIR / AVAILABLE_SCHEMAS[schema_name]
    if not schema_file.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Schema file not found: {schema_file}",
        )

    with open(schema_file) as f:
        return dict(json.load(f))


@router.get("/schemas")
async def list_schemas() -> dict[str, list[str]]:
    """List available schemas.

    Returns:
        Dict with available schema names
    """
    return {"schemas": list(AVAILABLE_SCHEMAS.keys())}
