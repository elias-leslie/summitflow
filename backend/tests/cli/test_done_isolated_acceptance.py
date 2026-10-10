"""One-command acceptance checks committed source without moving foreign WIP."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.commands import done_task
from cli.commands.done_task_acceptance import accept_isolated_revision
from cli.lib import acceptance
from cli.lib.acceptance_coordinator import validate_source_receipt
from cli.lib.task_completion_adapter import AcceptedTaskWork


def test_isolated_acceptance_materializes_on_private_mounted_scratch(native_source, monkeypatch, tmp_path):
    from app.utils import transient_scratch

    repo, sha, _store = native_source
    root = tmp_path / "mounted-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("")
    monkeypatch.setattr(transient_scratch, "_MOUNTINFO", mountinfo)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    original = subprocess.run
    materialized = []

    def stop_before_clone(command, **kwargs):
        if command[0] == "git" and "clone" in command:
            temporary = Path(command[-1]).parent
            materialized.append(temporary)
            assert temporary.parent == root / f"st-acceptance-{os.getuid()}"
            assert stat.S_IMODE(temporary.stat().st_mode) == 0o700
            assert stat.S_IMODE(temporary.parent.stat().st_mode) == 0o700
            raise acceptance.AcceptanceError("fixture stopped before materialization")
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", stop_before_clone)
    with pytest.raises(acceptance.AcceptanceError, match="fixture stopped"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source", reuse=False)
    assert materialized and all(not path.exists() for path in materialized)


@pytest.fixture
def sandbox_probe(tmp_path: Path):
    from cli.commands.done_task_acceptance import _sandbox_command

    if not shutil.which("bwrap"):
        pytest.skip("Installed managed isolation capability required")
    repo = tmp_path / "probe"
    repo.mkdir()
    metadata = repo / ".git"
    metadata.mkdir()
    temporary_parent = os.environ.get("ST_NATIVE_TMP_HOST_ROOT", "/var/tmp")
    with tempfile.TemporaryDirectory(prefix="st-probe-", dir=temporary_parent) as directory:
        temporary = Path(directory)

        def run(script: str):
            command = _sandbox_command(repo, repo, metadata, metadata, temporary, [], "fixture", (), "fixture", False)
            return subprocess.run([*command[:command.index("--") + 1], sys.executable, "-P", "-c", script],
                                  capture_output=True, text=True, check=False)

        yield run


def test_isolated_sandbox_has_private_writable_home_and_state(sandbox_probe, monkeypatch):
    # The suite-wide fixture points leases outside the sandbox; this proves
    # the sandbox's own private-HOME default.
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    backend = Path(__file__).resolve().parents[2]
    host_home = Path.home()
    host_lock = host_home / '.summitflow/leases/isolated-writable-home-fixture.lock'
    assert not host_lock.exists()
    inner_probe = (
        "from pathlib import Path\n"
        "assert not (Path.home()/'outer-state-marker').exists()\n"
        "(Path.home()/'inner-state-marker').write_text('private inner state')\n"
    )
    script = (
        "import os\nfrom pathlib import Path\nimport subprocess\nimport sys\nimport tempfile\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        "from cli.lib.leases import list_active\n"
        "assert list_active('isolated-writable-home-fixture') == []\n"
        "assert Path.home().is_relative_to('/tmp')\n"
        f"assert Path.home() != Path({str(host_home)!r})\n"
        "assert Path.home().stat().st_mode & 0o777 == 0o700\n"
        "for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME'):\n"
        "    directory=Path(os.environ[key])\n"
        "    assert directory.is_relative_to('/tmp')\n"
        "    assert directory.is_relative_to(Path.home())\n"
        "    directory.mkdir(parents=True, exist_ok=True)\n"
        "    (directory/'test-local-state').write_text('private fixture state')\n"
        "from cli.commands.done_task_acceptance import _sandbox_command\n"
        "outer_home=Path.home()\n"
        "(outer_home/'outer-state-marker').write_text('private outer state')\n"
        "with tempfile.TemporaryDirectory(prefix='st-inner-',dir=os.environ['ST_NATIVE_TMP_HOST_ROOT']) as directory:\n"
        "    repo=Path.cwd()\n"
        "    command=_sandbox_command(repo,repo,repo/'.git',repo/'.git',Path(directory),[],'fixture',(),'fixture',False)\n"
        f"    probe={inner_probe!r} + 'assert Path.home() != Path(' + repr(str(outer_home)) + ')\\n'\n"
        "    result=subprocess.run([*command[:command.index('--')+1],sys.executable,'-P','-c',probe],capture_output=True,text=True)\n"
        "    assert result.returncode == 0, result.stderr\n"
        "assert (outer_home/'outer-state-marker').read_text() == 'private outer state'\n"
        "assert not (outer_home/'inner-state-marker').exists()\n"
    )
    result = sandbox_probe(script)
    assert result.returncode == 0, result.stderr
    assert not host_lock.exists()


def test_portable_native_caller_scratch_stays_hidden_and_aliases_read_only(sandbox_probe, monkeypatch):
    # Exercise the supported portable physical parent. Its own caller scratch
    # needs masking even when this sandbox does not overlay all of /var/tmp.
    with (tempfile.TemporaryDirectory(prefix="st-caller-", dir="/var/tmp") as scratch,
          tempfile.TemporaryDirectory(prefix="st-alias-", dir="/var/tmp") as aliases):
        marker = Path(scratch) / "host-only"
        marker.write_text("private caller state")
        monkeypatch.setenv("TMPDIR", scratch)
        monkeypatch.setenv("ST_NATIVE_TOOL_ALIAS_ROOT", aliases)
        script = (
            "import errno\nfrom pathlib import Path\n"
            f"assert not Path({str(marker)!r}).exists()\n"
            f"aliases=Path({aliases!r})\n"
            "assert aliases.is_dir()\n"
            "try:\n    (aliases/'write').touch()\n"
            "except OSError as exc:\n    assert exc.errno in {errno.EROFS, errno.EACCES}\n"
            "else:\n    raise AssertionError('native aliases must remain read-only')\n"
        )
        result = sandbox_probe(script)
        assert result.returncode == 0, result.stderr
        assert marker.read_text() == "private caller state"


def test_masked_caller_scratch_keeps_mount_points_for_binds_beneath_it(monkeypatch):
    # Regression: direct native stages run pytest with TMPDIR on scratch, so
    # the project, its metadata and the temporary run all live beneath the
    # read-only mask. bwrap cannot create their mount points there itself.
    from cli.commands.done_task_acceptance import _sandbox_command

    if not shutil.which("bwrap"):
        pytest.skip("Installed managed isolation capability required")
    with (tempfile.TemporaryDirectory(prefix="st-caller-", dir="/var/tmp") as scratch,
          tempfile.TemporaryDirectory(prefix="st-alias-", dir="/var/tmp") as aliases):
        root = Path(scratch)
        # Tests point TMPDIR deeper inside the stage scratch; mask its root.
        nested = root / "pytest-of-fixture/inherited"
        nested.mkdir(parents=True)
        monkeypatch.setenv("TMPDIR", str(nested))
        monkeypatch.setenv("ST_NATIVE_TOOL_ALIAS_ROOT", aliases)
        (root / "host-only").write_text("private caller state")
        repo = root / "nested/project"
        source = root / "accepted/source"
        metadata = root / "accepted/metadata"
        common = root / "nested/common"
        for directory in (repo, source, metadata, common):
            directory.mkdir(parents=True)
        (source / "marker").write_text("accepted source")
        local = repo / "local.toml"
        local.write_text("local input")
        temporary = root / "runs/attempt"
        temporary.mkdir(parents=True)
        command = _sandbox_command(repo, source, metadata, common, temporary, [(local, local)],
                                   "fixture", (), "fixture", False)
        script = (
            "from pathlib import Path\n"
            f"assert not Path({str(root / 'host-only')!r}).exists()\n"
            f"assert Path({str(repo / 'marker')!r}).read_text() == 'accepted source'\n"
            f"assert Path({str(local)!r}).read_text() == 'local input'\n"
            f"assert Path({str(common)!r}).is_dir()\n"
        )
        result = subprocess.run([*command[:command.index("--") + 1], sys.executable, "-P", "-c", script],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_isolated_home_retains_only_read_only_fingerprinted_shared_config(sandbox_probe, tmp_path: Path, monkeypatch):
    host_home = tmp_path / "host-home"
    host_home.mkdir()
    shared = host_home / ".env.local"
    shared.write_text("ISOLATION_FIXTURE=approved-local-input\n")
    shared.chmod(0o600)
    foreign = host_home / "unrelated-home-state"
    foreign.write_text("unrelated host state\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda _: host_home))
    expected = acceptance._secret_safe_file_input("~/.env.local", shared)
    backend = Path(__file__).resolve().parents[2]
    script = (
        "import errno\nfrom pathlib import Path\nimport sys\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        "from cli.lib.acceptance import _secret_safe_file_input\n"
        "shared=Path.home()/'.env.local'\n"
        f"assert _secret_safe_file_input('~/.env.local',shared) == {expected!r}\n"
        "assert not (Path.home()/'unrelated-home-state').exists()\n"
        "try:\n    shared.write_text('unapproved fixture change')\n"
        "except OSError as exc:\n    assert exc.errno in {errno.EROFS,errno.EACCES}\n"
        "else:\n    raise AssertionError('Shared configuration must stay read-only')\n"
    )
    result = sandbox_probe(script)
    assert result.returncode == 0, result.stderr
    assert acceptance._secret_safe_file_input("~/.env.local", shared) == expected
    assert foreign.read_text() == "unrelated host state\n"


def test_isolated_sandbox_pnpm_can_install_local_offline_workspace(sandbox_probe):
    package_manager = json.loads((Path(__file__).resolve().parents[3] / 'package.json').read_text())['packageManager']
    script = (
        "import json\nimport os\nimport subprocess\nimport tempfile\nfrom pathlib import Path\n"
        "os.environ['COREPACK_ENABLE_NETWORK']='0'\n"
        "with tempfile.TemporaryDirectory() as directory:\n"
        "    root=Path(directory)\n"
        f"    (root/'package.json').write_text(json.dumps({{'private': True, 'packageManager': {package_manager!r}}}))\n"
        "    (root/'pnpm-workspace.yaml').write_text('packages: [frontend, packages/*]\\n')\n"
        "    library=root/'packages/library'\n"
        "    library.mkdir(parents=True)\n"
        "    (library/'package.json').write_text(json.dumps({'name':'@test/library','version':'1.0.0'}))\n"
        "    frontend=root/'frontend'\n"
        "    frontend.mkdir()\n"
        "    (frontend/'package.json').write_text(json.dumps({'name':'@test/frontend','private':True,'dependencies':{'@test/library':'workspace:*'}}))\n"
        "    result=subprocess.run(['pnpm','install','--offline','--ignore-scripts'],cwd=root,capture_output=True,text=True)\n"
        "    assert result.returncode == 0, result.stdout + result.stderr\n"
        "    assert (frontend/'node_modules/@test/library').is_dir()\n"
    )
    result = sandbox_probe(script)
    assert result.returncode == 0, result.stderr


def test_isolated_retry_reuses_successful_stage_from_failed_attempt(native_source):
    import http.server
    import threading

    repo, _sha, _store = native_source
    attempts = []

    class TransientFixture(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            attempts.append(True)
            self.send_response(503 if len(attempts) == 1 else 200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TransientFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    check = repo / "transient.py"
    check.write_text(f"import urllib.request\nimport json\nurllib.request.urlopen('http://127.0.0.1:{server.server_port}/')\n"
                     "print(json.dumps({'passed':1,'failed':0,'skipped':0}))\n")
    config = repo / ".st-check.toml"
    config.write_text(config.read_text() +
                      '\n[[native.stages]]\nid="transient"\nkind="test"\ncoverage="full"\n'
                      'argv=["python","-B","transient.py"]\n[native.stages.evidence]\nformat="json"\nsource="stdout"\n')
    git(repo, "add", "transient.py", ".st-check.toml")
    git(repo, "commit", "--only", "-qm", "transient fixture", "--", "transient.py", ".st-check.toml")
    sha = git(repo, "rev-parse", "HEAD")
    try:
        with pytest.raises(acceptance.AcceptanceError, match="retained check evidence"):
            accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
        second = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
        assert second["checks"][0]["evidence"]["stages"][0]["reused"] is True
        assert second["checks"][0]["evidence"]["stages"][1]["reused"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_isolated_acceptance_allows_unrelated_checkpoint_during_checks(native_source, monkeypatch):
    from cli.commands import done_task_acceptance

    repo, sha, _store = native_source
    original = done_task_acceptance.heavy_work

    class IndependentCheckpoint:
        def __enter__(self):
            self.manager = original("isolated concurrency regression")
            self.work = self.manager.__enter__()
            return self

        def run(self, command, **kwargs):
            with acceptance.repo_lock(repo, purpose="foreign checkpoint"):
                (repo / "unrelated-new.txt").write_text("concurrent unrelated work\n")
            return self.work.run(command, **kwargs)

        def __exit__(self, *args):
            return self.manager.__exit__(*args)

    monkeypatch.setattr(done_task_acceptance, "heavy_work", lambda purpose: IndependentCheckpoint())
    result = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert result["state"] == "success"
    assert (repo / "unrelated-new.txt").read_text() == "concurrent unrelated work\n"


def test_new_isolated_receipt_freezes_complete_modes_without_certifying_foreign_wip(native_source):
    repo, sha, _store = native_source
    receipt = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    entries = receipt["inputs"]["source_mode_entries"]
    assert len(entries) == receipt["inputs"]["source_modes"]["file_count"]
    assert entries["native.lock"] == 0o664
    (repo / "foreign.txt").write_text("later unrelated work\n")
    assert acceptance.validate_acceptance_receipt(repo, receipt, sha=sha)["state"] == "success"
    legacy = acceptance._load_receipt(receipt)[0]
    legacy["schema_version"] = 2
    legacy["inputs"].pop("source_mode_entries")
    legacy["acceptance_id"] = acceptance._receipt_digest(legacy)
    with pytest.raises(acceptance.AcceptanceError, match="fresh proof required"):
        acceptance.validate_acceptance_receipt(repo, legacy, sha=sha)


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
        # The declared real Python stage covers this fixture's contract. Global
        # linters/type/security runtimes are unrelated to its sandbox assertions.
        '[native]\nschema_version=1\nlegacy_tools=[]\nlocks=["native.lock"]\npaths=[".tool-env"]\nenvironment_inputs=[".tool-env"]\n'
        '[native.tools]\npython="/usr/bin/python3"\n'
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
    monkeypatch.setattr(done_task, "_owned_completion_claim", lambda *a: {"project_id": "fixture", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {},
        "context": {"completion_requirements": {"acceptance": "full"}}})
    monkeypatch.setattr("app.storage.task_spirit.get_task_spirit", lambda _: None)
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
    validated = validate_source_receipt(repo, receipt, sha=sha)
    assert validated.receipt["checks"][0]["evidence"]["stages"][0]["counts"]["executed"] == 1
    assert not {"inputs", "checks", "plan"}.intersection(receipt)
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())
    assert (repo / ".tool-env" / "prepared.txt").read_text() == "locked fixture dependency\n"
    assert store.call_args.args[2]["source_commit"] == sha
    reused = done_task._accept_completed_work("task-source", "fixture", paths=("check.py",))
    assert isinstance(reused, AcceptedTaskWork) and reused.reused is True
    assert (repo / ".git" / "index").read_bytes() == index
    assert all((repo / name).read_bytes() == content for name, content in foreign.items())


def test_isolation_preserves_equivalent_modes_and_fits_real_unix_socket_paths(native_source, monkeypatch, tmp_path: Path):
    repo, _sha, _store = native_source
    host_only = tmp_path / "host-only-scratch"
    host_only.write_text("outside isolated /tmp\n")
    # The actual protected input is safely prepared even under ambient002.
    # Its permission check must inspect equivalent permissions in isolation.
    config = repo / "protected.json"
    config.write_text('{}\n')
    config.chmod(0o644)
    executable = repo / "fixture-executable"
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o6750)
    check_file = repo / "check.py"
    check_file.write_text("import os\nimport socket\nimport tempfile\n" + check_file.read_text() + (
        "protected=Path('protected.json').lstat()\n"
        "assert stat.S_ISREG(protected.st_mode) and protected.st_uid == os.getuid()\n"
        "assert protected.st_nlink == 1 and stat.S_IMODE(protected.st_mode) == 0o644\n"
        "assert stat.S_IMODE(Path('fixture-executable').stat().st_mode) == 0o750\n"
        f"assert not Path({str(host_only)!r}).exists()\n"
        "with tempfile.TemporaryDirectory(dir='/tmp') as hardcoded:\n"
        "    Path(hardcoded, 'writable').write_text('private hard-coded scratch')\n"
        "    mapped=Path(os.environ['ST_NATIVE_TMP_HOST_ROOT'])/Path(hardcoded).relative_to('/tmp')\n"
        "    assert mapped.joinpath('writable').read_text() == 'private hard-coded scratch'\n"
        # Exercise the longest real pytest fixture suffix beneath the stage's
        # actual temporary root, rather than a shorter tool-directory parent.
        "socket_path=Path(os.environ['TMPDIR'])/'pytest-of-kasadis/pytest-0/test_installed_monitor_prefers_0/state/summitflow/monitor/control.sock'\n"
        "socket_path.parent.mkdir(parents=True)\n"
        "with socket.socket(socket.AF_UNIX) as bus:\n    bus.bind(str(socket_path))\n"
        "with tempfile.TemporaryDirectory(prefix='st-native-db-') as directory:\n"
        "    assert Path(directory).parent == Path(os.environ['TMPDIR'])\n"
        "    assert stat.S_IMODE(Path(os.environ['TMPDIR']).stat().st_mode) == 0o700\n"
        "    with socket.socket(socket.AF_UNIX) as database:\n"
        "        database.bind(str(Path(directory) / 'socket'))\n"
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
    assert host_only.read_text() == "outside isolated /tmp\n"


def test_isolated_native_fallback_preserves_nested_aliases_and_host_tmp(native_source, monkeypatch):
    repo, _sha, _store = native_source
    backend = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    inner_probe = """
