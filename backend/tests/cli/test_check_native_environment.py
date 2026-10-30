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


def test_node_modules_identity_ignores_vitest_results_cache(tmp_path: Path) -> None:
    modules = tmp_path / "node_modules"
    (modules / "dependency").mkdir(parents=True)
    (modules / "dependency/index.js").write_text("module.exports = 1\n")
    results = modules / ".vite/vitest/hash/results.json"
    results.parent.mkdir(parents=True)
    results.write_text('{"first": true}')
    optimized = modules / ".vite/deps/chunk.js"
    optimized.parent.mkdir(parents=True)
    optimized.write_text("export default 1\n")
    before = _environment_identity(tmp_path, modules)

    results.write_text('{"second": true}')
    assert _environment_identity(tmp_path, modules) == before

    optimized.write_text("export default 2\n")
    assert _environment_identity(tmp_path, modules) != before


def _virtualenv(root: Path) -> tuple[Path, dict[str, Path]]:
    environment = root / ".venv"
    site = environment / "lib/python3.13/site-packages"
    (site / "dependency").mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (site / "dependency/__init__.py").write_text("VERSION = 1\n")
    (site / "dependency/__pycache__").mkdir()
    (site / "dependency/__pycache__/__init__.cpython-313.pyc").write_bytes(b"first compile")
    record = site / "dependency-1.0.dist-info/RECORD"
    record.parent.mkdir()
    record.write_text("dependency/__init__.py,sha256=one,12\n")
    return environment, {"cache": site / "dependency/__pycache__/__init__.cpython-313.pyc",
                         "installed": site / "dependency/__init__.py", "manifest": record,
                         "unclaimed": site / "hand_placed.py"}


def _node_modules(root: Path) -> tuple[Path, dict[str, Path]]:
    store = root / "node_modules/.pnpm"
    package = store / "dependency@1.0.0/node_modules/dependency"
    package.mkdir(parents=True)
    (package / "index.js").write_text("module.exports = 1\n")
    (store / "lock.yaml").write_text("dependency: 1.0.0\n")
    modules = root / "frontend/node_modules"
    modules.mkdir(parents=True)
    (modules / "dependency").symlink_to(package, target_is_directory=True)
    results = modules / ".vite/vitest/results.json"
    results.parent.mkdir(parents=True)
    results.write_text("{}")
    return modules, {"cache": results, "installed": package / "index.js", "manifest": store / "lock.yaml",
                     "unclaimed": modules / "dependency"}


@pytest.mark.parametrize("build", [_virtualenv, _node_modules])
def test_prepared_identity_binds_installed_manifests_not_caches(tmp_path: Path, build) -> None:
    from cli.commands.check_native import _prepared_identity

    environment, files = build(tmp_path)
    before = _prepared_identity(tmp_path, environment)
    assert before["state"] == "present"

    files["cache"].write_bytes(b"rewritten by a test run")
    files["installed"].write_text("same installed version, rewritten bytes\n")
    assert _prepared_identity(tmp_path, environment) == before

    files["manifest"].write_text(files["manifest"].read_text() + "changed install\n")
    changed = _prepared_identity(tmp_path, environment)
    assert changed != before

    if files["unclaimed"].is_symlink():
        relinked = tmp_path / "node_modules/.pnpm/dependency@2.0.0/node_modules/dependency"
        relinked.mkdir(parents=True)
        files["unclaimed"].unlink()
        files["unclaimed"].symlink_to(relinked, target_is_directory=True)
    else:
        files["unclaimed"].write_text("hand placed module\n")
    assert _prepared_identity(tmp_path, environment) != changed


def test_prepared_source_package_ignores_bytecode_written_by_the_run(tmp_path: Path) -> None:
    """A managed input used from its checkout (aico's uilint) compiles on first import mid-acceptance."""
    from cli.commands.check_native import _prepared_identity

    package = tmp_path / "uilint"
    package.mkdir()
    (package / "scope.py").write_text("X = 1\n")
    before = _prepared_identity(tmp_path, package)
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "scope.cpython-313.pyc").write_bytes(b"bytecode")
    assert _prepared_identity(tmp_path, package) == before
    (package / "scope.py").write_text("X = 2\n")
    assert _prepared_identity(tmp_path, package) != before
