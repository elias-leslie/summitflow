from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from app.utils import heavy_work as heavy_work_guard
from cli.commands.check_native import NativeCheckError, _counts, native_plan, run_native
from cli.lib import acceptance
from cli.main import app


def _plan(root: Path) -> dict[str, Any]:
    plan = native_plan(root)
    assert plan is not None
    return plan


@pytest.fixture
def native_repo(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Private heavy-work lane: the host lane is shared with live agents' checks.
    monkeypatch.setattr(heavy_work_guard, "_LOCK_DIRECTORY", tmp_path_factory.mktemp("heavy-lane"))
    (tmp_path / ".tools").mkdir()
    (tmp_path / ".tools/python").symlink_to(sys.executable)
    (tmp_path / ".tools/suite.py").write_text(
        "import json, os\nfrom pathlib import Path\n"
        "assert 'AMBIENT_SECRET' not in os.environ\n"
        "Path('.dev-tools').mkdir(exist_ok=True)\n"
        "Path('.dev-tools/result.json').write_text(json.dumps({'passed': 2, 'failed': 0, 'skipped': 0}))\n"
        "print('native suite passed')\n"
    )
    (tmp_path / "project.lock").write_text("locked tools v1\n")
    (tmp_path / ".gitignore").write_text(".dev-tools/\n")
    (tmp_path / ".st-check.toml").write_text(
        '[native]\nschema_version = 1\nlocks = ["project.lock"]\npaths = [".tools"]\nlegacy_tools = []\n'
        '[[native.stages]]\nid = "native-suite"\nargv = ["python", ".tools/suite.py"]\n'
        'cwd = "."\nkind = "test"\ncoverage = "full"\nrequired = true\n'
        '[native.stages.evidence]\nformat = "json"\npath = ".dev-tools/result.json"\n'
    )
    return tmp_path


def test_native_executes_prepared_tools_with_fresh_evidence_and_no_ambient_credentials(native_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("AMBIENT_SECRET", "private")
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "pass"
    assert result["coverage"] == "full"
    stage = result["stages"][0]
    assert stage["state"] == "pass"
    assert stage["counts"] == {"executed": 2, "failed": 0, "skipped": 0}
    assert stage["tool"]["sha256"]
    assert stage["artifacts"][0]["sha256"]
    assert stage["duration_ms"] >= 0


def test_native_stage_materializes_aliases_and_scratch_on_mounted_scratch(native_repo, monkeypatch):
    from app.utils import transient_scratch

    root = native_repo / "mounted-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    mountinfo = native_repo / "mountinfo"
    mountinfo.write_text("")
    monkeypatch.setattr(transient_scratch, "_MOUNTINFO", mountinfo)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    parent = root / f"st-native-{os.getuid()}"
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        "import stat\n"
        "scratch=Path(os.environ['TMPDIR'])\n"
        "aliases=Path(os.environ['PATH'].split(os.pathsep)[0]).parent\n"
        f"assert scratch.parent == aliases.parent == Path({str(parent)!r})\n"
        "assert scratch != aliases\n"
        "assert stat.S_IMODE(scratch.stat().st_mode) == stat.S_IMODE(aliases.stat().st_mode) == 0o700\n"
    ))
    result = run_native(native_repo, _plan(native_repo), reuse=False)
    assert result["state"] == "pass", result["stages"][0]["detail"]
    assert not list(parent.iterdir())


def test_native_stage_can_create_private_temporary_files_without_ambient_environment(native_repo: Path, monkeypatch) -> None:
    from app.utils.transient_scratch import managed_temp_parent

    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    monkeypatch.setenv("AMBIENT_SECRET", "private")
    parent = managed_temp_parent("st-native", label="Native check")
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        "import stat, tempfile\n"
        "temporary = Path(os.environ['TMPDIR'])\n"
        "assert temporary.is_dir()\n"
        f"assert temporary.parent == Path({str(parent)!r})\n"
        "aliases = Path(os.environ['PATH'].split(os.pathsep)[0])\n"
        f"assert aliases.parent.parent == Path({str(parent)!r})\n"
        "assert temporary != aliases.parent\n"
        "assert stat.S_IMODE(temporary.stat().st_mode) == 0o700\n"
        "with tempfile.TemporaryDirectory() as directory:\n"
        "    assert Path(directory).parent == temporary\n"
        "    Path(directory, 'writable').write_text('private stage scratch')\n"
    ))
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "pass", result["stages"][0]["detail"]


def test_native_stage_preserves_only_explicit_docker_scratch_mapping(native_repo: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ST_NATIVE_TMP_HOST_ROOT", str(tmp_path))
    monkeypatch.setenv("AMBIENT_SECRET", "private")
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        f"assert os.environ['ST_NATIVE_TMP_HOST_ROOT'] == {str(tmp_path)!r}\n"
        "assert os.environ['TMPDIR'] == '/tmp'\n"
        "aliases=Path(os.environ['PATH'].split(os.pathsep)[0])\n"
        "assert aliases.parent.parent == Path(os.environ['ST_NATIVE_TMP_HOST_ROOT'])\n"
    ))

    result = run_native(native_repo, _plan(native_repo))

    assert result["state"] == "pass", result["stages"][0]["detail"]


@pytest.mark.parametrize("missing", ["project.lock", ".tools/python"])
def test_missing_preparation_is_unavailable(native_repo: Path, missing: str) -> None:
    (native_repo / missing).unlink()
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "fail"
    assert result["stages"][0]["state"] == "unavailable"
    assert "prepare explicitly" in result["stages"][0]["reason"]