import os
import shutil
from pathlib import Path
alias = Path(os.environ['PATH'].split(os.pathsep)[0])
assert alias.parent.parent == Path('/var/tmp')
assert shutil.which('python') == str(alias / 'python')
assert (alias / 'python').is_file()
assert not Path('/tmp/outer-marker').exists()
Path('/tmp/inner-marker').write_text('nested private scratch')
"""
    native_probe = f"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, {str(backend)!r})
from cli.commands.done_task_acceptance import _sandbox_command
alias = Path(os.environ['PATH'].split(os.pathsep)[0])
assert alias.parent.parent == Path('/var/tmp')
assert shutil.which('python') == str(alias / 'python')
Path('/tmp/outer-marker').write_text('outer private scratch')
with tempfile.TemporaryDirectory(dir='/var/tmp') as directory:
    root = Path.cwd()
    command = _sandbox_command(root, root, root/'.git', root/'.git', Path(directory), [], 'fixture', (), 'fixture', False)
    result = subprocess.run([*command[:command.index('--')+1], sys.executable, '-P', '-c', {inner_probe!r}], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
assert Path('/tmp/outer-marker').read_text() == 'outer private scratch'
assert not Path('/tmp/inner-marker').exists()
print('{{"passed":1,"failed":0,"skipped":0}}')
"""
    with tempfile.TemporaryDirectory(prefix="st-host-marker-", dir="/var/tmp") as host_directory:
        marker = Path(host_directory) / "marker"
        marker.write_text("host remains unchanged")
        nested_config = (
            '[native]\nschema_version=1\nlegacy_tools=[]\nlocks=["native.lock"]\n'
            f'[native.tools]\npython={sys.executable!r}\nbwrap={str(shutil.which("bwrap"))!r}\n'
            '[[native.stages]]\nid="nested"\nkind="test"\ncoverage="full"\n'
            'argv=["python","-B","probe.py"]\n'
            '[native.stages.evidence]\nformat="json"\nsource="stdout"\n'
        )
        check = repo / "check.py"
        check.write_text(check.read_text() + f"""
import os
import sys
import tempfile
sys.path.insert(0, {str(backend)!r})
from cli.commands.check_native import native_plan, run_native
host_marker = Path({str(marker)!r})
os.environ.pop('ST_NATIVE_TMP_HOST_ROOT', None)
with tempfile.TemporaryDirectory(dir='/tmp') as directory:
    child = Path(directory)
    (child/'.git').mkdir()
    (child/'native.lock').write_text('locked fixture')
    (child/'.st-check.toml').write_text({nested_config!r})
    (child/'probe.py').write_text({native_probe!r})
    plan = native_plan(child)
    assert plan is not None
    result = run_native(child, plan, reuse=False)
    assert result['state'] == 'pass', result
assert not host_marker.exists()
host_marker.parent.mkdir()
host_marker.write_text('private shadow')
assert host_marker.read_text() == 'private shadow'
""")
        config = repo / ".st-check.toml"
        config.write_text(config.read_text().replace("/usr/bin/python3", sys.executable))
        git(repo, "add", "check.py", ".st-check.toml")
        git(repo, "commit", "--only", "-qm", "native fallback nested isolation contract", "--", "check.py", ".st-check.toml")
        try:
            receipt = accept_isolated_revision(repo, sha=git(repo, "rev-parse", "HEAD"), scope=("check.py", ".st-check.toml"), task_id="task-source")
        except acceptance.AcceptanceError as exc:
            observations = repo / ".git/st/acceptance/isolated-observations"
            artifacts = [*observations.glob("*.log"), *observations.glob("*/native-artifacts/*")]
            raise AssertionError("\n".join(path.read_text() for path in artifacts)) from exc
        assert receipt["state"] == "success"
        assert marker.read_text() == "host remains unchanged"


