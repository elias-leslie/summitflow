"""Check details survive concurrent invocations instead of overwriting evidence."""

from pathlib import Path

from cli.commands.check_artifacts import write_check_details


def test_each_check_invocation_retains_unique_details_and_updates_latest(tmp_path: Path) -> None:
    first = write_check_details(tmp_path, "pytest", "first failure\n")
    second = write_check_details(tmp_path, "pytest", "second result\n")

    assert first != second
    assert first.read_text() == "first failure\n"
    assert second.read_text() == "second result\n"
    latest = tmp_path / ".dev-tools" / "pytest-details.txt"
    assert latest.is_symlink()
    assert latest.resolve() == second
    assert latest.read_text() == "second result\n"