@pytest.mark.parametrize("counts", [{"passed": 0, "failed": 0, "skipped": 0}, {"passed": 2, "failed": 0, "skipped": 1}])
def test_zero_exit_with_empty_or_skipped_tests_is_unavailable(native_repo: Path, counts: dict) -> None:
    (native_repo / ".tools/suite.py").write_text(
        "from pathlib import Path\nPath('.dev-tools').mkdir(exist_ok=True)\n"
        f"Path('.dev-tools/result.json').write_text({json.dumps(json.dumps(counts))})\n"
    )
    result = run_native(native_repo, _plan(native_repo))
    assert result["stages"][0]["state"] == "unavailable"


def test_stale_evidence_does_not_certify_zero_exit(native_repo: Path) -> None:
    run_native(native_repo, _plan(native_repo))
    (native_repo / ".tools/suite.py").write_text("print('no suite ran')\n")
    result = run_native(native_repo, _plan(native_repo))
    assert result["stages"][0]["state"] == "unavailable"
    assert "stale" in result["stages"][0]["reason"]


def test_reported_failure_overrides_zero_exit(native_repo: Path) -> None:
    (native_repo / ".tools/suite.py").write_text(
        "from pathlib import Path\nPath('.dev-tools').mkdir(exist_ok=True)\n"
        "Path('.dev-tools/result.json').write_text('{\"passed\":1,\"failed\":1,\"skipped\":0}')\n"
    )
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["state"] == "fail"


def test_focused_invocation_never_claims_full_coverage(native_repo: Path) -> None:
    result = run_native(native_repo, _plan(native_repo), stage_id="native-suite")
    assert result["state"] == "pass"
    assert result["coverage"] == "focused"


def test_task_acceptance_requires_declared_native_evidence_without_claiming_full(native_repo: Path, local_gate_tools) -> None:
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    _committed(native_repo)
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if "--quick" in command:
            return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")
        native = run_native(cwd, _plan(cwd), stage_id=command[-1])
        return subprocess.CompletedProcess(command, 0 if native["state"] == "pass" else 1,
                                           "NATIVE_EVIDENCE:" + json.dumps(native), "")

    result = accept_source(native_repo, sha="HEAD", materialization="actual", coverage="task",
                           scope=(".tools/suite.py",), required_stages=("native-suite",), runner=runner)
    assert result.reference.coverage == "task"
    assert [stage["id"] for stage in result.reference.required_stages] == ["scoped-quality", "native-suite"]
    assert validate_source_receipt(native_repo, Path(result.reference.acceptance_artifact)).reference == result.reference
    assert len(calls) == 2
    with pytest.raises(acceptance.AcceptanceError, match="missing"):
        accept_source(native_repo, sha="HEAD", materialization="actual", coverage="task",
                       scope=(".tools/suite.py",), required_stages=("undeclared",), runner=runner)


def test_task_required_optional_stage_cannot_omit_artifacts(native_repo: Path, local_gate_tools) -> None:
    from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt

    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="focused"\nargv=["python", ".tools/suite.py"]\n'
                      'coverage="focused"\nkind="test"\nrequired=false\n'
                      '[native.stages.evidence]\nformat="json"\npath=".dev-tools/result.json"\n')
    _committed(native_repo)

    def runner(command, cwd):
        if "--quick" in command:
            return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")
        return subprocess.CompletedProcess(command, 0, "NATIVE_EVIDENCE:" + json.dumps(run_native(cwd, _plan(cwd), stage_id="focused")), "")

    result = accept_source(native_repo, sha="HEAD", materialization="actual", coverage="task",
                           scope=(".tools/suite.py",), required_stages=("focused",), runner=runner)
    payload = json.loads(Path(result.reference.acceptance_artifact).read_text())
    payload["checks"][1]["evidence"]["stages"][0]["artifacts"] = []
    payload["acceptance_id"] = acceptance._receipt_digest(payload)
    with pytest.raises(acceptance.AcceptanceError, match="required native artifacts"):
        validate_source_receipt(native_repo, payload)


def test_not_applicable_requires_optional_explicit_reason(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="optional"\nargv=["python"]\ncoverage="full"\nrequired=false\napplicable=false\nreason="No migration schema in this project"\n')
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "pass"
    assert result["stages"][1]["state"] == "not-applicable"
    config.write_text(config.read_text().replace("required=false", "required=true"))
    with pytest.raises(NativeCheckError, match="optional with a reason"):
        _plan(native_repo)


@pytest.mark.parametrize("change", [
    ('schema_version = 1', 'schema_version = 9'),
    ('cwd = "."', 'cwd = "../outside"'),
    ('argv = ["python", ".tools/suite.py"]', 'argv = ["npx", "vitest"]'),
    ('kind = "test"', 'kind = "invented"'),
    ('format = "json"', 'format = "unknown"'),
])
def test_invalid_native_configuration_fails_closed(native_repo: Path, change: tuple[str, str]) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace(*change))
    with pytest.raises(NativeCheckError):
        _plan(native_repo)


def test_native_timeout_keeps_heavy_admission(native_repo: Path, monkeypatch) -> None:
    admission = Mock()
    admission.__enter__ = Mock(return_value=admission)
    admission.__exit__ = Mock(return_value=False)
    admission.run.side_effect = subprocess.TimeoutExpired(["python"], 600)
    heavy = Mock(return_value=admission)
    monkeypatch.setattr("cli.commands.check_native.heavy_work", heavy)
    result = run_native(native_repo, _plan(native_repo))
    heavy.assert_called_once_with("native check native-suite")
    assert result["stages"][0]["state"] == "fail"
    assert result["stages"][0]["returncode"] == 124
    assert admission.run.call_args.kwargs["env"]["UV_NO_SYNC"] == "1"


@pytest.mark.parametrize("format_name,content,expected", [
    ("junit", '<testsuite><testcase/><testcase><skipped/></testcase></testsuite>', {"executed": 1, "failed": 0, "skipped": 1}),
    ("go-test-json", '{"Action":"pass","Test":"TestNative"}\n{"Action":"pass","Package":"fixture"}', {"executed": 1, "failed": 0, "skipped": 0}),
    ("go-test-json", '{"Action":"pass","Package":"fixture"}', {"executed": 0, "failed": 0, "skipped": 0}),
])
def test_native_evidence_counts(format_name: str, content: str, expected: dict) -> None:
    assert _counts({"format": format_name}, content) == expected