def test_private_tmp_supports_nested_isolated_acceptance(native_source):
    repo, _sha, _store = native_source
    backend = Path(__file__).resolve().parents[2]
    config = repo / ".st-check.toml"
    config.write_text(config.read_text().replace('/usr/bin/python3', sys.executable).replace(
        '[[native.stages]]', 'git="/usr/bin/git"\nbwrap="/usr/bin/bwrap"\n'
        f'ruff={str(shutil.which("ruff") or "/managed-ruff-unavailable")!r}\n'
        f'gitleaks={str(shutil.which("gitleaks") or "/managed-gitleaks-unavailable")!r}\n[[native.stages]]',
    ))
    nested_check = (
        "import json\nimport tempfile\nfrom pathlib import Path\n"
        "with tempfile.TemporaryDirectory(dir='/tmp') as scratch:\n    Path(scratch, 'writable').touch()\n"
        "print(json.dumps({'passed':1,'failed':0,'skipped':0}))\n"
    )
    check = repo / "check.py"
    check.write_text("import os\nimport shutil\nimport subprocess\nimport sys\nimport tempfile\n" + check.read_text() + (
        "os.environ['DATABASE_URL']='postgresql://fixture@127.0.0.1:1/summitflow_test'\n"
        "os.environ['TEST_DATABASE_URL']=os.environ['DATABASE_URL']\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        "accept_isolated_revision=importlib.import_module('cli.commands.done_task_acceptance').accept_isolated_revision\n"
        "with tempfile.TemporaryDirectory(dir='/tmp') as directory:\n"
        "    child=Path(directory)\n"
        "    shutil.copy('.st-check.toml', child/'.st-check.toml')\n"
        "    shutil.copy('native.lock', child/'native.lock')\n"
        "    shutil.copytree('.tool-env', child/'.tool-env')\n"
        "    (child/'.gitignore').write_text('.tool-env/\\n__pycache__/\\n')\n"
        f"    (child/'check.py').write_text({nested_check!r})\n"
        "    def git(*args):\n"
        "        return subprocess.check_output(['/usr/bin/git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'core.hooksPath=/dev/null', *args], cwd=child, text=True).strip()\n"
        "    git('init', '-q', '--initial-branch=main')\n"
        "    git('add', '.')\n"
        "    git('commit', '-qm', 'nested accepted source')\n"
        "    try:\n"
        "        nested=accept_isolated_revision(child, sha=git('rev-parse', 'HEAD'), scope=('check.py',), task_id='nested-fixture')\n"
        "    except Exception:\n"
        "        observations=child/'.git/st/acceptance/isolated-observations'\n"
        "        for artifact in [*observations.glob('*.log'), *observations.glob('*/native-artifacts/*'), *observations.glob('*/*-details.txt')]:\n"
        "            print(artifact.read_text())\n"
        "        for artifact in observations.glob('*/*.json'):\n"
        "            for retained in json.loads(artifact.read_text()).get('checks', []):\n"
        "                print(retained.get('evidence', {}).get('legacy', {}).get('detail', ''))\n"
        "        raise\n"
        "    assert nested['state'] == 'success'\n"
    ))
    git(repo, "add", "check.py", ".st-check.toml")
    git(repo, "commit", "--only", "-qm", "nested isolation control", "--", "check.py", ".st-check.toml")

    try:
        receipt = accept_isolated_revision(repo, sha=git(repo, "rev-parse", "HEAD"), scope=("check.py",), task_id="task-source")
    except acceptance.AcceptanceError as exc:
        artifacts = (repo / '.git/st/acceptance/isolated-observations').glob('*/native-artifacts/*')
        raise AssertionError("\n".join(path.read_text() for path in artifacts)) from exc

    assert receipt["state"] == "success"


