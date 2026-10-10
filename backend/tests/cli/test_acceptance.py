from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.lib import acceptance
from cli.lib.task_completion_adapter import AcceptedTaskWork
from cli.main import app


def test_acceptance_plan_survives_equivalent_release_relocation(tmp_path: Path, monkeypatch) -> None:
    from cli import tool_registry

    checkout = tmp_path / "checkout"
    for relative in ("backend/cli/commands/check.py", "backend/cli/lib/acceptance.py",
                     "backend/app/utils/heavy_work.py", "backend/app/utils/safe_subprocess.py",
                     "backend/cli/main.py", "backend/cli/tool_registry.py", "scripts/lib/tool-registry.json"):
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    scanner = checkout / "scanner"
    scanner.write_text("same scanner bytes")
    launcher = checkout / "st"
    launcher.write_text("checkout shell facade")
    monkeypatch.setattr(acceptance, "__file__", str(checkout / "backend/cli/lib/acceptance.py"))
    monkeypatch.setattr(tool_registry, "tool_registry_path", lambda: checkout / "scripts/lib/tool-registry.json")
    monkeypatch.setattr(acceptance.shutil, "which", lambda name: str(launcher if name == "st" else scanner))
    before = acceptance._acceptance_plan()
    release = tmp_path / "release"
    shutil.copytree(checkout, release, copy_function=shutil.copyfile)
    (release / "st").write_text("release Python facade for the same cli.main:app")
    monkeypatch.setattr(acceptance, "__file__", str(release / "backend/cli/lib/acceptance.py"))
    monkeypatch.setattr(tool_registry, "tool_registry_path", lambda: release / "scripts/lib/tool-registry.json")
    monkeypatch.setattr(acceptance.shutil, "which", lambda name: str(release / ("st" if name == "st" else "scanner")))
    assert acceptance._acceptance_plan() == before
    (release / "backend/cli/commands/check.py").write_text("changed gate implementation")
    assert acceptance._acceptance_plan()["fingerprint"] != before["fingerprint"]


def test_acceptance_plan_detects_changed_security_tool_bytes(tmp_path: Path, monkeypatch) -> None:
    scanner = tmp_path / "scanner"
    scanner.write_text("original scanner")
    monkeypatch.setattr(acceptance.shutil, "which", lambda _name: str(scanner))
    before = acceptance._acceptance_plan()
    scanner.write_text("changed scanner")
    assert acceptance._acceptance_plan()["fingerprint"] != before["fingerprint"]


@pytest.mark.parametrize("name", ["heavy_work.py", "safe_subprocess.py"])
def test_acceptance_plan_binds_shared_gate_support_bytes(tmp_path: Path, monkeypatch, name: str) -> None:
    from cli import tool_registry

    backend = tmp_path / "backend"
    support = backend / "app" / "utils" / name
    support.parent.mkdir(parents=True)
    support.write_text("original shared gate support")
    monkeypatch.setattr(acceptance, "__file__", str(backend / "cli" / "lib" / "acceptance.py"))
    monkeypatch.setattr(tool_registry, "tool_registry_path", lambda: tmp_path / "scripts" / "lib" / "tool-registry.json")
    before = acceptance._acceptance_plan()
    support.write_text("changed shared gate support")
    assert acceptance._acceptance_plan()["fingerprint"] != before["fingerprint"]


def test_acceptance_plan_ignores_transient_heavy_admission_identity(monkeypatch) -> None:
    monkeypatch.setenv("ST_HEAVY_LEASE", "first-process-fixture")
    before = acceptance._acceptance_plan()
    monkeypatch.setenv("ST_HEAVY_LEASE", "another-process-fixture")
    assert acceptance._acceptance_plan() == before


def test_acceptance_runner_binds_canonical_implementation_not_path(tmp_path: Path, monkeypatch) -> None:
    launcher = tmp_path / "st"
    launcher.write_text("unrelated PATH launcher")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", "original-target-import-path")
    invoke = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(acceptance.subprocess, "run", invoke)
    acceptance._run(["st", "check", "--check"], tmp_path)
    args, kwargs = invoke.call_args
    assert args[0][:3] == [acceptance.sys.executable, "-P", "-c"]
    assert args[0][4:] == [str(Path(acceptance.__file__).resolve().parents[2]), "check", "--check"]
    assert kwargs["env"]["PYTHONPATH"] == "original-target-import-path"
    assert acceptance.os.environ["PYTHONPATH"] == "original-target-import-path"
    assert kwargs["cwd"] == tmp_path


