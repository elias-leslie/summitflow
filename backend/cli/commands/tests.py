"""Test commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json, output_success, output_tests

app = typer.Typer(help="Test management commands")


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
        handle_api_error(e)
        return

    output_tests(tests, json_output)


@app.command("link")
def link_test(
    capability_id: str,
    criterion_id: str,
    test_id: Annotated[int, typer.Argument()],
    primary: Annotated[bool, typer.Option("--primary")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Link a test to a criterion.

    Examples:
        st test link user-login ac-001 42
        st test link user-login ac-001 42 --primary
    """
    client = STClient()

    try:
        result = client.link_test_to_criterion(
            capability_id=capability_id,
            criterion_id=criterion_id,
            test_id=test_id,
            is_primary=primary,
        )
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success(f"Linked test {test_id} to criterion {criterion_id}")


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
        handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        imported = result.get("imported_count", 0)
        output_success(f"Imported {imported} tests from {framework}")