def test_workspace_dependency_discovery_borrows_only_locked_ignored_packages(tmp_path: Path):
    from cli.commands.done_task_acceptance import _dependency_roots

    git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    package = tmp_path / "packages" / "notes-ui"
    (package / "src").mkdir(parents=True)
    (package / "src" / "index.ts").write_text("export const tracked = true;\n")
    (package / "package.json").write_text('{"name":"@fixture/notes-ui"}\n')
    (package / "node_modules" / "lucide-react").mkdir(parents=True)
    (package / "node_modules" / "lucide-react" / "package.json").write_text('{"name":"lucide-react"}\n')
    (package / "dist").mkdir()
    (package / "dist" / "index.js").write_text("foreign compiled output\n")
    git(tmp_path, "add", ".")

    assert _dependency_roots(tmp_path) == [package / "node_modules"]
    (tmp_path / "pnpm-lock.yaml").unlink()
    with pytest.raises(acceptance.AcceptanceError, match="dependency lock"):
        _dependency_roots(tmp_path)


@pytest.mark.parametrize("invalid", ["tracked", "unignored", "escaped"])
def test_workspace_dependency_discovery_rejects_unprepared_package_roots(tmp_path: Path, invalid: str):
    from cli.commands.done_task_acceptance import _dependency_roots

    git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / ".gitignore").write_text("node_modules/\n" if invalid != "unignored" else "dist/\n")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    package = tmp_path / "packages" / "notes-ui"
    package.mkdir(parents=True)
    dependency = package / "node_modules"
    if invalid == "escaped":
        dependency.symlink_to(tmp_path.parent, target_is_directory=True)
    else:
        dependency.mkdir()
        (dependency / "index.js").write_text("dependency\n")
    git(tmp_path, "add", ".gitignore", "pnpm-lock.yaml")
    if invalid == "tracked":
        git(tmp_path, "add", "-f", "packages/notes-ui/node_modules/index.js")

    with pytest.raises(acceptance.AcceptanceError, match={
        "tracked": "tracked source", "unignored": "ignored local tooling", "escaped": "escapes this project",
    }[invalid]):
        _dependency_roots(tmp_path)


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


def test_isolation_rejects_owned_checkout_changes_during_the_gate(native_source, monkeypatch):
    from app.utils.heavy_work import HeavyWork

    repo, sha, store = native_source
    original = HeavyWork.run

    def mutate_original(work, *args, **kwargs):
        result = original(work, *args, **kwargs)
        (repo / "check.py").write_text("changed during isolated acceptance\n")
        return result

    monkeypatch.setattr(HeavyWork, "run", mutate_original)

    with pytest.raises(acceptance.AcceptanceError, match="Task-owned paths have uncommitted changes"):
        accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert (repo / "check.py").read_text() == "changed during isolated acceptance\n"
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
def test_historical_isolation_allows_newer_unconsumed_file_drift(native_source, monkeypatch, change: str):
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
    result = accept_isolated_revision(repo, sha=sha, scope=("check.py",), task_id="task-source")
    assert result["state"] == "success" and result["source_commit"] == sha
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