def test_acceptance_binding_does_not_change_target_child_import_environment(tmp_path: Path, monkeypatch) -> None:
    backend = tmp_path / "bound-backend"
    package = backend / "cli"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text(
        "def app():\n"
        "    import subprocess, sys\n"
        "    print('bound canonical CLI')\n"
        "    print(subprocess.check_output([sys.executable, '-P', '-c', "
        "\"import os; print(os.environ.get('PYTHONPATH'))\"], text=True).strip())\n"
    )
    target = tmp_path / "target-project"
    (target / "cli").mkdir(parents=True)
    (target / "cli" / "__init__.py").write_text("raise RuntimeError('wrong target CLI')")
    monkeypatch.setattr(acceptance, "__file__", str(package / "lib/acceptance.py"))
    monkeypatch.setenv("PYTHONPATH", "original-target-import-path")
    result = acceptance._run(["st", "check", "--check"], target)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["bound canonical CLI", "original-target-import-path"]


@pytest.mark.parametrize("name", ["DATABASE_URL", "DATABASE_ADMIN_URL", "POSTGRES_ADMIN_URL", "REDIS_URL", "TEST_DATABASE_URL"])
def test_exporting_same_bound_home_configuration_preserves_gate_identity(tmp_path: Path, monkeypatch, name: str) -> None:
    shared = tmp_path / "shared-home"
    shared.mkdir()
    monkeypatch.setattr(Path, "home", lambda: shared)
    monkeypatch.delenv(name, raising=False)
    (shared / ".env.local").write_text(f"{name}=fixture-literal-value\n")
    before = acceptance._local_gate_inputs(tmp_path)
    monkeypatch.setenv(name, "fixture-literal-value")
    assert acceptance._local_gate_inputs(tmp_path) == before
    monkeypatch.setenv(name, "different-explicit-override")
    assert acceptance._local_gate_inputs(tmp_path) != before
    monkeypatch.delenv(name)
    (shared / ".env.local").write_text(f"{name}=changed-file-value\n")
    assert acceptance._local_gate_inputs(tmp_path) != before


