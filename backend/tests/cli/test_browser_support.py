from __future__ import annotations

from cli.lib.browser_support import parse_agent_console


def test_parse_agent_console_collects_initial_errors_and_multiline_warnings() -> None:
    errors, warnings = parse_agent_console(
        """[error] Uncaught Error: broken
[warning] The chart has invalid dimensions,
       add a minWidth to the container.
[log] ignored
"""
    )

    assert errors == ["[error] Uncaught Error: broken"]
    assert warnings == [
        "[warning] The chart has invalid dimensions,\nadd a minWidth to the container."
    ]


def test_parse_agent_console_ignores_daemon_noise() -> None:
    errors, warnings = parse_agent_console(
        "⚠ --profile ignored: daemon already running\nregular output"
    )

    assert errors == []
    assert warnings == []
