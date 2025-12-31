"""Test commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_error, output_json, output_success, output_tests

app = typer.Typer(help="Test management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command("list")
def list_tests(
    test_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List tests for the project.

    Examples:
        st test list
        st test list -t pytest
        st test list --json
    """
    client = STClient()

    try:
        tests = client.list_tests(test_type=test_type)
    except APIError as e:
        _handle_api_error(e)
        return

    output_tests(tests, json_output)


@app.command("import")
def import_tests(
    framework: Annotated[str, typer.Option("-f", "--from")] = "pytest",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Import tests from a framework.

    Examples:
        st test import --from pytest
        st test import --from mypy
        st test import --from ruff
    """
    client = STClient()

    try:
        result = client.import_tests(framework)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        imported = result.get("imported_count", 0)
        output_success(f"Imported {imported} tests from {framework}")