def test_same_home_export_removed_from_actual_gate_child_only(tmp_path: Path, monkeypatch) -> None:
    shared = tmp_path / "shared-home"
    shared.mkdir()
    (shared / ".env.local").write_text("DATABASE_URL=fixture-literal-value\n")
    monkeypatch.setattr(Path, "home", lambda: shared)
    monkeypatch.setenv("DATABASE_URL", "fixture-literal-value")
    backend = tmp_path / "bound-backend"
    package = backend / "cli"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text("def app():\n    import os\n    print(os.environ.get('DATABASE_URL', 'unset'))\n")
    monkeypatch.setattr(acceptance, "__file__", str(package / "lib/acceptance.py"))
    result = acceptance._run(["st", "check", "--check"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "unset"
    assert acceptance.os.environ["DATABASE_URL"] == "fixture-literal-value"
    monkeypatch.setenv("DATABASE_URL", "different-explicit-override")
    assert acceptance._run(["st", "check", "--check"], tmp_path).stdout.strip() == "different-explicit-override"


@pytest.mark.parametrize("content", ["DATABASE_URL=${OTHER_VALUE}\n",
                                     "DATABASE_URL=one\nDATABASE_URL=two\n",
                                     "DATABASE_URL='unfinished\n", "DATABASE_URL\n"])
def test_ambiguous_shared_configuration_is_not_normalized(tmp_path: Path, monkeypatch, content: str) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".env.local").write_text(content)
    monkeypatch.setenv("DATABASE_URL", "two" if "=two" in content else "${OTHER_VALUE}")
    assert acceptance._canonical_gate_environment()["DATABASE_URL"] == acceptance.os.environ["DATABASE_URL"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, local_gate_tools: None) -> Path:
    git(tmp_path, "init", "-q", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_source_inspection_preserves_stale_index_bytes(repo: Path) -> None:
    import os

    index = repo / ".git/index"
    before = index.read_bytes()
    source = repo / "pyproject.toml"
    info = source.stat()
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    assert acceptance.source_identity(repo)["clean"] is True
    assert index.read_bytes() == before


def successful_runner(calls: list[list[str]]):
    def run(command: list[str], cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    return run


@pytest.mark.parametrize("detail", [
    "BIOME:SKIP:biome:tool_not_installed\nGITLEAKS:OK:0",
    "\n".join([
        "ARCH:SKIP:architecture:no_changed_paths",
        "IDENTITY:OK:slopminer",
        "LINT:SKIP:ruff:no_changed_paths",
        "TYPES:SKIP:types:no_changed_paths",
        "TEST:SKIP:pytest:no_relevant_changed_paths",
        "BIOME:biome:start",
        "BIOME:SKIP:biome:tool_not_installed",
        "TSC:SKIP:tsc:no_relevant_changed_paths",
        "GITLEAKS:OK:0|details:.dev-tools/security-gitleaks-18dca56742c0534a-3090135-0c0ac543-details.txt|hint:3:43PM INF no leaks found",
    ]),
], ids=["minimal", "slopminer-receipt"])
def test_task_acceptance_allows_undeclared_biome_for_docs_and_profiles(repo: Path, detail: str) -> None:
    (repo / "guide.md").write_text("Updated guide\n")
    (repo / "profile.json").write_text('{"rules": []}\n')
    git(repo, "add", "guide.md", "profile.json")
    git(repo, "commit", "-qm", "docs and profile")

    def runner(command: list[str], cwd: Path):
        assert command == ["st", "check", "--quick", "--changed-only"]
        return subprocess.CompletedProcess(command, 0, detail, "")

    result = acceptance.accept_revision(
        repo, sha="HEAD", coverage="task", scope=("guide.md", "profile.json"), runner=runner
    )
    assert result["state"] == "success"
    assert result["coverage"] == "task"
    assert result["checks"][0]["evidence"]["state"] == "pass"
    assert acceptance.validate_acceptance_receipt(repo, result)["acceptance_id"] == result["acceptance_id"]


@pytest.mark.parametrize(("path", "content"), [
    ("biome.json", "{}\n"),
    ("frontend/biome.jsonc", "{}\n"),
    ("package.json", '{"devDependencies":{"@biomejs/biome":"2"}}\n'),
    ("frontend/package.json", '{"scripts":{"lint":"biome check ."}}\n'),
    ("package.json", "malformed manifest\n"),
    (".st-check.toml", '[paths]\nbiome="missing/bin"\n'),
])
def test_task_acceptance_blocks_declared_missing_biome(repo: Path, path: str, content: str) -> None:
    declaration = repo / path
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text(content)
    git(repo, "add", path)
    git(repo, "commit", "-qm", "declare required formatter")
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(
            repo, sha="HEAD", coverage="task", scope=("app.py",),
            runner=lambda command, _: subprocess.CompletedProcess(
                command, 0, "BIOME:SKIP:biome:tool_not_installed\nGITLEAKS:OK:0", ""
            ),
        )


@pytest.mark.parametrize("detail", [
    "TEST:SKIP:pytest:tool_not_installed\nGITLEAKS:OK:0",
    "GITLEAKS:SKIP:gitleaks:tool_not_installed\nIDENTITY:OK:fixture",
    "UNKNOWN:SKIP:unknown:tool_not_installed\nGITLEAKS:OK:0",
    "BIOME:SKIP:biome:required\nGITLEAKS:OK:0",
    "BIOME:SKIP:biome:no_tests\nGITLEAKS:OK:0",
    "BIOME:FAIL:1\nGITLEAKS:OK:0",
    "BIOME:SKIP:biome:tool_not_installed",
])
def test_task_acceptance_retains_required_quality_failures(repo: Path, detail: str) -> None:
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(
            repo, sha="HEAD", coverage="task", scope=("app.py",),
            runner=lambda command, _: subprocess.CompletedProcess(command, 0, detail, ""),
        )


def test_accept_revision_writes_and_reuses_exact_source_receipt(repo: Path) -> None:
    calls: list[list[str]] = []
    sha = git(repo, "rev-parse", "HEAD")

    first = acceptance.accept_revision(
        repo, sha=sha, scope=("app.py",), task_id="task-one", runner=successful_runner(calls)
    )
    second = acceptance.accept_revision(
        repo,
        sha=sha,
        scope=("pyproject.toml",),
        task_id="task-two",
        runner=successful_runner(calls),
    )

    assert first["state"] == "success"
    assert first["source_commit"] == sha
    assert first["source_tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert first["scope"] == ["app.py"]
    assert first["reused"] is False
    assert first["check_count"] == 1
    assert first["duration_ms"] >= 0
    assert first["checks"][0]["duration_ms"] >= 0
    assert Path(first["acceptance_artifact"]).is_file()
    assert second["acceptance_id"] == first["acceptance_id"]
    assert second["reused"] is True
    assert second["task_id"] == "task-two"
    assert second["scope"] == ["pyproject.toml"]
    assert second["reuse_lookup_ms"] >= 0
    assert calls == [["st", "check", "--check"]]


def test_accept_revision_rejects_dirty_candidate(repo: Path) -> None:
    (repo / "app.py").write_text("value = 2\n")

    with pytest.raises(acceptance.AcceptanceError, match="clean checkout"):
        acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))


def test_accept_revision_reuses_accepted_head_while_preserving_unrelated_wip(repo: Path) -> None:
    calls: list[list[str]] = []
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner(calls))
    (repo / "unrelated.py").write_text("other agent work\n")
    reused = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner(calls))
    assert reused["acceptance_id"] == accepted["acceptance_id"]
    assert reused["reused"] is True
    assert reused["working_tree_clean"] is False
    assert reused["source_commit"] == git(repo, "rev-parse", "HEAD")
    assert len(calls) == 1
    assert (repo / "unrelated.py").read_text() == "other agent work\n"
    assert acceptance.validate_acceptance_receipt(repo, reused)["state"] == "success"
    with pytest.raises(acceptance.AcceptanceError, match="clean checkout"):
        acceptance.accept_revision(repo, sha="HEAD", reuse=False, runner=successful_runner(calls))
    assert len(calls) == 1