def test_text_evidence_can_bind_godot_or_migration_markers() -> None:
    evidence = {"format": "text", "success_pattern": "SUITE PASS", "failure_pattern": "^FAIL:", "executed_pattern": "^PASS:"}
    assert _counts(evidence, "PASS: migration on fresh database\nSUITE PASS") == {"executed": 1, "failed": 0, "skipped": 0}
    with pytest.raises(NativeCheckError, match="success marker"):
        _counts(evidence, "no tests")


def test_native_cli_full_and_focused_results(native_repo: Path, monkeypatch) -> None:
    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: native_repo)
    full = CliRunner().invoke(app, ["check", "--check", "--json"])
    focused = CliRunner().invoke(app, ["check", "--native", "--stage", "native-suite", "--json"])
    assert full.exit_code == focused.exit_code == 0
    assert json.loads(full.stdout.removeprefix("NATIVE_EVIDENCE:"))["coverage"] == "full"
    assert json.loads(focused.stdout.removeprefix("NATIVE_EVIDENCE:"))["coverage"] == "focused"
    invalid = CliRunner().invoke(app, ["check", "--check", "--changed-only"])
    assert invalid.exit_code == 2


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def _committed(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "native@example.invalid")
    _git(repo, "config", "user.name", "Native Fixture")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "native fixture")


def test_native_receipt_stores_structured_evidence_and_reuses_exact_inputs(native_repo: Path) -> None:
    _committed(native_repo)
    calls = []

    def runner(command, cwd):
        calls.append(command)
        result = run_native(cwd, _plan(cwd))
        return subprocess.CompletedProcess(command, 0, "NATIVE_EVIDENCE:" + json.dumps(result), "")

    first = acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    second = acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    assert first["schema_version"] == 3
    assert first["coverage"] == "full"
    assert first["checks"][0]["evidence"]["stages"][0]["counts"]["executed"] == 2
    assert second["reused"] is True
    assert len(calls) == 1


def test_native_receipt_rejects_missing_structured_evidence(native_repo: Path) -> None:
    _committed(native_repo)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(native_repo, sha="HEAD", runner=lambda cmd, _: subprocess.CompletedProcess(cmd, 0, "ok", ""))


def test_native_receipt_preserves_unavailable_stage_evidence(native_repo: Path) -> None:
    (native_repo / ".tools/python").unlink()
    _committed(native_repo)

    def runner(command, cwd):
        return subprocess.CompletedProcess(command, 1, "NATIVE_EVIDENCE:" + json.dumps(run_native(cwd, _plan(cwd))), "")

    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    artifact = Path(str(error.value).split("acceptance evidence: ", 1)[1])
    receipt = json.loads(artifact.read_text())
    assert receipt["checks"][0]["evidence"]["stages"][0]["state"] == "unavailable"


def test_native_plan_binding_hides_explicit_environment_values(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('[[native.stages]]', '[native.environment]\nEXPLICIT_TOKEN="private-value"\n[[native.stages]]'))
    plan = acceptance._project_acceptance_plan(native_repo)
    assert "private-value" not in json.dumps(plan)
    assert plan["native"]["environment"]["EXPLICIT_TOKEN"]["sha256"]


def test_explicit_managed_tool_alias_is_bound_without_ambient_path(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('[[native.stages]]', f'[native.tools]\npython={json.dumps(sys.executable)}\n[[native.stages]]'))
    (native_repo / ".tools/python").unlink()
    plan = _plan(native_repo)
    assert plan["tools"]["python"]["sha256"]
    assert run_native(native_repo, plan)["state"] == "pass"


def test_stdout_evidence_supports_go_without_shell_redirects(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('format = "json"\npath = ".dev-tools/result.json"', 'format = "go-test-json"\nsource = "stdout"'))
    (native_repo / ".tools/suite.py").write_text('print(\'{"Action":"pass","Test":"TestNative","Package":"fixture"}\')\n')
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "pass"
    assert result["stages"][0]["artifacts"][0]["path"] == "stdout"
    assert result["stages"][0]["counts"]["executed"] == 1


def test_exact_full_retry_reuses_passed_stage_with_retained_artifact(native_repo: Path, monkeypatch) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="second"\nargv=["python", ".tools/suite.py"]\ncoverage="full"\nkind="test"\n[native.stages.evidence]\nformat="json"\npath=".dev-tools/result.json"\n')
    _committed(native_repo)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if len(calls) == 2:
            return subprocess.CompletedProcess(command, 1, "transient failure", "")
        return subprocess.run(command, **kwargs)

    work = Mock()
    work.run.side_effect = execute
    admission = Mock()
    admission.__enter__ = Mock(return_value=work)
    admission.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("cli.commands.check_native.heavy_work", lambda _: admission)
    first = run_native(native_repo, _plan(native_repo))
    second = run_native(native_repo, _plan(native_repo))
    assert first["state"] == "fail"
    assert first["stages"][0]["reused"] is False
    assert second["state"] == "pass"
    assert second["stages"][0]["reused"] is True
    assert second["stages"][1]["reused"] is False
    assert len(calls) == 3
    retained = Path(second["stages"][0]["artifacts"][0]["retained_path"])
    assert retained.is_file()
    retained.write_text("corrupt retained evidence")
    third = run_native(native_repo, _plan(native_repo))
    assert third["stages"][0]["reused"] is False


