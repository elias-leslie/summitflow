from pathlib import Path
from subprocess import CompletedProcess

import pytest

from cli.commands.check_native import _environment_identity
from cli.lib import acceptance


@pytest.mark.parametrize("file_count", [1, 128])
def test_selected_environment_resolves_ancestors_once(tmp_path: Path, monkeypatch, file_count: int) -> None:
    environment = tmp_path / "prepared"
    environment.mkdir()
    for index in range(file_count):
        (environment / f"dependency_{index}.py").write_text("prepared dependency\n")
    monkeypatch.setattr(acceptance, "_source_tree_entries", lambda *_: {"tracked.py": ("100644", "blob")})
    monkeypatch.setattr(acceptance, "projected_source_modes", lambda *_: {"tracked.py": 0o644})
    resolve = Path.resolve
    resolutions = []

    def counted_resolve(path, *args, **kwargs):
        resolutions.append(path)
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted_resolve)

    result = _environment_identity(tmp_path, environment, commit="selected")

    assert result["state"] == "present"
    assert result["file_count"] == file_count
    assert resolutions == [tmp_path, environment]


def test_selected_environment_preserves_symlink_confinement_and_consumed_inputs(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    package = root / "packages/fixture"
    package.mkdir(parents=True)
    source = package / "source.py"
    source.write_text("host workspace source\n")
    dependency = package / "node_modules/dependency.py"
    dependency.parent.mkdir()
    dependency.write_text("consumed dependency\n")
    outside = tmp_path / "project-other/packages/fixture"
    outside.mkdir(parents=True)
    external = outside / "source.py"
    external.write_text("external dependency\n")
    environment = root / "prepared"
    environment.mkdir()
    (environment / "workspace").symlink_to(package, target_is_directory=True)
    (environment / "external").symlink_to(outside, target_is_directory=True)
    (environment / "workspace.py").symlink_to(source)
    (environment / "external.py").symlink_to(external)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    relative = "packages/fixture/source.py"
    monkeypatch.setattr(acceptance, "_source_tree_entries", lambda *_: {relative: ("100644", "blob")})
    monkeypatch.setattr(acceptance, "projected_source_modes", lambda *_: {relative: 0o644})
    source_reads = []

    def selected_source(repo, args, *, text):
        source_reads.append(args)
        return CompletedProcess(args, 0, b"accepted source\n", b"")

    monkeypatch.setattr(acceptance, "_git", selected_source)
    before = _environment_identity(alias, alias / "prepared", commit="selected")
    assert before["state"] == "present"
    assert source_reads == [["show", f"selected:{relative}"]] * 2

    source.write_text("unaccepted workspace edit\n")
    (package / "dist").mkdir()
    (package / "dist/ignored.py").write_text("unmounted output\n")
    assert _environment_identity(alias, alias / "prepared", commit="selected") == before

    dependency.write_text("changed consumed dependency\n")
    changed = _environment_identity(alias, alias / "prepared", commit="selected")
    assert changed != before
    external.write_text("changed external dependency\n")
    assert _environment_identity(alias, alias / "prepared", commit="selected") != changed