def test_dirty_head_reuses_validated_receipt_stored_under_another_basis_key(repo: Path) -> None:
    calls: list[list[str]] = []
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner(calls))
    artifact = Path(accepted["acceptance_artifact"])
    # An isolated-basis receipt is stored under a key a dirty actual lookup never derives.
    artifact.rename(artifact.with_name("isolated-basis-key.json"))
    (repo / "unrelated.py").write_text("other agent work\n")

    reused = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner(calls))

    assert reused["acceptance_id"] == accepted["acceptance_id"]
    assert reused["reused"] is True and reused["working_tree_clean"] is False
    assert len(calls) == 1
    with pytest.raises(acceptance.AcceptanceError, match="clean checkout"):
        acceptance.accept_revision(repo, sha="HEAD", reuse=False, runner=successful_runner(calls))


def test_permission_only_change_refuses_receipt_reuse_and_runs_the_guard(repo: Path) -> None:
    protected = repo / "protected.json"
    protected.write_text('{}\n')
    protected.chmod(0o644)
    git(repo, "add", "protected.json")
    git(repo, "commit", "-qm", "protected input")
    calls = []

    def guard(command: list[str], cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, int(bool((cwd / 'protected.json').stat().st_mode & 0o022)), "guard", "")

    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    artifact = Path(accepted["acceptance_artifact"])
    retained = artifact.read_bytes()
    protected.chmod(0o664)
    assert acceptance.source_identity(repo)["clean"] is True
    with pytest.raises(acceptance.AcceptanceError, match="permission inputs"):
        acceptance.validate_acceptance_receipt(repo, accepted)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    assert len(calls) == 2
    assert artifact.read_bytes() == retained
    assert protected.stat().st_mode & 0o777 == 0o664


def test_acceptance_blocks_permission_drift_even_when_checks_exit_zero(repo: Path) -> None:
    selected = repo / "app.py"
    selected.chmod(0o644)

    def mutate(command: list[str], cwd: Path):
        (cwd / "app.py").chmod(0o664)
        return subprocess.CompletedProcess(command, 0, "passed before permission drift", "")

    with pytest.raises(acceptance.AcceptanceError, match="source_changed_during_acceptance"):
        acceptance.accept_revision(repo, sha="HEAD", runner=mutate)
    assert acceptance.source_identity(repo)["clean"] is True


def _committed_crlf_source(repo: Path) -> Path:
    selected = repo / "app.py"
    (repo / ".gitattributes").write_text("app.py text eol=crlf\n")
    selected.write_bytes(b"value = 1\r\n")
    selected.chmod(0o644)
    git(repo, "add", ".gitattributes", "app.py")
    git(repo, "commit", "-qm", "Git-clean CRLF checkout")
    assert git(repo, "status", "--porcelain") == ""
    return selected


@pytest.mark.parametrize("change", ["mode", "content"])
def test_git_clean_physical_drift_refuses_full_receipt_reuse(repo: Path, change: str) -> None:
    selected = _committed_crlf_source(repo)
    calls = []

    def guard(command: list[str], cwd: Path):
        calls.append(command)
        source = cwd / "app.py"
        passed = source.read_bytes() == b"value = 1\r\n" and source.stat().st_mode & 0o777 == 0o644
        return subprocess.CompletedProcess(command, int(not passed), "physical input guard", "")

    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    artifact = Path(accepted["acceptance_artifact"])
    retained = artifact.read_bytes()
    if change == "mode":
        selected.chmod(0o664)
    else:
        selected.write_bytes(b"value = 1\n")
        git(repo, "add", "app.py")  # Refresh stat data without changing the accepted Git blob.
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(acceptance.AcceptanceError, match=r"permission inputs|materialization"):
        acceptance.validate_acceptance_receipt(repo, accepted)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    assert len(calls) == 2
    assert artifact.read_bytes() == retained


def test_acceptance_blocks_git_clean_raw_byte_drift_during_checks(repo: Path) -> None:
    _committed_crlf_source(repo)

    def mutate(command: list[str], cwd: Path):
        (cwd / "app.py").write_bytes(b"value = 1\n")
        git(cwd, "add", "app.py")
        return subprocess.CompletedProcess(command, 0, "passed before physical drift", "")

    with pytest.raises(acceptance.AcceptanceError, match="source_changed_during_acceptance"):
        acceptance.accept_revision(repo, sha="HEAD", runner=mutate)
    assert git(repo, "status", "--porcelain") == ""


def test_isolated_basis_requires_actual_canonical_materialization(repo: Path) -> None:
    _committed_crlf_source(repo)
    calls = []
    with pytest.raises(acceptance.AcceptanceError, match="isolated source materialization"):
        acceptance.accept_revision(repo, sha="HEAD", execution_basis="isolated", runner=successful_runner(calls))
    assert calls == []