@pytest.mark.parametrize("change", ["dirty", "environment", "locks", "focused"])
def test_stage_reuse_rejects_changed_inputs_and_focused_proof(native_repo: Path, change: str) -> None:
    _committed(native_repo)
    run_native(native_repo, _plan(native_repo), stage_id="native-suite" if change == "focused" else None)
    if change == "dirty":
        (native_repo / "untracked-input.py").write_text("new source")
    elif change == "environment":
        config = native_repo / ".st-check.toml"
        config.write_text(config.read_text().replace('[[native.stages]]', '[native.environment]\nNATIVE_MODE="different"\n[[native.stages]]'))
        _git(native_repo, "add", ".")
        _git(native_repo, "commit", "-qm", "changed environment")
    elif change == "locks":
        (native_repo / "project.lock").write_text("changed lock")
        _git(native_repo, "add", ".")
        _git(native_repo, "commit", "-qm", "changed lock")
    result = run_native(native_repo, _plan(native_repo))
    assert result["stages"][0]["reused"] is False


def test_stage_cache_binds_protected_permissions_outside_declared_locks(native_repo: Path) -> None:
    protected = native_repo / "protected.json"
    protected.write_text('{}\n')
    protected.chmod(0o644)
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        "if Path('protected.json').stat().st_mode & 0o022:\n"
        "    raise RuntimeError('Protected configuration is group or world writable')\n"
    ))
    _committed(native_repo)
    first = run_native(native_repo, _plan(native_repo))
    assert first['state'] == 'pass'
    assert run_native(native_repo, _plan(native_repo))['stages'][0]['reused'] is True
    protected.chmod(0o664)
    second = run_native(native_repo, _plan(native_repo))
    assert second['state'] == 'fail'
    assert second['stages'][0]['reused'] is False
    assert 'Protected configuration' in second['stages'][0]['detail']


def test_actual_full_and_native_cache_bind_protected_file_link_count(native_repo: Path) -> None:
    import os

    protected = native_repo / "protected.json"
    protected.write_text("{}\n")
    protected.chmod(0o644)
    ignored = native_repo / ".links"
    ignored.mkdir()
    (native_repo / ".gitignore").write_text(".dev-tools/\n.links/\n")
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        "info = Path('protected.json').stat()\n"
        "assert info.st_uid == os.getuid() and info.st_nlink == 1, 'Unsafe protected metadata'\n"
    ))
    _committed(native_repo)
    observations = []

    def runner(command, cwd):
        result = run_native(cwd, _plan(cwd))
        observations.append(result)
        return subprocess.CompletedProcess(command, int(result["state"] != "pass"), "NATIVE_EVIDENCE:" + json.dumps(result), "")

    accepted = acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    artifact = Path(accepted["acceptance_artifact"])
    retained = artifact.read_bytes()
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    os.link(protected, ignored / "outside-source.json")
    assert _git(native_repo, "status", "--porcelain") == ""
    with pytest.raises(acceptance.AcceptanceError, match="materialization"):
        acceptance.validate_acceptance_receipt(native_repo, accepted)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    assert len(observations) == 2
    assert observations[-1]["stages"][0]["reused"] is False
    assert "Unsafe protected metadata" in observations[-1]["stages"][0]["detail"]
    assert artifact.read_bytes() == retained


def test_native_stage_cache_binds_git_clean_raw_checkout_bytes(native_repo: Path) -> None:
    selected = native_repo / "physical.txt"
    selected.write_bytes(b"same Git content\r\n")
    (native_repo / ".gitattributes").write_text("physical.txt text eol=crlf\n")
    _committed(native_repo)
    observations = []

    def runner(command, cwd):
        result = run_native(cwd, _plan(cwd))
        observations.append(result)
        return subprocess.CompletedProcess(command, 0, "NATIVE_EVIDENCE:" + json.dumps(result), "")

    accepted = acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    selected.write_bytes(b"same Git content\n")
    _git(native_repo, "add", "physical.txt")
    assert _git(native_repo, "status", "--porcelain") == ""
    with pytest.raises(acceptance.AcceptanceError, match="materialization"):
        acceptance.validate_acceptance_receipt(native_repo, accepted)
    refreshed = acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    assert refreshed["reused"] is False
    assert len(observations) == 2
    assert observations[-1]["state"] == "pass"
    assert observations[-1]["stages"][0]["reused"] is False


def test_native_blocks_git_clean_raw_byte_drift_during_checks(native_repo: Path) -> None:
    selected = native_repo / "physical.txt"
    selected.write_bytes(b"same Git content\r\n")
    (native_repo / ".gitattributes").write_text("physical.txt text eol=crlf\n")
    suite = native_repo / ".tools/suite.py"
    git_binary = shutil.which("git")
    assert git_binary is not None
    suite.write_text(suite.read_text() + (
        "Path('physical.txt').write_bytes(b'same Git content\\n')\n"
        f"import subprocess\nsubprocess.run([{git_binary!r}, 'add', 'physical.txt'], check=True)\n"
    ))
    _committed(native_repo)
    result = run_native(native_repo, _plan(native_repo))
    assert _git(native_repo, "status", "--porcelain") == ""
    assert result["state"] == "fail"
    assert result["stages"][0]["reason"] == "source_inputs_changed_during_native_check"


@pytest.mark.parametrize('dirty', [False, True])
def test_native_permission_drift_fails_even_for_dirty_source(native_repo: Path, dirty: bool) -> None:
    from cli.commands.check_native import _native_source

    selected = native_repo / 'protected.json'
    selected.write_text('{}\n')
    selected.chmod(0o644)
    suite = native_repo / '.tools/suite.py'
    suite.write_text(suite.read_text() + "Path('protected.json').chmod(0o664)\n")
    _committed(native_repo)
    if dirty:
        selected.write_text('{"unaccepted":"working contents"}\n')
    before = _native_source(native_repo)
    result = run_native(native_repo, _plan(native_repo))
    assert result['state'] == 'fail'
    assert result['stages'][0]['reason'] == 'source_inputs_changed_during_native_check'
    assert _native_source(native_repo)['source_modes'] != before['source_modes']
    assert not list((native_repo / '.git/st/native-stages').glob('*-native-suite.json'))


