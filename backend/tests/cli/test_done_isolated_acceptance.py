"""One-command acceptance checks committed source without moving foreign WIP."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.commands import done_task
from cli.commands.done_task_acceptance import accept_isolated_revision
from cli.lib import acceptance


def git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=repo, text=True).strip()


@pytest.fixture
def native_source(tmp_path: Path, monkeypatch):
    if shutil.which("bwrap") is None:
        pytest.skip("Installed managed isolation capability required")
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "--initial-branch=main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "native.lock").write_text("prepared fixture environment\n")
    # Ordinary native locks/configuration legitimately retain group write
    # permission. Their actual mode remains part of the receipt identity.
    (repo / "native.lock").chmod(0o664)
    (repo / "implementation.py").write_text("VALUE = 'accepted'\n")
    (repo / "foreign.txt").write_text("before\n")
    environment = repo / ".tool-env"
    environment.mkdir()
    (environment / "prepared.txt").write_text("locked fixture dependency\n")
    (repo / "check.py").write_text(
        "import errno\nimport importlib.util\nimport json\nimport stat\nfrom pathlib import Path\n"
        f"spec=importlib.util.spec_from_file_location('implementation',{str(repo / 'implementation.py')!r})\n"
        "assert spec is not None and spec.loader is not None\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert module.VALUE == 'accepted', 'Editable imports escaped immutable source'\n"
        "assert stat.S_IMODE(Path('native.lock').stat().st_mode) == 0o664\n"
        "assert stat.S_IMODE(Path('.st-check.toml').stat().st_mode) == 0o664\n"
        "dependency=Path('.tool-env/prepared.txt')\n"
        "assert dependency.read_text() == 'locked fixture dependency\\n'\n"
        "try:\n    dependency.write_text('implicit install')\n"
        "except OSError as exc:\n    assert exc.errno in {errno.EROFS, errno.EACCES}\n"
        "else:\n    raise AssertionError('Prepared dependency environment must stay read-only')\n"
        "print(json.dumps({'passed':1,'failed':0,'skipped':0}))\n"
    )
    (repo / ".gitignore").write_text("__pycache__/\n.tool-env/\n")
    (repo / ".st-check.toml").write_text(
        '[paths]\ntypes=".tool-env"\n'
        '[native]\nschema_version=1\nlocks=["native.lock"]\npaths=[".tool-env"]\nenvironment_inputs=[".tool-env"]\n'
        '[native.tools]\npython="/usr/bin/python3"\n'
        f'ty={str(shutil.which("ty") or "/managed-type-checker-unavailable")!r}\n'
        '[[native.stages]]\nid="contract"\nkind="test"\ncoverage="full"\n'
        'argv=["python","-B","check.py"]\n'
        '[native.stages.evidence]\nformat="json"\nsource="stdout"\n'
    )
    (repo / ".st-check.toml").chmod(0o664)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "accepted source")
    sha = git(repo, "rev-parse", "HEAD")
    (repo / "implementation.py").write_text("VALUE = 'foreign-unaccepted'\n")
    (repo / "foreign.txt").write_text("foreign staged work\n")
    git(repo, "add", "foreign.txt")
    (repo / "untracked.txt").write_text("foreign untracked work\n")
    monkeypatch.setattr(done_task, "_owned_completion_claim", lambda *a: {"project_id": "fixture", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {}})
    monkeypatch.setattr(done_task, "get_project_root_path", lambda _: str(repo))
    store = Mock(return_value=True)
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", store)
    monkeypatch.setattr("cli.lib.publish_workflow.publish_git", Mock(side_effect=AssertionError("GitHub unavailable")))
    return repo, sha, store


def test_done_accepts_isolated_source_and_reuses_it_on_retry(native_source):
    repo, sha, store = native_source
    selected = repo / "check.py"
    info = selected.stat()
    os.utime(selected, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    index = (repo / ".git" / "index").read_bytes()
    foreign = {name: (repo / name).read_bytes() for name in ("implementation.py", "foreign.txt", "untracked.txt")}
    receipt = done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    assert receipt["state"] == "success" and receipt["source_commit"] == sha
    assert receipt["checks"][0]["evidence"]["stages"][0]["counts"]["executed"] == 1
    acceptance.validate_acceptance_receipt(repo, receipt, sha=sha)
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())
    assert (repo / ".tool-env" / "prepared.txt").read_text() == "locked fixture dependency\n"
    assert store.call_args.args[2]["source_commit"] == sha
    reused = done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    assert reused["reused"] is True
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())


def test_isolation_preserves_equivalent_modes_and_fits_real_unix_socket_paths(native_source, monkeypatch, tmp_path: Path):
    repo, _sha, _store = native_source
    # The actual protected input is safely prepared even under ambient002.
    # Its permission check must inspect equivalent permissions in isolation.
    config = repo / "protected.json"
    config.write_text('{}\n')
    config.chmod(0o644)
    executable = repo / "fixture-executable"
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o6750)
    check_file = repo / "check.py"
    check_file.write_text("import os\nimport socket\n" + check_file.read_text() + (
        "protected=Path('protected.json').lstat()\n"
        "assert stat.S_ISREG(protected.st_mode) and protected.st_uid == os.getuid()\n"
        "assert protected.st_nlink == 1 and stat.S_IMODE(protected.st_mode) == 0o644\n"
        "assert stat.S_IMODE(Path('fixture-executable').stat().st_mode) == 0o750\n"
        # Native stages have a clean environment; the tool aliases were
        # prepared under the isolated gate's actual TMPDIR before that reset.
        "socket_path=Path(os.environ['PATH'].split(os.pathsep)[0]).parent/'pytest-of-kasadis/pytest-0/test_restricted_dispatch_uses_0/run/user/1000/bus'\n"
        "socket_path.parent.mkdir(parents=True)\n"
        "with socket.socket(socket.AF_UNIX) as bus:\n    bus.bind(str(socket_path))\n"
    ))
    git(repo, "add", "protected.json", "fixture-executable", "check.py")
    git(repo, "commit", "--only", "-qm", "protected config and real socket contract", "--", "protected.json", "fixture-executable", "check.py")
    sha = git(repo, "rev-parse", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    foreign = {name: (repo / name).read_bytes() for name in ("implementation.py", "foreign.txt", "untracked.txt")}
    parent_umask = next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('Umask:'))
    inherited = tmp_path / ('inherited-temp-' * 8)
    inherited.mkdir()
    monkeypatch.setenv("TMPDIR", str(inherited))
    try:
        receipt = accept_isolated_revision(repo, sha=sha, scope=("check.py", "protected.json", "fixture-executable"), task_id="task-source")
    except acceptance.AcceptanceError as exc:
        # The shared test runner cleans tmp_path after the gate. Keep these
        # fixture-only stage diagnostics in the same failing pytest output.
        observations = repo / ".git" / "st" / "acceptance" / "isolated-observations"
        artifacts = [*observations.glob("*/native-artifacts/*"), *observations.glob("*/*-details.txt")]
        details = "\n".join(path.read_text() for path in artifacts)
        raise AssertionError(f"{exc}\n{details}") from exc
    assert receipt["state"] == "success"
    acceptance.validate_acceptance_receipt(repo, receipt, sha=sha)
    assert next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('Umask:')) == parent_umask
    assert stat.S_IMODE(config.stat().st_mode) == 0o644
    assert stat.S_IMODE(executable.stat().st_mode) == 0o6750
    assert git(repo, "rev-parse", "HEAD") == sha
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())
    assert (repo / ".tool-env" / "prepared.txt").read_text() == "locked fixture dependency\n"


def test_isolation_preserves_unsafe_protected_mode_and_fails_the_real_guard(native_source):
    repo, _sha, store = native_source
    config = repo / "protected.json"
    config.write_text('{}\n')
    config.chmod(0o644)
    check_file = repo / "check.py"
    check_file.write_text(check_file.read_text() + (
        "if Path('protected.json').stat().st_mode & 0o022:\n"
        "    raise RuntimeError('Protected configuration is group or world writable')\n"
    ))
    git(repo, "add", "protected.json", "check.py")
    git(repo, "commit", "--only", "-qm", "protective mode check", "--", "protected.json", "check.py")
    sha = git(repo, "rev-parse", "HEAD")
    safe = accept_isolated_revision(repo, sha=sha, scope=("check.py", "protected.json"), task_id="task-source")
    artifact = Path(safe['acceptance_artifact'])
    historical = artifact.read_bytes()
    # Git sees the same blob/execute bit; sanitizing this unsafe permission to
    # 0644 would turn the required protective guard into a false pass.
    config.chmod(0o664)
    index = (repo / ".git" / "index").read_bytes()
    with pytest.raises(acceptance.AcceptanceError, match="permission inputs"):
        acceptance.validate_acceptance_receipt(repo, safe, sha=sha)
    with pytest.raises(acceptance.AcceptanceError, match="retained check evidence"):
        done_task._accept_completed_work("task-source", "fixture", paths=("check.py", "protected.json"))
    artifacts = (repo / ".git" / "st" / "acceptance" / "isolated-observations").glob("*/native-artifacts/*")
    assert any(b"Protected configuration is group or world writable" in path.read_bytes() for path in artifacts)
    assert stat.S_IMODE(config.stat().st_mode) == 0o664
    assert git(repo, "rev-parse", "HEAD") == sha
    assert (repo / ".git" / "index").read_bytes() == index
    assert (repo / "implementation.py").read_text() == "VALUE = 'foreign-unaccepted'\n"
    assert (repo / "foreign.txt").read_text() == "foreign staged work\n"
    assert (repo / "untracked.txt").read_text() == "foreign untracked work\n"
    assert artifact.read_bytes() == historical
    store.assert_not_called()


def test_permission_copy_rejects_changed_content_execute_bit_and_links(native_source, tmp_path: Path):
    from cli.commands.done_task_acceptance import _git, _preserve_equivalent_modes

    repo, sha, _store = native_source
    source = tmp_path / "isolated-source"
    _git(repo, "clone", "--local", "--no-hardlinks", "--no-checkout", "--", str(repo), str(source))
    _git(source, "checkout", "--detach", sha)
    # This tracked source has foreign content despite matching its Git mode.
    (repo / "implementation.py").chmod(0o600)
    # This content matches, but the actual execute bit differs from Git.
    (repo / "check.py").chmod(0o755)
    outside = tmp_path / "foreign-lock"
    outside.write_text("prepared fixture environment\n")
    outside.chmod(0o660)
    (repo / "native.lock").unlink()
    (repo / "native.lock").symlink_to(outside)
    _preserve_equivalent_modes(repo, source)
    assert stat.S_IMODE((source / ".st-check.toml").stat().st_mode) == 0o664
    assert stat.S_IMODE((source / "implementation.py").stat().st_mode) == 0o644
    assert stat.S_IMODE((source / "check.py").stat().st_mode) == 0o644
    assert stat.S_IMODE((source / "native.lock").stat().st_mode) == 0o644
    assert stat.S_IMODE((repo / "implementation.py").stat().st_mode) == 0o600
    assert stat.S_IMODE((repo / "check.py").stat().st_mode) == 0o755
    assert stat.S_IMODE(outside.stat().st_mode) == 0o660
    assert (repo / "native.lock").is_symlink()


def test_failed_isolation_retains_evidence_and_preserves_foreign_work(native_source):
    repo, _sha, store = native_source
    # Commit a failing task check while preserving every foreign path.
    (repo / "check.py").write_text("raise RuntimeError('fixture failure')\n")
    git(repo, "add", "check.py")
    git(repo, "commit", "--only", "-qm", "failing task source", "--", "check.py")
    index = (repo / ".git" / "index").read_bytes()
    with pytest.raises(acceptance.AcceptanceError, match="retained check evidence"):
        done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    assert (repo / ".git" / "index").read_bytes() == index
    assert (repo / "implementation.py").read_text() == "VALUE = 'foreign-unaccepted'\n"
    assert list((repo / ".git" / "st" / "acceptance" / "isolated-observations").glob("*.log"))
    artifacts = list((repo / ".git" / "st" / "acceptance" / "isolated-observations").glob("*/native-artifacts/*"))
    assert any(b"fixture failure" in artifact.read_bytes() for artifact in artifacts)
    store.assert_not_called()


def test_interruption_is_retryable_without_moving_work(native_source, monkeypatch):
    repo, sha, _store = native_source
    from app.utils.heavy_work import HeavyWork
    original = HeavyWork.run
    monkeypatch.setattr(HeavyWork, "run", Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert (repo / "foreign.txt").read_text() == "foreign staged work\n"
    monkeypatch.setattr(HeavyWork, "run", original)
    assert done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))["state"] == "success"


def test_isolation_rejects_changed_dependency_config(native_source):
    repo, _sha, store = native_source
    (repo / "native.lock").write_text("foreign dependency changes\n")
    with pytest.raises(acceptance.AcceptanceError, match="lock inputs differ"):
        done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    assert (repo / "native.lock").read_text() == "foreign dependency changes\n"
    store.assert_not_called()


def test_isolation_uses_selected_tool_registry_without_moving_foreign_changes(native_source):
    repo, _sha, _store = native_source
    registry = repo / "scripts" / "lib" / "tool-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"operator_tools": [{"name": "accepted-tool"}]}\n')
    check = repo / "check.py"
    check.write_text(check.read_text() + (
        "registry=json.loads(Path('scripts/lib/tool-registry.json').read_text())\n"
        "assert registry['operator_tools'][0]['name'] == 'accepted-tool'\n"
    ))
    git(repo, "add", "scripts/lib/tool-registry.json", "check.py")
    git(repo, "commit", "--only", "-qm", "selected tool registry", "--", "scripts/lib/tool-registry.json", "check.py")
    sha = git(repo, "rev-parse", "HEAD")
    registry.write_text('{"operator_tools": [{"name": "foreign-tool"}]}\n')
    index = (repo / ".git" / "index").read_bytes()
    foreign = {name: (repo / name).read_bytes() for name in (
        "scripts/lib/tool-registry.json", "implementation.py", "foreign.txt", "untracked.txt",
    )}

    receipt = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")

    assert receipt["state"] == "success" and receipt["source_commit"] == sha
    acceptance.validate_acceptance_receipt(repo, receipt, sha=sha)
    assert accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")["reused"] is True
    assert git(repo, "rev-parse", "HEAD") == sha
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())


def test_partial_checkout_never_hydrates_objects(native_source):
    repo, sha, store = native_source
    git(repo, "config", "remote.origin.promisor", "true")
    with pytest.raises(acceptance.AcceptanceError, match="partial/promisor"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    store.assert_not_called()


def test_isolation_rejects_original_checkout_changes_during_the_gate(native_source, monkeypatch):
    from app.utils.heavy_work import HeavyWork

    repo, sha, store = native_source
    original = HeavyWork.run

    def mutate_original(work, *args, **kwargs):
        result = original(work, *args, **kwargs)
        (repo / "foreign.txt").write_text("changed during isolated acceptance\n")
        return result

    monkeypatch.setattr(HeavyWork, "run", mutate_original)

    with pytest.raises(acceptance.AcceptanceError, match="Original task source or local inputs changed"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert (repo / "foreign.txt").read_text() == "changed during isolated acceptance\n"
    store.assert_not_called()


def test_isolation_unavailable_is_actionable(native_source, monkeypatch):
    _repo, _sha, store = native_source
    original = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None if name == "bwrap" else original(name, **kw))
    with pytest.raises(acceptance.AcceptanceError, match="bwrap is not installed"):
        done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    store.assert_not_called()


def test_isolation_ignores_ambient_remote_rewrites(native_source, tmp_path, monkeypatch):
    repo, sha, _store = native_source
    redirected = tmp_path / "gitconfig"
    redirected.write_text(f'[url "https://unavailable.invalid/"]\n\tinsteadOf = {repo}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(redirected))
    receipt = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert receipt["state"] == "success"
    assert (repo / "implementation.py").read_text() == "VALUE = 'foreign-unaccepted'\n"


def test_historical_task_source_preserves_newer_cloud_history_and_foreign_work(native_source):
    repo, sha, _store = native_source
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: historical cloud administration\n")
    (workflows / "ci.yml").chmod(0o664)
    (repo / ".gitignore").write_text((repo / ".gitignore").read_text() + ".links/\n")
    check = repo / "check.py"
    check.write_text(check.read_text().replace("import errno\n", "import errno\nimport os\n", 1) + (
        "cloud = Path('.github/workflows/ci.yml').stat()\n"
        "assert stat.S_IMODE(cloud.st_mode) == 0o644\n"
        "assert cloud.st_uid == os.getuid() and cloud.st_nlink == 1\n"
    ))
    git(repo, "add", ".github/workflows/ci.yml", "check.py", ".gitignore")
    git(repo, "commit", "--only", "-qm", "earlier cloud administration", "--", ".github/workflows/ci.yml", "check.py", ".gitignore")
    sha = git(repo, "rev-parse", "HEAD")
    (workflows / "ci.yml").write_text("name: newer cloud administration\n")
    git(repo, "add", ".github/workflows/ci.yml")
    git(repo, "commit", "--only", "-qm", "later unrelated cloud administration", "--", ".github/workflows/ci.yml")
    (repo / ".links").mkdir()
    os.link(workflows / "ci.yml", repo / ".links/current-cloud.yml")
    head = git(repo, "rev-parse", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    foreign = {name: (repo / name).read_bytes() for name in ("implementation.py", "foreign.txt", "untracked.txt")}
    receipt = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert receipt["state"] == "success" and receipt["source_commit"] == sha
    assert receipt["inputs"]["execution"]["basis"] == "isolated"
    acceptance.validate_acceptance_receipt(repo, receipt, sha=sha)
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())
    assert any(item["path"] == ".github/workflows/ci.yml" for item in receipt["inputs"]["source_inputs"]["files"])
    assert acceptance.projected_source_modes(repo, sha)['.github/workflows/ci.yml'] == 0o644
    assert stat.S_IMODE((workflows / 'ci.yml').stat().st_mode) == 0o664
    assert (workflows / "ci.yml").stat().st_nlink == 2
    # Import the real on-disk canonical receipt, which stores source.commit
    # rather than the returned descriptor's top-level source_commit alias.
    from cli.lib.completion_evidence import load_completion_evidence
    bundle = repo / ".git" / "st" / "completion-test.json"
    bundle.write_text(__import__("json").dumps({"acceptance_receipt": receipt["acceptance_artifact"]}))
    imported = load_completion_evidence(bundle, project_root=repo)
    assert imported["acceptance"]["state"] == "success"
    assert imported["acceptance"]["source_commit"] == sha


def test_isolation_rejects_unsafe_equivalent_current_file_metadata(native_source):
    repo, _sha, store = native_source
    protected = repo / "protected.json"
    protected.write_text("{}\n")
    (repo / ".gitignore").write_text((repo / ".gitignore").read_text() + ".links/\n")
    git(repo, "add", "protected.json", ".gitignore")
    git(repo, "commit", "--only", "-qm", "protected source input", "--", "protected.json", ".gitignore")
    sha = git(repo, "rev-parse", "HEAD")
    (repo / ".links").mkdir()
    os.link(protected, repo / ".links/outside-source.json")
    with pytest.raises(acceptance.AcceptanceError, match="equivalent source metadata"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert protected.stat().st_nlink == 2
    store.assert_not_called()


@pytest.mark.parametrize("change", ["mode", "content"])
def test_historical_isolation_guard_detects_newer_head_file_drift(native_source, monkeypatch, change: str):
    from app.utils.heavy_work import HeavyWork

    repo, sha, store = native_source
    selected = repo / "later.txt"
    selected.write_bytes(b"later source\r\n")
    selected.chmod(0o644)
    (repo / ".gitattributes").write_text("later.txt text eol=crlf\n")
    git(repo, "add", ".gitattributes", "later.txt")
    git(repo, "commit", "--only", "-qm", "newer unrelated source", "--", ".gitattributes", "later.txt")
    original = HeavyWork.run

    def drift(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        assert result.returncode == 0, result.stderr
        if change == "mode":
            selected.chmod(0o664)
        else:
            selected.write_bytes(b"later source\n")
            git(repo, "add", "later.txt")
        return result

    monkeypatch.setattr(HeavyWork, "run", drift)
    with pytest.raises(acceptance.AcceptanceError, match="Original task source or local inputs changed"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    store.assert_not_called()


def test_isolation_rejects_committed_checkout_content_transforms(native_source):
    repo, _sha, store = native_source
    (repo / "physical.txt").write_bytes(b"accepted source\r\n")
    (repo / ".gitattributes").write_text("physical.txt text eol=crlf\n")
    git(repo, "add", ".gitattributes", "physical.txt")
    git(repo, "commit", "--only", "-qm", "transformed checkout", "--", ".gitattributes", "physical.txt")
    sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(acceptance.AcceptanceError, match="retained check evidence") as failure:
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    log = Path(str(failure.value).split("retained check evidence: ", 1)[1])
    assert "isolated source materialization" in log.read_text()
    store.assert_not_called()


def test_historical_task_source_rejects_owned_revision_drift(native_source):
    repo, sha, _store = native_source
    (repo / "check.py").write_text("print('newer task behavior')\n")
    git(repo, "commit", "--only", "-qm", "owned behavior changed", "--", "check.py")
    with pytest.raises(acceptance.AcceptanceError, match="Task-owned source changed"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")


def test_historical_source_requires_literal_nonempty_scope(native_source):
    from cli.commands.done_task_acceptance import require_scope_matches_revision

    repo, sha, _store = native_source
    (repo / "foreign.txt").write_text("later committed foreign behavior\n")
    git(repo, "commit", "--only", "-qm", "foreign behavior changed", "--", "foreign.txt")
    for scope in ((), ("*",), (".",), ("../outside",)):
        with pytest.raises(acceptance.AcceptanceError, match="literal"):
            require_scope_matches_revision(repo, sha, scope)


def test_declared_created_file_must_exist_in_accepted_source(native_source):
    from cli.commands.done_task_acceptance import require_task_created_paths

    repo, sha, _store = native_source
    with pytest.raises(acceptance.AcceptanceError, match="Declared task file is missing"):
        require_task_created_paths(repo, sha, {"context": {"files_to_create": ["missing.py"]}})
    require_task_created_paths(repo, sha, {"context": {"files_to_create": ["check.py"]}})