def test_receipt_without_consumed_source_binding_remains_immutable(repo: Path) -> None:
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    artifact = Path(accepted["acceptance_artifact"])
    retained = artifact.read_bytes()
    historical = json.loads(retained)
    historical["inputs"].pop("execution")
    historical["acceptance_id"] = acceptance._receipt_digest(historical)
    with pytest.raises(acceptance.AcceptanceError, match="consumed source binding"):
        acceptance.persist_validated_receipt(repo, historical, sha="HEAD")
    assert "execution" not in historical["inputs"]
    assert artifact.read_bytes() == retained


def test_ignored_local_file_link_count_invalidates_acceptance(repo: Path) -> None:
    import os

    config = repo / ".env.test"
    config.write_text("FIXTURE_MODE=local\n")
    ignored = repo / ".links"
    ignored.mkdir()
    (repo / ".gitignore").write_text(".env.test\n.links/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-qm", "ignored local configuration")
    calls = []

    def guard(command: list[str], cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, int((cwd / ".env.test").stat().st_nlink != 1), "local metadata guard", "")

    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    artifact = Path(accepted["acceptance_artifact"])
    retained = artifact.read_bytes()
    os.link(config, ignored / "outside-source.env")
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(acceptance.AcceptanceError, match="local environment/configuration"):
        acceptance.validate_acceptance_receipt(repo, accepted)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(repo, sha="HEAD", runner=guard)
    assert len(calls) == 2
    assert artifact.read_bytes() == retained


@pytest.mark.parametrize("change", ["tracked_mode", "tracked_content", "untracked_mode"])
def test_historical_source_guard_captures_newer_working_paths(repo: Path, change: str) -> None:
    old_sha = git(repo, "rev-parse", "HEAD")
    selected = repo / "later.txt"
    selected.write_bytes(b"later source\r\n")
    selected.chmod(0o644)
    (repo / ".gitattributes").write_text("later.txt text eol=crlf\n")
    git(repo, "add", ".gitattributes", "later.txt")
    git(repo, "commit", "-qm", "newer source outside historical paths")
    if change == "untracked_mode":
        selected = repo / "foreign.txt"
        selected.write_text("untracked owner work\n")
        selected.chmod(0o644)
    before = acceptance.source_identity(repo, sha=old_sha)
    if change == "tracked_content":
        selected.write_bytes(b"later source\n")
        git(repo, "add", "later.txt")
    else:
        selected.chmod(0o664)
    after = acceptance.source_identity(repo, sha=old_sha)
    assert before["execution"] == after["execution"]
    assert before["workspace_fingerprint"] == after["workspace_fingerprint"]
    assert before["working_materialization"] != after["working_materialization"]


def test_receipt_without_permission_binding_stays_historical(repo: Path) -> None:
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    historical = json.loads(Path(accepted['acceptance_artifact']).read_text())
    historical['inputs'].pop('source_modes')
    historical['acceptance_id'] = acceptance._receipt_digest(historical)
    with pytest.raises(acceptance.AcceptanceError, match=r"permission inputs.*not recorded"):
        acceptance.validate_acceptance_receipt(repo, historical)
    assert 'source_modes' not in historical['inputs']


def test_projected_permission_modes_use_old_blob_defaults_and_actual_equivalent_files(repo: Path) -> None:
    original = repo / "app.py"
    original.chmod(0o664)
    old_sha = git(repo, "rev-parse", "HEAD")
    original.write_text('later source\n')
    git(repo, 'commit', '--only', '-qm', 'different current source', '--', 'app.py')
    modes = acceptance.projected_source_modes(repo, old_sha)
    assert modes['app.py'] == 0o644
    assert modes['pyproject.toml'] == (repo / 'pyproject.toml').stat().st_mode & 0o777


@pytest.mark.parametrize('object_format', ['sha1', 'sha256'])
def test_projected_modes_compare_actual_git_blob_identities(tmp_path: Path, object_format: str) -> None:
    git(tmp_path, 'init', '-q', f'--object-format={object_format}', '--initial-branch=main')
    git(tmp_path, 'config', 'user.name', 'Fixture')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    selected = tmp_path / 'binary-source'
    selected.write_bytes(b'blob\0actual\xffcontent\n')
    selected.chmod(0o664)
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'actual Git object')
    assert acceptance.projected_source_modes(tmp_path, 'HEAD')['binary-source'] == 0o664
    selected.write_bytes(b'blob\0altered\xffcontent\n')
    assert acceptance.projected_source_modes(tmp_path, 'HEAD')['binary-source'] == 0o644


def test_successful_rerun_preserves_prior_immutable_receipt(repo: Path) -> None:
    first = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    artifact = Path(first["acceptance_artifact"])
    original = artifact.read_bytes()
    second = acceptance.accept_revision(repo, sha="HEAD", reuse=False, runner=successful_runner([]))
    assert Path(second["acceptance_artifact"]) != artifact
    assert artifact.read_bytes() == original
    assert acceptance.validate_acceptance_receipt(repo, first)["state"] == "success"