def test_historical_receipt_cannot_be_promoted_to_native_acceptance(native_repo: Path) -> None:
    _committed(native_repo)
    payload = {"schema_version": 1, "state": "success", "checks": []}
    payload["acceptance_id"] = acceptance._receipt_digest(payload)
    with pytest.raises(acceptance.AcceptanceError, match="successful full acceptance"):
        acceptance.validate_acceptance_receipt(native_repo, payload)


def test_legacy_skipped_required_tool_blocks_acceptance(native_repo: Path, local_gate_tools) -> None:
    (native_repo / ".st-check.toml").unlink()
    _committed(native_repo)
    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed"):
        acceptance.accept_revision(native_repo, sha="HEAD", runner=lambda command, _: subprocess.CompletedProcess(command, 0, "TEST:SKIP:pytest:tool_not_installed", ""))


def test_gate_fingerprint_ignores_catalogue_prose_but_binds_selected_check(tmp_path: Path, monkeypatch) -> None:
    from cli import tool_registry

    registry = tmp_path / "registry.json"
    original = {"operator_tools": [{"summary": "old prompt"}], "tools": [{"name": "pytest", "check": {"binary": "pytest"}}, {"name": "codeql", "check": {"args": "remote"}}]}
    registry.write_text(json.dumps(original))
    monkeypatch.setattr(tool_registry, "tool_registry_path", lambda: registry)
    before = acceptance._acceptance_plan()
    original["operator_tools"][0]["summary"] = "different prompt"
    original["tools"][1]["check"]["args"] = "different remote-only tool"
    registry.write_text(json.dumps(original))
    assert acceptance._acceptance_plan() == before
    original["tools"][0]["check"]["binary"] = "changed required binary"
    registry.write_text(json.dumps(original))
    assert acceptance._acceptance_plan() != before


def test_native_no_reuse_forces_fresh_full_stages(native_repo: Path) -> None:
    _committed(native_repo)
    run_native(native_repo, _plan(native_repo))
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    assert run_native(native_repo, _plan(native_repo), reuse=False)["stages"][0]["reused"] is False


def test_native_stage_reuse_binds_runner_implementation(native_repo: Path, monkeypatch) -> None:
    _committed(native_repo)
    run_native(native_repo, _plan(native_repo))
    monkeypatch.setattr("cli.commands.check_native._native_implementation", lambda: "changed runner proof")
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is False


def test_acceptance_no_reuse_disables_native_stage_cache(monkeypatch, native_repo: Path) -> None:
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(acceptance.subprocess, "run", execute)
    acceptance._run(["st", "check", "--check"], native_repo, native_reuse=False)
    assert execute.call_args.kwargs["env"]["ST_NATIVE_NO_REUSE"] == "1"


def test_ignored_local_configuration_invalidates_native_stage_cache(native_repo: Path) -> None:
    (native_repo / ".gitignore").write_text(".dev-tools/\n.env.test\n")
    (native_repo / ".env.test").write_text("LOCAL_MODE=first\n")
    _committed(native_repo)
    run_native(native_repo, _plan(native_repo))
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    (native_repo / ".env.test").write_text("LOCAL_MODE=second\n")
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is False


def test_changed_prepared_package_bytes_invalidate_same_lock_stage_cache(native_repo: Path) -> None:
    (native_repo / ".venv/bin").mkdir(parents=True)
    (native_repo / ".venv/bin/python").symlink_to(sys.executable)
    package = native_repo / ".venv/lib/package.py"
    package.parent.mkdir()
    package.write_text("prepared_version = 1\n")
    (native_repo / ".gitignore").write_text(".dev-tools/\n.venv/\n")
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('paths = [".tools"]', 'paths = [".venv/bin"]'))
    _committed(native_repo)
    first_plan = _plan(native_repo)
    run_native(native_repo, first_plan)
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    package.write_text("prepared_version = 2\n")
    changed_plan = _plan(native_repo)
    assert changed_plan["prepared_environment"] != first_plan["prepared_environment"]
    assert run_native(native_repo, changed_plan)["stages"][0]["reused"] is False


def test_native_full_preserves_applicable_legacy_checks_once(native_repo: Path, monkeypatch) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('legacy_tools = []\n', ''))
    selected = []

    def legacy(names, _configs, **kwargs):
        selected.extend(names)
        print("GITLEAKS:OK:0")
        print("SEMGREP:SKIP:semgrep:no_local_rules;codeql_equivalence_not_claimed")
        print("OSV:SKIP:osv:no_candidate_lockfiles")
        return 0

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: native_repo)
    monkeypatch.setattr("cli.commands.check._run_selected", legacy)
    full = CliRunner().invoke(app, ["check", "--check", "--json"])
    assert full.exit_code == 0
    evidence = json.loads(full.stdout.removeprefix("NATIVE_EVIDENCE:"))
    assert selected == ["security"]
    assert evidence["legacy"]["state"] == "pass"
    assert any(stage["id"] == "semgrep" and stage["state"] == "not-applicable" for stage in evidence["legacy"]["stages"])
    assert len(evidence["stages"]) == 1


def test_missing_legacy_scanner_never_certifies_native_full(native_repo: Path, monkeypatch) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('legacy_tools = []', 'legacy_tools = ["security"]'))

    def legacy(*_args, **_kwargs):
        print("GITLEAKS:OK:0")
        print("SEMGREP:SKIP:semgrep:tool_not_installed;coverage_not_claimed")
        print("OSV:SKIP:osv:no_candidate_lockfiles")
        return 0

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: native_repo)
    monkeypatch.setattr("cli.commands.check._run_selected", legacy)
    assert CliRunner().invoke(app, ["check", "--check", "--json"]).exit_code == 1


