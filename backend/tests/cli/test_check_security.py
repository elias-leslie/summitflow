"""Local security adapters scan candidate inputs and state coverage limits."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.utils.heavy_work import HeavyWork
from cli.commands import check_dispatch, check_security


def test_security_admits_before_materializing_candidates(tmp_path, monkeypatch) -> None:
    from app.utils import heavy_work as guard

    def candidates(*_args):
        assert getattr(guard._LOCAL, "work", None) is not None
        return []

    monkeypatch.setattr(check_security, "_candidate_paths", candidates)
    assert check_security.run_local_security_check("gitleaks", tmp_path, [], False, []) == 0


def test_security_candidates_and_child_scratch_use_private_mounted_scratch(tmp_path, monkeypatch):
    from app.utils import transient_scratch

    root = tmp_path / "mounted-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("")
    monkeypatch.setattr(transient_scratch, "_MOUNTINFO", mountinfo)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    (tmp_path / "app.py").write_text("safe = True\n")
    observed = []

    def run(command, **kwargs):
        candidate = Path(command[-1])
        temporary = candidate.parent
        observed.append(temporary)
        assert temporary.parent == root / f"st-security-{os.getuid()}"
        assert temporary.stat().st_mode & 0o777 == 0o700
        assert kwargs["env"]["TMPDIR"] == str(temporary)
        assert Path(kwargs["env"]["XDG_CACHE_HOME"]).parent == temporary
        assert (candidate / "app.py").read_text() == "safe = True\n"
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(HeavyWork, "run", staticmethod(run))
    assert check_security.run_local_security_check("gitleaks", tmp_path, ["app.py"], True, []) == 0
    assert observed and all(not path.exists() for path in observed)


def test_gitleaks_materializes_only_changed_candidate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "backend" / "app.py"
    ignored = tmp_path / "node_modules" / "secret.js"
    source.parent.mkdir(parents=True)
    ignored.parent.mkdir()
    source.write_text("safe = True\n")
    ignored.write_text("should not be scanned\n")

    def run(command, **_kwargs):
        candidate = Path(command[-1])
        assert (candidate / "backend" / "app.py").read_text() == "safe = True\n"
        assert not (candidate / "node_modules").exists()
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(HeavyWork, "run", staticmethod(run))
    assert check_security.run_local_security_check(
        "gitleaks", tmp_path, ["backend/app.py", "node_modules/secret.js"], True, []
    ) == 0


def test_gitleaks_is_required_and_redacts_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = tmp_path / "secret.txt"
    candidate.write_text("placeholder\n")

    def missing(command, **_kwargs):
        assert "--redact" in command
        raise FileNotFoundError("gitleaks")

    monkeypatch.setattr(HeavyWork, "run", staticmethod(missing))
    assert check_security.run_local_security_check(
        "gitleaks", tmp_path, ["secret.txt"], True, []
    ) == 127
    assert "GITLEAKS:FAIL:127" in capsys.readouterr().out


def test_semgrep_without_local_rules_is_explicit_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "app.py"
    source.write_text("pass\n")
    run = Mock()
    monkeypatch.delenv("SEMGREP_RULES", raising=False)
    monkeypatch.setattr(HeavyWork, "run", run)

    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["app.py"], True, []
    ) == 0

    run.assert_not_called()
    output = capsys.readouterr().out
    assert "no_local_rules" in output
    assert "codeql_equivalence_not_claimed" in output


def test_semgrep_uses_only_local_rules_without_metrics_or_version_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("pass\n")
    (tmp_path / ".semgrep.yml").write_text("rules: []\n")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(HeavyWork, "run", run)

    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["app.py"], True, []
    ) == 0

    command = run.call_args.args[0]
    assert command[:4] == ["semgrep", "scan", "--config", str(tmp_path / ".semgrep.yml")]
    assert command[4:6] == ["--metrics", "off"]
    assert "--disable-version-check" in command


def test_semgrep_can_write_private_settings_and_logs_without_changing_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("pass\n")
    (tmp_path / ".semgrep.yml").write_text("rules: []\n")
    owner_home = tmp_path / "readonly-home"
    owner_home.mkdir()
    monkeypatch.setenv("HOME", str(owner_home))
    monkeypatch.setenv("SEMGREP_SETTINGS_FILE", str(owner_home / "settings.yml"))
    monkeypatch.setenv("SEMGREP_LOG_FILE", str(owner_home / "semgrep.log"))
    private_paths = []

    def run(command, **kwargs):
        environment = kwargs["env"]
        assert environment["HOME"] == str(owner_home)
        candidate = Path(command[-1])
        for name in ("SEMGREP_SETTINGS_FILE", "SEMGREP_LOG_FILE"):
            path = Path(environment[name])
            assert path.parent != owner_home
            assert not path.is_relative_to(candidate)
            assert path.parent.stat().st_mode & 0o077 == 0
            path.write_text("private scanner state\n")
            private_paths.append(path)
        assert os.environ["SEMGREP_SETTINGS_FILE"] == str(owner_home / "settings.yml")
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(HeavyWork, "run", staticmethod(run))
    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["app.py"], True, []
    ) == 0
    assert private_paths and all(not path.exists() for path in private_paths)
    assert not list(owner_home.iterdir())


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="Semgrep is not installed")
def test_local_shell_rule_detects_execution_without_flagging_argv_or_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rules = Path(__file__).resolve().parents[3] / ".semgrep.yml"
    shutil.copyfile(rules, tmp_path / ".semgrep.yml")
    source = tmp_path / "src" / "processes.py"
    source.parent.mkdir()
    source.write_text(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(['git', 'status'], shell=False)\n"
        "subprocess.run(['git', 'status'])\n"
        "asyncio.create_subprocess_exec('git', 'status')\n",
        encoding="utf-8",
    )
    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["src/processes.py"], True, []
    ) == 0

    source.write_text(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(command, shell=True)\n"
        "subprocess.Popen(command, shell=True)\n"
        "asyncio.create_subprocess_shell(command)\n",
        encoding="utf-8",
    )
    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["src/processes.py"], True, []
    ) == 1
    output = capsys.readouterr().out
    assert "SEMGREP:FAIL:1" in output
    details = list((tmp_path / ".dev-tools").glob("security-semgrep-*-details.txt"))
    assert details
    assert any(
        "summitflow-python-shell-execution" in path.read_text(encoding="utf-8")
        for path in details
    )


def test_osv_scans_only_candidate_lockfiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lockfile = tmp_path / "backend" / "uv.lock"
    lockfile.parent.mkdir()
    lockfile.write_text("version = 1\n")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(HeavyWork, "run", run)

    assert check_security.run_local_security_check(
        "osv", tmp_path, ["backend/uv.lock"], True, []
    ) == 0

    command = run.call_args.args[0]
    assert command.count("--lockfile") == 1
    assert str(lockfile) in command
    assert str(tmp_path / "pnpm-lock.yaml") not in command


def test_changed_go_sum_selects_supported_go_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = tmp_path / "go.mod"
    module.write_text("module example.test/monitor\n")
    (tmp_path / "go.sum").write_text("example.test/module v1 h1:fixture\n")
    monkeypatch.setattr(check_security, "_git_paths", lambda _root: ["go.mod", "go.sum"])
    assert check_security._lockfiles(tmp_path, ["go.sum"], True) == [module]


def test_security_aggregate_states_codeql_limitation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_security, "_candidate_paths", lambda *_args: [])
    assert check_security.run_local_security_check(
        "security", tmp_path, [], False, []
    ) == 0
    assert "codeql_equivalence=not_claimed" in capsys.readouterr().out


def test_dispatch_exposes_security_without_tool_registry_config(tmp_path: Path) -> None:
    runtime = Mock(spec=list(check_dispatch.CheckRuntime.__dataclass_fields__))
    runtime.resolve_repo_root.return_value = tmp_path
    runtime.changed_files.return_value = ["app.py"]
    runtime.run_local_security_check.return_value = 0

    assert check_dispatch.run_named_tool(
        "gitleaks", ["gitleaks"], {}, changed_only=True, fix=False, runtime=runtime
    ) == 0

    runtime.run_local_security_check.assert_called_once_with(
        "gitleaks", tmp_path, ["app.py"], True, []
    )