def test_persist_validated_receipt_retains_exact_source_cache_under_wip(repo: Path) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    artifact = Path(receipt["acceptance_artifact"])
    retained = artifact.read_bytes()
    (repo / "unrelated.py").write_text("owner work\n")
    persisted = acceptance.persist_validated_receipt(repo, receipt, sha="HEAD")
    calls: list[list[str]] = []
    reused = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner(calls))
    assert persisted["acceptance_id"] == reused["acceptance_id"]
    assert reused["reused"] is True
    assert calls == []
    assert (repo / "unrelated.py").read_text() == "owner work\n"
    assert artifact.read_bytes() == retained


def test_accept_revision_detects_checkout_mutation_during_checks(repo: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")

    def mutate(command: list[str], cwd: Path):
        (cwd / "app.py").write_text("value = 2\n")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    with pytest.raises(acceptance.AcceptanceError, match="source_changed_during_acceptance"):
        acceptance.accept_revision(repo, sha=sha, runner=mutate)


def test_acceptance_does_not_hold_repository_mutation_lock_while_checks_run(repo: Path) -> None:
    def run(command: list[str], cwd: Path):
        with acceptance.repo_lock(cwd, purpose="independent owned checkpoint"):
            pass
        return subprocess.CompletedProcess(command, 0, "ok", "")

    assert acceptance.accept_revision(repo, sha="HEAD", runner=run)["state"] == "success"


def test_isolated_plan_uses_selected_native_declaration(repo: Path) -> None:
    from cli.commands.check_native import native_plan

    config = repo / ".st-check.toml"
    config.write_text('[native]\nschema_version=1\nlocks=["pyproject.toml"]\nlegacy_tools=[]\n'
                      '[[native.stages]]\nid="selected"\nargv=["app.py"]\ncoverage="full"\n')
    git(repo, "add", ".st-check.toml")
    git(repo, "commit", "-qm", "selected native declaration")
    sha = git(repo, "rev-parse", "HEAD")
    expected = native_plan(repo)
    assert expected is not None
    config.write_text(config.read_text().replace('id="selected"', 'id="foreign-dirty-plan"'))

    assert acceptance._project_acceptance_plan(repo, commit=sha)["native"]["stages"] == expected["stages"]


def test_accept_revision_detects_shared_plan_mutation_during_checks(repo: Path, monkeypatch) -> None:
    scanner = repo.parent / "shared-scanner"
    scanner.write_text("original scanner")
    monkeypatch.setattr(acceptance.shutil, "which", lambda _name: str(scanner))

    def mutate(command: list[str], cwd: Path):
        scanner.write_text("changed scanner during acceptance")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    with pytest.raises(acceptance.AcceptanceError, match="acceptance_plan_changed_during_acceptance"):
        acceptance.accept_revision(repo, sha="HEAD", runner=mutate)


def test_validate_receipt_allows_later_checkout_to_advance(repo: Path) -> None:
    accepted_sha = git(repo, "rev-parse", "HEAD")
    receipt = acceptance.accept_revision(repo, sha=accepted_sha, runner=successful_runner([]))
    (repo / "later.py").write_text("later = True\n")
    git(repo, "add", "later.py")
    git(repo, "commit", "-qm", "later")

    validated = acceptance.validate_acceptance_receipt(repo, receipt, sha=accepted_sha)

    assert validated["state"] == "success"
    assert validated["source_commit"] == accepted_sha
    assert validated["source_tree"] != git(repo, "rev-parse", "HEAD^{tree}")


def test_validate_receipt_rejects_tampered_payload(repo: Path) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    payload = json.loads(Path(receipt["acceptance_artifact"]).read_text())
    payload["source"]["tree"] = "0" * 40

    with pytest.raises(acceptance.AcceptanceError, match="integrity"):
        acceptance.validate_acceptance_receipt(repo, payload)


@pytest.mark.parametrize("mutation", ["count", "missing", "command", "failed", "returncode", "plan"])
def test_receipt_success_label_does_not_override_actual_checks(repo: Path, mutation: str) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    payload = json.loads(Path(receipt["acceptance_artifact"]).read_text())
    if mutation == "count":
        payload["check_count"] = 0
    elif mutation == "missing":
        payload["checks"] = []
    elif mutation == "command":
        payload["checks"][0]["command"] = ["echo", "not a check"]
    elif mutation == "failed":
        payload["checks"][0]["state"] = "failed"
    elif mutation == "returncode":
        payload["checks"][0]["returncode"] = 7
    else:
        payload["plan"]["commands"] = [["echo", "not a check"]]
        payload["checks"][0]["command"] = payload["plan"]["commands"][0]
    payload["acceptance_id"] = acceptance._receipt_digest(payload)
    with pytest.raises(acceptance.AcceptanceError, match=r"checks|plan"):
        acceptance.validate_acceptance_receipt(repo, payload, sha="HEAD")


@pytest.fixture
def owned_done_claim(repo: Path, monkeypatch):
    from datetime import UTC, datetime

    from cli.commands import done_task
    from cli.lib.task_claims import current_worker_id

    claim = {"id": "task", "project_id": "project", "status": "running",
             "claimed_by": current_worker_id(), "claimed_at": datetime.now(UTC),
             "verification_result": {}}
    renewal = Mock(return_value=claim)
    monkeypatch.setattr("cli.lib.task_claims.renew_local_owned_claim", renewal)
    monkeypatch.setattr(done_task, "_checkpoint_repo_root", lambda _: str(repo))
    stored = Mock(return_value=True)
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", stored)
    return claim, renewal, stored


def test_done_reuses_explicit_receipt_without_touching_unrelated_wip(repo: Path, monkeypatch, owned_done_claim) -> None:
    from cli.commands import done_task

    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    (repo / "unrelated.txt").write_bytes(b"other agent work")
    git(repo, "add", "unrelated.txt")
    before = git(repo, "diff", "--cached", "--binary")
    claim, renewal, stored = owned_done_claim
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("do not repeat checks")))
    result = done_task._accept_completed_work("task", "project", paths=("app.py",), acceptance_receipt=receipt)
    assert result["source_commit"] == git(repo, "rev-parse", "HEAD")
    assert isinstance(result, AcceptedTaskWork) and result.reused is True
    assert (repo / "unrelated.txt").read_bytes() == b"other agent work"
    assert git(repo, "diff", "--cached", "--binary") == before
    renewal.assert_called_once_with(repo, "task")
    stored.assert_called_once_with("task", "project", dict(result), expected_worker=claim["claimed_by"],
        expected_claimed_at=claim["claimed_at"], expected_acceptance={})