def test_failed_cheap_gate_prevents_native_execution(native_repo: Path, monkeypatch) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('legacy_tools = []', 'legacy_tools = ["security"]'))
    marker = native_repo / ".dev-tools/native-started"
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + "Path('.dev-tools/native-started').touch()\n")
    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: native_repo)
    monkeypatch.setattr("cli.commands.check._run_selected", lambda *args, **kwargs: 1)

    assert CliRunner().invoke(app, ["check", "--check", "--json"]).exit_code == 1
    assert not marker.exists()


def test_full_gate_uses_declared_covering_stage_but_explicit_focus_executes(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="subset"\nargv=["python", ".tools/suite.py"]\n'
                      'coverage="focused"\nkind="test"\nrequired=false\ncovered_by="native-suite"\n'
                      '[native.stages.evidence]\nformat="json"\npath=".dev-tools/result.json"\n')
    full = run_native(native_repo, _plan(native_repo))
    assert full["state"] == "pass"
    assert full["stages"][1]["state"] == "not-applicable"
    assert full["stages"][1]["covered_by"] == "native-suite"
    assert full["stages"][1]["reason"] == "coverage_provided_by:native-suite"
    assert full["stages"][1]["duration_ms"] == 0
    assert full["stages"][1]["returncode"] is None
    assert full["stages"][1]["artifacts"] == []
    assert "counts" not in full["stages"][1]
    assert run_native(native_repo, _plan(native_repo), stage_id="subset")["stages"][0]["state"] == "pass"


def test_failed_covering_stage_does_not_elide_focused_diagnostics(native_repo: Path) -> None:
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + "raise SystemExit(1)\n")
    (native_repo / ".tools/focused.py").write_text(
        "from pathlib import Path\nPath('.dev-tools').mkdir(exist_ok=True)\n"
        "Path('.dev-tools/focused.json').write_text('{\"passed\":1,\"failed\":0,\"skipped\":0}')\n"
    )
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="subset"\nargv=["python", ".tools/focused.py"]\n'
                      'coverage="focused"\nkind="test"\nrequired=false\ncovered_by="native-suite"\n'
                      '[native.stages.evidence]\nformat="json"\npath=".dev-tools/focused.json"\n')

    result = run_native(native_repo, _plan(native_repo))

    assert result["state"] == "fail"
    assert result["stages"][0]["state"] == "fail"
    focused = result["stages"][1]
    assert focused["state"] == "pass"
    assert focused["counts"]["executed"] == 1
    assert "covered_by" not in focused
    assert (native_repo / ".dev-tools/focused.json").is_file()


def test_missing_later_preparation_prevents_earlier_heavy_execution(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text() + '\n[[native.stages]]\nid="unprepared"\nargv=["missing-tool"]\ncoverage="full"\n')
    result = run_native(native_repo, _plan(native_repo))
    assert result["state"] == "fail"
    assert not (native_repo / ".dev-tools/result.json").exists()


def test_entrypoint_help_prose_does_not_invalidate_gate_but_behavior_does(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("CLI_REFERENCE='old operator guide'\ndef app():\n    return 'unchanged check dispatch'\n")
    before = acceptance._entrypoint_identity(path, name="main")
    path.write_text(path.read_text().replace("old operator guide", "fresh and longer operator guide"))
    assert acceptance._entrypoint_identity(path, name="main") == before
    path.write_text(path.read_text().replace("unchanged check dispatch", "changed check dispatch"))
    assert acceptance._entrypoint_identity(path, name="main") != before


def test_go_skip_policy_names_exact_not_applicable_cases() -> None:
    evidence = {"format": "go-test-json", "not_applicable_tests": {"fixture.TestSeed": "Opt-in fixture generator, exercised in the browser stage"}}
    content = '\n'.join(json.dumps(event) for event in [
        {"Action": "pass", "Test": "TestActual", "Package": "fixture"},
        {"Action": "skip", "Test": "TestSeed", "Package": "fixture"},
        {"Action": "skip", "Test": "TestUnexpected", "Package": "fixture"},
    ])
    assert _counts(evidence, content) == {"executed": 1, "failed": 0, "skipped": 2, "not_applicable": 1}


def test_explicit_script_unavailable_preserves_preparation_reason(native_repo: Path) -> None:
    (native_repo / ".tools/suite.py").write_text("print('NATIVE_UNAVAILABLE: prepared driver missing')\nraise SystemExit(127)\n")
    result = run_native(native_repo, _plan(native_repo))
    assert result["stages"][0]["state"] == "unavailable"
    assert result["stages"][0]["reason"] == "NATIVE_UNAVAILABLE: prepared driver missing"


def test_combined_evidence_includes_stderr_failures(native_repo: Path) -> None:
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('format = "json"\npath = ".dev-tools/result.json"', 'format="text"\nsource="combined"\nsuccess_pattern="SUITE PASS"\nfailure_pattern="^ERROR:"\nexecuted_pattern="^PASS:"'))
    (native_repo / ".tools/suite.py").write_text("import sys\nprint('PASS: actual check')\nprint('SUITE PASS')\nprint('ERROR: engine failure', file=sys.stderr)\n")
    result = run_native(native_repo, _plan(native_repo))
    assert result["stages"][0]["state"] == "fail"
    assert result["stages"][0]["counts"]["failed"] == 1


def test_focused_check_retains_complete_evidence_without_seeding_reuse(native_repo: Path) -> None:
    import hashlib

    _committed(native_repo)
    result = run_native(native_repo, _plan(native_repo), full_gate=False)
    outcome = result["stages"][0]
    assert result["coverage"] == "focused"
    assert [artifact["path"] for artifact in outcome["artifacts"]] == [".dev-tools/result.json", "output"]
    for artifact in outcome["artifacts"]:
        retained = Path(artifact["retained_path"])
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == artifact["sha256"]
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is False


