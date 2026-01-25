"""Test commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json, output_tests

app = typer.Typer(help="Test management commands")


@app.command("list")
def list_tests(
    test_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """List tests for the project.

    Examples:
        st test list
        st test list -t pytest
        st test list --limit 10
    """
    client = STClient()

    try:
        tests = client.list_tests(test_type=test_type, limit=limit)
    except APIError as e:
        handle_api_error(e)
        return

    output_tests(tests)


@app.command("import")
def import_tests(
    framework: Annotated[str, typer.Option("-f", "--from")] = "pytest",
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
        handle_api_error(e)
        return

    output_json(result)