@pytest.mark.parametrize("blocker", ["no-paths", "selected-dirty", "head-changed"])
def test_done_receipt_cannot_bypass_scope_or_new_checkpoint(repo: Path, monkeypatch, blocker: str, owned_done_claim) -> None:
    from cli.commands import done_task

    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    paths = () if blocker == "no-paths" else ("app.py",)
    if blocker != "no-paths":
        (repo / "app.py").write_text("value = 2\n")
        if blocker == "head-changed":
            git(repo, "add", "app.py")
            git(repo, "commit", "-qm", "task checkpoint")
    _claim, renewal, stored = owned_done_claim
    expected = {"no-paths": "Imported acceptance requires explicit", "selected-dirty": "Task-owned paths have uncommitted",
                "head-changed": "Task-owned source changed"}
    with pytest.raises((ValueError, acceptance.AcceptanceError), match=expected[blocker]):
        done_task._accept_completed_work("task", "project", paths=paths, acceptance_receipt=receipt)
    renewal.assert_called_once_with(repo, "task")
    stored.assert_not_called()


def test_changed_local_acceptance_plan_invalidates_receipt(repo: Path, monkeypatch) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    monkeypatch.setattr(
        acceptance,
        "_acceptance_plan",
        lambda: {"commands": [], "toolchain": {}, "fingerprint": "changed"},
    )

    with pytest.raises(acceptance.AcceptanceError, match="toolchain changed"):
        acceptance.validate_acceptance_receipt(repo, receipt)


def test_failed_full_gate_raises_and_retains_bounded_evidence(repo: Path) -> None:
    def fail(command: list[str], _cwd: Path):
        return subprocess.CompletedProcess(command, 7, "x" * 5000, "failed")

    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed") as error:
        acceptance.accept_revision(repo, sha="HEAD", runner=fail)

    artifact = Path(str(error.value).split("acceptance evidence: ", 1)[1])
    payload = json.loads(artifact.read_text())
    assert payload["state"] == "failed"
    assert payload["checks"][0]["returncode"] == 7
    assert len(payload["checks"][0]["detail"]) == 1200
    assert payload["checks"][0]["output_bytes"] == 5007


def test_failed_full_gate_names_failed_check_before_receipt_path(repo: Path) -> None:
    def fail(command: list[str], _cwd: Path):
        return subprocess.CompletedProcess(
            command, 1,
            "TEST:FAIL:1|details:.dev-tools/pytest-details.txt|hint:2 failed\n",
            "",
        )

    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.accept_revision(repo, sha="HEAD", runner=fail)

    assert "TEST:FAIL:1|details:.dev-tools/pytest-details.txt|hint:2 failed" in str(error.value)
    assert "acceptance evidence: " in str(error.value)


def test_later_success_does_not_overwrite_failed_acceptance_evidence(repo: Path) -> None:
    def fail(command, _cwd):
        return subprocess.CompletedProcess(command, 1, "failure artifact remains useful", "")

    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.accept_revision(repo, sha="HEAD", runner=fail)
    failed_path = Path(str(error.value).split("acceptance evidence: ", 1)[1])
    failed_bytes = failed_path.read_bytes()
    successful = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    assert Path(successful["acceptance_artifact"]) != failed_path
    assert failed_path.read_bytes() == failed_bytes
    assert json.loads(failed_bytes)["state"] == "failed"