@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_first_acceptance_requires_retained_artifact_bytes(native_repo: Path, damage: str) -> None:
    _committed(native_repo)

    def runner(command, cwd):
        result = run_native(cwd, _plan(cwd))
        artifact = Path(result["stages"][0]["artifacts"][0]["retained_path"])
        if damage == "missing":
            artifact.unlink()
        else:
            artifact.write_text("corrupted evidence")
        return subprocess.CompletedProcess(command, 0, "NATIVE_EVIDENCE:" + json.dumps(result), "")

    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.accept_revision(native_repo, sha="HEAD", runner=runner)
    receipt = json.loads(Path(str(error.value).split("acceptance evidence: ", 1)[1]).read_text())
    assert receipt["state"] == "failed"
    assert receipt["checks"][0]["evidence"]["reason"].startswith("native_artifact_unavailable")


def test_changed_executable_runtime_cache_invalidates_stage_proof(native_repo: Path) -> None:
    (native_repo / ".venv/bin").mkdir(parents=True)
    (native_repo / ".venv/bin/python").symlink_to(sys.executable)
    cached = native_repo / ".venv/.vite/deps/runtime.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("cached_runtime = 1\n")
    (native_repo / ".gitignore").write_text(".dev-tools/\n.venv/\n")
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('paths = [".tools"]', 'paths = [".venv/bin"]'))
    _committed(native_repo)
    run_native(native_repo, _plan(native_repo))
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    cached.write_text("cached_runtime = 2\n")
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is False


def test_selected_plan_omits_unmounted_workspace_dist_but_binds_package_dependencies(native_repo: Path) -> None:
    package = native_repo / "packages/notes-ui"
    (package / "src").mkdir(parents=True)
    (package / "src/index.ts").write_text("export const value = 1\n")
    dependencies = package / "node_modules"
    dependencies.mkdir()
    dependency = dependencies / "dependency.js"
    dependency.write_text("consumed dependency v1\n")
    (native_repo / "frontend/node_modules/@fixture").mkdir(parents=True)
    (native_repo / "frontend/node_modules/@fixture/notes-ui").symlink_to(package)
    (native_repo / ".gitignore").write_text(".dev-tools/\nnode_modules/\ndist/\n")
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('paths = [".tools"]', 'paths = [".tools"]\nenvironment_inputs=["frontend/node_modules"]'))
    _committed(native_repo)
    selected = _git(native_repo, "rev-parse", "HEAD")
    before = acceptance._project_acceptance_plan(native_repo, commit=selected)
    (package / "dist").mkdir()
    (package / "dist/index.js").write_text("host-only ignored build output\n")
    assert acceptance._project_acceptance_plan(native_repo, commit=selected) == before
    dependency.write_text("consumed dependency v2\n")
    assert acceptance._project_acceptance_plan(native_repo, commit=selected) != before


def test_unselected_environment_identity_does_not_resolve_source_projections(tmp_path: Path, monkeypatch) -> None:
    from cli.commands.check_native import _environment_identity

    environment = tmp_path / "prepared"
    environment.mkdir()
    (environment / "dependency.py").write_text("prepared dependency\n")
    before = _environment_identity(tmp_path, environment)
    monkeypatch.setattr(Path, "resolve", lambda *args, **kwargs: pytest.fail("unselected environment traversed a source projection"))
    assert _environment_identity(tmp_path, environment) == before


def test_selected_plan_resolves_workspace_root_independently_of_environment_size(native_repo: Path, monkeypatch) -> None:
    environment = native_repo / "prepared"
    environment.mkdir()
    executable = native_repo / ".tools/check"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (native_repo / ".gitignore").write_text(".dev-tools/\nprepared/\n")
    (native_repo / ".st-check.toml").write_text(
        '[native]\nschema_version = 1\nlocks = ["project.lock"]\npaths = []\n'
        'legacy_tools = []\nenvironment_inputs = ["prepared"]\n'
        f'[native.tools]\nfixture = "{executable}"\n'
        '[[native.stages]]\nid = "fixture"\nargv = ["fixture"]\n'
        'kind = "check"\ncoverage = "full"\nrequired = true\n'
    )
    _committed(native_repo)
    selected = _git(native_repo, "rev-parse", "HEAD")
    resolve = Path.resolve
    resolutions = 0

    def counted_resolve(path, *args, **kwargs):
        nonlocal resolutions
        if path == native_repo:
            resolutions += 1
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted_resolve)
    empty = native_plan(native_repo, commit=selected)
    empty_resolutions = resolutions
    for index in range(128):
        (environment / f"dependency_{index}.py").write_text("prepared dependency\n")
    resolutions = 0
    populated = native_plan(native_repo, commit=selected)

    assert empty is not None and populated is not None
    assert empty["prepared_environment"][0]["file_count"] == 0
    assert populated["prepared_environment"][0]["file_count"] == 128
    assert resolutions == empty_resolutions > 0


def test_standalone_executable_does_not_require_unused_packaging_python(native_repo: Path) -> None:
    tool_env = native_repo / "managed-tool"
    (tool_env / "bin").mkdir(parents=True)
    (tool_env / "pyvenv.cfg").write_text("unused packaging environment\n")
    (tool_env / "bin/python").symlink_to(tool_env / "missing-python")
    executable = tool_env / "bin/standalone"
    # Preserve an ELF launcher in the managed prefix, as Ruff/Ty are shipped.
    import shutil
    shutil.copyfile("/usr/bin/true", executable)
    executable.chmod(0o755)
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().split('[native.stages.evidence]')[0].replace('paths = [".tools"]', 'paths = []').replace(
        '[[native.stages]]', f'[native.tools]\nstandalone = "{executable}"\n[[native.stages]]').replace(
        'argv = ["python", ".tools/suite.py"]', 'argv = ["standalone"]').replace('kind = "test"', 'kind = "check"'))
    plan = _plan(native_repo)
    assert plan["prepared_environment"] == []
    assert run_native(native_repo, plan)["state"] == "pass"