def test_repo_lock_reports_concurrent_mutation(repo: Path) -> None:
    with (
        acceptance.repo_lock(repo, purpose="first"),
        pytest.raises(acceptance.AcceptanceError, match="repo_mutation_in_progress"),
        acceptance.repo_lock(repo, purpose="second"),
    ):
        pass


def test_repo_lock_waits_out_a_short_foreign_operation(repo: Path) -> None:
    import threading

    held, release = threading.Event(), threading.Event()

    def short_commit() -> None:
        with acceptance.repo_lock(repo, purpose="commit"):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=short_commit)
    holder.start()
    held.wait(5)
    threading.Timer(0.3, release.set).start()
    with acceptance.repo_lock(repo, purpose="full acceptance", wait_seconds=10):
        pass
    holder.join(5)


def test_check_acceptance_surface_forwards_exact_source(repo: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def accept(root: Path, **kwargs: object) -> dict[str, object]:
        captured.update({"root": root, **kwargs})
        return {
            "state": "success",
            "source_commit": "a" * 40,
            "acceptance_id": "acceptance-one",
            "acceptance_artifact": "/tmp/acceptance-one.json",
            "reused": True,
            "duration_ms": 12.5,
            "check_count": 1,
            "inputs": {"large_manifest": "must-not-be-printed"},
            "checks": [{"detail": "must-not-be-printed"}],
        }

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr("cli.lib.acceptance_coordinator.accept_source", lambda *args, **kwargs: Mock(to_dict=lambda: accept(*args, **kwargs)))
    monkeypatch.setattr(
        "cli.commands.check.renew_owned_claim",
        lambda root, task_id: captured.update({"renewed_root": root, "renewed_task": task_id}),
    )
    result = CliRunner().invoke(
        app,
        [
            "check",
            "--acceptance",
            "--sha",
            "abc",
            "--task",
            "task-one",
            "--scope",
            "backend",
            "--no-reuse",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "root": repo,
        "sha": "abc",
        "task_id": "task-one",
        "scope": ["backend"],
        "reuse": False,
        "materialization": "actual",
        "coverage": "full",
        "required_stages": [],
        "renewed_root": repo,
        "renewed_task": "task-one",
    }
    assert result.stdout == (
        "ACCEPTANCE:state=success|source="
        + "a" * 40
        + "|id=acceptance-one|artifact=/tmp/acceptance-one.json|"
        "reused=true|duration_ms=12.5|checks=1\n"
    )


def test_check_acceptance_json_preserves_full_machine_receipt(repo: Path, monkeypatch) -> None:
    receipt: dict[str, object] = {
        "state": "success",
        "source_commit": "a" * 40,
        "inputs": {"fingerprint": "input-one"},
        "checks": [{"detail": "retained detail"}],
    }
    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr("cli.lib.acceptance_coordinator.accept_source", lambda *_args, **_kwargs: Mock(to_dict=lambda: receipt))

    result = CliRunner().invoke(app, ["check", "--acceptance", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout.removeprefix("ACCEPTANCE:")) == receipt


def test_check_acceptance_blocks_when_owned_claim_cannot_be_renewed(
    repo: Path, monkeypatch
) -> None:
    from cli.lib.task_claims import TaskClaimRenewalError

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr(
        "cli.commands.check.renew_owned_claim",
        lambda *_args: (_ for _ in ()).throw(TaskClaimRenewalError("claim lost")),
    )
    accept = Mock()
    monkeypatch.setattr("cli.lib.acceptance_coordinator.accept_source", accept)

    result = CliRunner().invoke(app, ["check", "--acceptance", "--task", "task-one"])

    assert result.exit_code == 2
    assert "claim lost" in result.stderr
    accept.assert_not_called()


def test_check_acceptance_help_is_available_without_running_checks() -> None:
    result = CliRunner().invoke(app, ["check", "--acceptance", "--help"])

    assert result.exit_code == 0
    assert "Usage: st check --acceptance" in result.stdout
    assert "--no-reuse" in result.stdout
    assert "--json" in result.stdout


def test_receipt_detail_keeps_decisive_lines_without_admission_noise():
    noise = "\n".join(f"[st] Waiting for shared heavy-work lane: check pytest wait_age={i}.0s" for i in range(200))
    detail = "LINT:OK:0\nTEST:FAIL:3|details:.dev-tools/pytest.txt|hint:3 failed\n" + noise + "\nOSV:OK:0"
    kept = acceptance._receipt_detail(detail)
    assert "TEST:FAIL:3" in kept and "Waiting for shared" not in kept and len(kept) <= 1200
    blocked = acceptance._receipt_detail("TEST:SKIP:pytest:tool_not_installed\n" + "x" * 3000)
    assert blocked.startswith("TEST:SKIP:pytest:tool_not_installed") and len(blocked) <= 1200