def test_managed_python_symlink_binds_lexical_venv_packages(native_repo: Path) -> None:
    environment = native_repo / "prepared-env"
    (environment / "bin").mkdir(parents=True)
    executable = environment / "bin/python"
    executable.symlink_to(sys.executable)
    (environment / "pyvenv.cfg").write_text(f"home = {Path(sys.executable).parent}\ninclude-system-site-packages = false\n")
    package = environment / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/native_dependency.py"
    package.parent.mkdir(parents=True)
    package.write_text("VERSION = 1\n")
    script = native_repo / ".tools/suite.py"
    script.write_text("import native_dependency, subprocess\nsubprocess.run(['python', '-V'], check=True)\n" + script.read_text() + "print('dependency version', native_dependency.VERSION)\n")
    config = native_repo / ".st-check.toml"
    config.write_text(config.read_text().replace('paths = [".tools"]', 'paths = []').replace(
        '[[native.stages]]', f'[native.tools]\npython = "{executable}"\n[[native.stages]]'))
    (native_repo / ".gitignore").write_text(".dev-tools/\nprepared-env/\n")
    _committed(native_repo)
    plan = _plan(native_repo)
    assert plan["prepared_environment"][0]["path"] == "prepared-env"
    first = run_native(native_repo, plan)
    assert first["state"] == "pass"
    assert "dependency version 1" in first["stages"][0]["detail"]
    assert run_native(native_repo, _plan(native_repo))["stages"][0]["reused"] is True
    package.write_text("VERSION = 2\n")
    second = run_native(native_repo, _plan(native_repo))
    assert second["stages"][0]["reused"] is False
    assert "dependency version 2" in second["stages"][0]["detail"]


def test_native_allowlisted_aliases_survive_nested_private_tmp(native_repo: Path, monkeypatch, request) -> None:
    import tempfile

    from app.utils.transient_scratch import managed_temp_parent

    if not shutil.which("bwrap"):
        pytest.skip("Installed managed isolation capability required")
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    monkeypatch.setenv("AMBIENT_SECRET", "private")
    parent = managed_temp_parent("st-native", label="Native check")
    config = native_repo / ".st-check.toml"
    tools = {"python": sys.executable, "git": shutil.which("git"), "bwrap": shutil.which("bwrap")}
    assert tools["git"] and tools["bwrap"]
    outer_directory = tempfile.TemporaryDirectory(dir="/var/tmp")
    request.addfinalizer(outer_directory.cleanup)
    outer_aliases = Path(outer_directory.name) / "bin"
    outer_aliases.mkdir()
    for name in ("git", "bwrap"):
        alias = outer_aliases / name
        target = tools[name]
        assert target is not None
        alias.symlink_to(target)
        tools[name] = str(alias)
    declarations = "[native.tools]\n" + "".join(f"{name}={json.dumps(path)}\n" for name, path in tools.items())
    config.write_text(config.read_text().replace("[[native.stages]]", declarations + "[[native.stages]]"))
    backend = Path(__file__).resolve().parents[2]
    probe = (
        "import os,shutil,subprocess,sys\nfrom pathlib import Path\n"
        "aliases=Path(os.environ['PATH'].split(os.pathsep)[0])\n"
        f"assert not Path({str(outer_aliases)!r}).exists()\n"
        f"assert aliases.parent.parent == Path({str(parent)!r})\n"
        "assert 'AMBIENT_SECRET' not in os.environ\n"
        "assert aliases.parent == Path(os.environ['ST_NATIVE_TOOL_ALIAS_ROOT'])\n"
        "try:\n"
        "    (aliases.parent/'unexpected-write').write_text('must remain read-only')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('tool alias root must remain read-only')\n"
        "for name in ('git','bwrap'):\n"
        "    assert shutil.which(name) == str(aliases/name), name\n"
        "subprocess.run(['git','--version'],check=True,capture_output=True)\n"
        "nested=subprocess.run(['bwrap','--die-with-parent','--ro-bind','/','/','--proc','/proc','--dev','/dev',"
        "'--',sys.executable,'-P','-c',\"import subprocess; subprocess.run(['git','--version'],check=True)\"],capture_output=True,text=True)\n"
        "assert nested.returncode == 0, nested.stderr\n"
    )
    suite = native_repo / ".tools/suite.py"
    suite.write_text(suite.read_text() + (
        "import subprocess,sys,tempfile\n"
        f"sys.path.insert(0,{str(backend)!r})\n"
        "from cli.commands.done_task_acceptance import _sandbox_command\n"
        "scratch=Path(os.environ['TMPDIR'])\n"
        f"assert scratch.parent == Path({str(parent)!r})\n"
        "host_only=scratch/'host-only-scratch'\n"
        "host_only.write_text('must be hidden by private /tmp')\n"
        f"probe={probe!r} + 'assert not Path(' + repr(str(host_only)) + ').exists()\\n'\n"
        "with tempfile.TemporaryDirectory(dir='/var/tmp') as directory:\n"
        "    repo=Path.cwd()\n"
        "    private_var_tmp=Path(directory)/'private-var-tmp'\n"
        "    private_var_tmp.mkdir()\n"
        "    command=_sandbox_command(repo,repo,repo/'.git',repo/'.git',Path(directory),[],'fixture',(),'fixture',False,private_var_tmp=private_var_tmp)\n"
        f"    result=subprocess.run([*command[:command.index('--')+1],sys.executable,'-P','-c',probe],capture_output=True,text=True)\n"
        "    assert result.returncode == 0, result.stderr\n"
    ))
    result = run_native(native_repo, _plan(native_repo), reuse=False)
    assert result["state"] == "pass", result["stages"][0]["detail"]
