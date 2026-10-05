from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from cli.lib import commit_workflow, leases
from cli.lib.commit_workflow import CommitError, commit_repo
from cli.main import app

runner = CliRunner()


@pytest.mark.parametrize("extra", [[], ["--skip-checks"], ["--paths", "owned.py"]])
def test_st_commit_push_rejects_before_repository_resolution(extra) -> None:
    with (
        patch("cli.main.current_repo") as resolve,
        patch("cli.main.commit_repo") as commit,
        patch("cli.main.log_task_event") as event,
    ):
        result = runner.invoke(app, ["commit", "-m", "checkpoint", "--push", "--task", "task-1", *extra])
    assert result.exit_code == 1
    assert "st vcs publish --source ID --sha FULL_OID --now" in result.output
    resolve.assert_not_called()
    commit.assert_not_called()
    event.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["commit_repo", "commit_git_revision"])
@pytest.mark.parametrize("skip_checks", [False, True])
def test_commit_push_rejects_before_checks_claim_or_git(tmp_path, entrypoint, skip_checks) -> None:
    from cli.lib import commit_workflow

    with (
        patch.object(commit_workflow, "repo_lock") as lock,
        patch.object(commit_workflow, "renew_owned_claim") as renew,
        patch.object(commit_workflow, "run_git") as git,
        patch.object(commit_workflow.subprocess, "run") as process,
        pytest.raises(CommitError, match="st vcs publish --source ID --sha FULL_OID --now"),
    ):
        getattr(commit_workflow, entrypoint)(
            tmp_path, message="publish", task_id="task-one", push=True,
            skip_checks=skip_checks, paths=("owned.py",),
        )
    lock.assert_not_called()
    renew.assert_not_called()
    git.assert_not_called()
    process.assert_not_called()


def test_scoped_git_commit_preserves_unrelated_staged_work(tmp_path: Path, monkeypatch) -> None:
    from cli.lib import commit_workflow

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True).stdout

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/note.md").write_text("before")
    (tmp_path / "unrelated.py").write_text("before")
    git("add", ".")
    git("commit", "-qm", "baseline")
    (tmp_path / "docs/note.md").write_text("after")
    (tmp_path / "unrelated.py").write_text("unfinished work")
    git("add", "unrelated.py")
    calls = []
    monkeypatch.setattr(commit_workflow, "run_checks", lambda repo, **kw: (calls.append(kw) or (True, "")))
    result = commit_workflow.commit_git_revision(tmp_path, message="scoped docs", paths=("docs",), push=False)
    assert result["status"] == "SUCCESS"
    assert calls == [{"paths": ["docs/note.md"], "full": False}]
    assert git("show", "--format=", "--name-only", "HEAD").strip() == "docs/note.md"
    assert git("diff", "--cached", "--name-only").strip() == "unrelated.py"


def test_commit_blocks_foreign_lease_on_changed_file(tmp_path: Path, monkeypatch) -> None:
    from cli.lib import commit_workflow

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "shared.py").write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    baseline = git("rev-parse", "HEAD")
    (tmp_path / "shared.py").write_text("after\n")

    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path / "leases")
    monkeypatch.setattr(
        "cli.lib.execution_context.resolve_checkout_project_id", lambda _repo: "example"
    )
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["shared.py"], project_root=str(tmp_path))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")

    with pytest.raises(CommitError, match="leased by another agent"):
        commit_workflow.commit_repo(
            tmp_path, message="overwrite shared", skip_checks=True
        )
    assert git("rev-parse", "HEAD") == baseline


def test_scoped_commit_ignores_foreign_lease_outside_selection(
    tmp_path: Path, monkeypatch
) -> None:
    from cli.lib import commit_workflow

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "mine.py").write_text("before\n")
    (tmp_path / "shared.py").write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    (tmp_path / "mine.py").write_text("after\n")
    (tmp_path / "shared.py").write_text("other agent work\n")

    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path / "leases")
    monkeypatch.setattr(
        "cli.lib.execution_context.resolve_checkout_project_id", lambda _repo: "example"
    )
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["shared.py"], project_root=str(tmp_path))
    leases.acquire("another-project", ["mine.py"], project_root=str(tmp_path))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")

    result = commit_workflow.commit_git_revision(
        tmp_path, message="mine", paths=("mine.py",), skip_checks=True
    )
    assert result["status"] == "SUCCESS"
    assert git("show", "--format=", "--name-only", "HEAD") == "mine.py"
    assert git("status", "--porcelain", "--", "shared.py")


@patch("cli.main.log_task_event")
@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_uses_canonical_workflow_and_logs_task(
    mock_current_repo: MagicMock,
    mock_commit_repo: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_current_repo.return_value = Path("/repo")
    mock_commit_repo.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "sha": "commit",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "--message", "test", "--task", "task-1"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="task-1",
        push=False,
        skip_checks=False,
        paths=(),
    )
    mock_log.assert_called_once_with(
        "task-1",
        "st commit commit=commit pushed=true",
    )
    assert "COMMIT[1]:status=SUCCESS pushed=true detail=commit" in result.stdout


def test_failed_checkpoint_prints_existing_gate_artifact_hints() -> None:
    with (
        patch("cli.main.current_repo", return_value=Path("/repo")),
        patch("cli.main.commit_repo", return_value={
            "status": "BLOCKED", "reason": "quality_gates_failed",
            "detail": "LINT:OK:0|details:lint.txt\nTYPE:FAIL:1|details:types.txt\nTEST:FAIL:1|details:tests.txt",
        }),
    ):
        result = runner.invoke(app, ["commit", "-m", "checkpoint"])
    assert result.exit_code == 2
    assert "TYPE:FAIL:1|details:types.txt" in result.stdout
    assert "TEST:FAIL:1|details:tests.txt" in result.stdout
    assert "LINT:OK" not in result.stdout


def test_local_task_commit_renews_owned_claim_before_repository_work(tmp_path: Path) -> None:
    with (
        patch("cli.lib.commit_workflow.renew_owned_claim") as renew,
        patch("cli.lib.commit_workflow.repo_lock", return_value=nullcontext()),
        patch(
            "cli.lib.commit_workflow.commit_git_revision",
            return_value={"repo": "repo", "status": "SKIP", "pushed": False},
        ) as commit,
        patch("cli.lib.commit_workflow._record_task_commit", side_effect=lambda _repo, result, **_: result),
    ):
        commit_repo(tmp_path, message="checkpoint", task_id="task-one", skip_checks=True)

    renew.assert_called_once_with(tmp_path, "task-one")
    commit.assert_called_once()


@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_forwards_selected_paths(
    mock_current_repo: MagicMock,
    mock_commit_repo: MagicMock,
) -> None:
    mock_current_repo.return_value = Path("/repo")
    mock_commit_repo.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "sha": "commit",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "-m", "test", "--path", "a.py", "--path", "b.py"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="",
        push=False,
        skip_checks=False,
        paths=("a.py", "b.py"),
    )


def test_st_commit_help_shows_repeated_paths_form() -> None:
    result = runner.invoke(app, ["commit", "--help"])

    assert result.exit_code == 0
    assert "--paths a --paths b" in result.stdout


def test_commit_repo_skips_gitignored_paths_in_add_step(tmp_path: Path) -> None:
    """Already-ignored paths (e.g., user did `git rm --cached` then added to .gitignore)
    must not abort the commit. The add step should skip them; commit picks up the
    pre-staged deletion."""
    from cli.lib import commit_workflow

    (tmp_path / ".git").mkdir()

    def fake_run_git(_repo: Path, args: list[str]):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if args[:2] == ["status", "--porcelain"]:
            result.stdout = "D  ignored.json\nM  .gitignore\n"
        if args[:2] == ["diff", "--cached"] and "--quiet" in args:
            result.returncode = 1
        if args[:1] == ["check-ignore"]:
            # ignored.json is gitignored; .gitignore itself isn't.
            result.returncode = 0 if "ignored.json" in args else 1
        if args[:2] == ["rev-parse", "HEAD"]:
            result.stdout = "abc1234"
        return result

    with (
        patch.object(commit_workflow, "run_git", side_effect=fake_run_git) as run,
        patch.object(commit_workflow, "_commit_selected_index", return_value=subprocess.CompletedProcess([], 0, "", "")),
        patch.object(commit_workflow, "run_checks", return_value=(True, "")),
        patch.object(commit_workflow, "repo_lock", return_value=nullcontext()),
        patch.object(commit_workflow, "workspace_fingerprint", return_value="stable"),
        patch.object(commit_workflow, "_require_foreign_leases_clear"),
        patch.object(
            commit_workflow.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, b"candidate", b""),
        ),
    ):
        result = commit_repo(
            tmp_path,
            message="ignore drift",
            paths=(".gitignore", "ignored.json"),
            push=False,
        )

    add_calls = [c for c in run.call_args_list if c.args[1][:1] == ["add"]]
    assert add_calls, "expected git add to be called for the non-ignored path"
    # ignored.json must be excluded from add args
    assert add_calls[0].args[1] == ["add", "--", ".gitignore"]
    assert result["status"] == "SUCCESS"


@pytest.mark.parametrize(
    ("full", "mode"),
    [(False, "--quick"), (True, "--check")],
)
def test_git_run_checks_scopes_changed_files_for_selected_paths(
    tmp_path: Path, full: bool, mode: str
) -> None:
    with patch("cli.lib.commit_workflow.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""

        ok, detail = commit_workflow.run_checks(
            tmp_path,
            paths=("frontend/a.tsx", "backend/b.py"),
            full=full,
        )

    assert ok is True
    assert detail == "ok"
    env = run.call_args.kwargs["env"]
    assert env["ST_CHECK_CHANGED_FILES"] == "frontend/a.tsx\nbackend/b.py"
    assert run.call_args.args[0] == ["st", "check", mode, "--changed-only"]


def _publish_result(**extra: object) -> dict[str, object]:
    return {"repo": "repo", "path": "/repo", "status": "SUCCESS", "pushed": True, "sha": "abc1234", **extra}


@patch("cli.lib.commit_workflow.run_git")
def test_refresh_symbols_after_publish_posts_changed_symbol_paths(mock_run_git: MagicMock) -> None:
    from cli.lib.commit_workflow import _refresh_symbols_after_publish

    mock_run_git.return_value = MagicMock(stdout="backend/app/x.py\ndocs/readme.md\nfrontend/y.tsx\n")
    mock_client = MagicMock()

    with (
        patch("cli.client.STClient", return_value=mock_client) as client_cls,
        patch("cli.lib.execution_context.resolve_checkout_project_id", return_value="summitflow"),
    ):
        result = _refresh_symbols_after_publish(Path("/repo"), _publish_result())

    assert result["symbol_refresh_queued"] == 2
    client_cls.assert_called_once_with(project_id="summitflow")
    diff_args = mock_run_git.call_args[0][1]
    assert diff_args == ["diff-tree", "-r", "--name-only", "--no-commit-id", "abc1234"]
    posted = mock_client.post.call_args.kwargs["json"]
    assert posted == {"paths": ["backend/app/x.py", "frontend/y.tsx"]}


def test_refresh_symbols_after_local_commit() -> None:
    from cli.lib.commit_workflow import _refresh_symbols_after_publish

    with (
        patch("cli.lib.commit_workflow.run_git", return_value=MagicMock(stdout="backend/a.py\n")),
        patch("cli.lib.execution_context.resolve_checkout_project_id", return_value="summitflow"),
        patch("cli.client.STClient") as client_cls,
    ):
        result = _refresh_symbols_after_publish(Path("/repo"), _publish_result(pushed=False))

    assert result["symbol_refresh_queued"] == 1
    client_cls.assert_called_once()


@patch("cli.lib.commit_workflow.run_git")
def test_refresh_symbols_after_publish_skips_unregistered_repo(mock_run_git: MagicMock) -> None:
    from cli.lib.commit_workflow import _refresh_symbols_after_publish

    with (
        patch("cli.client.STClient") as client_cls,
        patch("cli.lib.execution_context.resolve_checkout_project_id", return_value=None),
    ):
        result = _refresh_symbols_after_publish(Path("/repo"), _publish_result())

    assert "symbol_refresh_queued" not in result
    client_cls.assert_not_called()
    mock_run_git.assert_not_called()


@patch("cli.lib.commit_workflow.run_git")
def test_refresh_symbols_after_publish_swallows_api_errors(mock_run_git: MagicMock) -> None:
    from cli.lib.commit_workflow import _refresh_symbols_after_publish

    mock_run_git.return_value = MagicMock(stdout="backend/app/x.py\n")
    mock_client = MagicMock()
    mock_client.post.side_effect = RuntimeError("api down")

    with (
        patch("cli.client.STClient", return_value=mock_client),
        patch("cli.lib.execution_context.resolve_checkout_project_id", return_value="summitflow"),
    ):
        result = _refresh_symbols_after_publish(Path("/repo"), _publish_result())

    assert result["status"] == "SUCCESS"
    assert "symbol_refresh_queued" not in result


@pytest.mark.parametrize(
    ("full", "mode"),
    [(False, "--quick"), (True, "--check")],
)
def test_checkpoint_and_publication_use_distinct_check_modes(tmp_path, full, mode):
    from cli.lib import commit_workflow
    with patch.object(commit_workflow.subprocess, 'run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, 'ok', '')
        assert commit_workflow.run_checks(
            tmp_path, paths=['frontend/a.tsx'], full=full
        )[0]
    assert run.call_args.args[0] == ['st', 'check', mode, '--changed-only']


def test_local_checkpoint_never_calls_publication(tmp_path: Path, monkeypatch) -> None:
    from cli.lib import commit_workflow

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True
        ).stdout

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "initial")
    (tmp_path / "app.py").write_text("after\n")
    monkeypatch.setattr(commit_workflow, "run_checks", lambda *_args, **_kwargs: (True, "ok"))

    result = commit_workflow.commit_git_revision(tmp_path, message="local checkpoint")

    assert result["status"] == "SUCCESS"
    assert result["pushed"] is False
    assert result["check_count"] == 1
    assert result["check_duration_ms"] >= 0


def test_checkpoint_blocks_if_checkout_changes_while_checks_run(tmp_path: Path, monkeypatch) -> None:
    from cli.lib import commit_workflow

    monkeypatch.setattr(commit_workflow, "dirty", lambda _repo: True)
    monkeypatch.setattr(commit_workflow, "_selected_changed_files", lambda *_args: ["app.py"])
    fingerprints = iter(("before", "after"))
    monkeypatch.setattr(commit_workflow, "workspace_fingerprint", lambda _repo: next(fingerprints))
    monkeypatch.setattr(commit_workflow, "run_checks", lambda *_args, **_kwargs: (True, "ok"))

    result = commit_workflow.commit_git_revision(tmp_path, message="checkpoint")

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "source_changed_during_checks"


def test_local_task_commit_is_linked_without_publication(monkeypatch, tmp_path: Path) -> None:
    from cli.lib import commit_workflow

    stored = Mock(return_value={"id": "task-one"})
    monkeypatch.setattr("app.storage.tasks.add_commit", stored)
    monkeypatch.setattr(
        "cli.lib.execution_context.resolve_checkout_project_id", lambda _repo: "project-one"
    )
    result = commit_workflow._record_task_commit(
        tmp_path,
        {"status": "SUCCESS", "sha": "a" * 40, "pushed": False},
        task_id="task-one",
    )

    stored.assert_called_once_with("task-one", "a" * 40, project_id="project-one")
    assert result["task_commit"]["source_commit"] == "a" * 40


@pytest.mark.parametrize('tracked_kind', ['file', 'symlink'])
@pytest.mark.parametrize('hook_fails', [False, True])
def test_selected_cached_deletion_preserves_local_directory_and_other_index_work(
    tmp_path: Path, monkeypatch, tracked_kind: str, hook_fails: bool,
) -> None:
    from cli.lib import commit_workflow

    def git(*args: str) -> str:
        return subprocess.run(['git', *args], cwd=tmp_path, text=True, capture_output=True, check=True).stdout

    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'frontend').mkdir()
    cache = tmp_path / 'frontend/node_modules'
    if tracked_kind == 'symlink':
        cache.symlink_to('/nonexistent/test-cache')
    else:
        cache.write_text('old tracked cache')
    (tmp_path / '.gitignore').write_text('')
    (tmp_path / 'unrelated.py').write_text('baseline')
    git('add', '.')
    git('commit', '-qm', 'baseline')
    before = git('rev-parse', 'HEAD')
    git('rm', '--cached', '--', 'frontend/node_modules')
    cache.unlink()
    cache.mkdir()
    (cache / 'cached.js').write_text('keep local cache')
    (tmp_path / '.gitignore').write_bytes(b'node_modules\r\n')
    (tmp_path / 'unrelated.py').write_text('unfinished staged work')
    git('add', 'unrelated.py')
    hook = tmp_path / '.git/hooks/pre-commit'
    hook.write_text('#!/bin/sh\nprintf ran > .git/hook-ran\nexit ' + ('1' if hook_fails else '0') + '\n')
    hook.chmod(0o755)
    monkeypatch.setattr(commit_workflow, 'run_checks', lambda *args, **kwargs: (True, ''))
    selected_paths = ('.gitignore', 'frontend/node_modules')
    if hook_fails:
        with pytest.raises(CommitError):
            commit_workflow.commit_git_revision(tmp_path, message='stop tracking cache', paths=selected_paths, push=False)
        assert git('rev-parse', 'HEAD') == before
        assert 'frontend/node_modules' in git('diff', '--cached', '--name-only')
    else:
        assert commit_workflow.commit_git_revision(tmp_path, message='stop tracking cache', paths=selected_paths, push=False)['status'] == 'SUCCESS'
        assert set(git('show', '--format=', '--name-only', 'HEAD').splitlines()) == {'.gitignore', 'frontend/node_modules'}
        assert git('diff', '--cached', '--name-only').strip() == 'unrelated.py'
        assert git('show', ':unrelated.py') == 'unfinished staged work'
        assert subprocess.check_output(['git', 'show', 'HEAD:.gitignore'], cwd=tmp_path) == b'node_modules\r\n'
    assert (tmp_path / '.git/hook-ran').read_text() == 'ran'
    assert (cache / 'cached.js').read_text() == 'keep local cache'


@pytest.mark.parametrize('paths', [(), ('app.py',)])
def test_git_status_error_blocks_before_publication(tmp_path, monkeypatch, paths):
    from cli.lib import commit_workflow

    monkeypatch.setattr(commit_workflow, 'run_git', Mock(return_value=subprocess.CompletedProcess([], 1, '', 'index unreadable')))
    with pytest.raises(CommitError, match='index unreadable'):
        commit_workflow.commit_git_revision(tmp_path, message='publish', paths=paths)


@pytest.mark.parametrize("scoped", [False, True])
def test_initial_git_commit_checks_new_files_and_preserves_other_staging(tmp_path, monkeypatch, scoped):
    from cli.lib import commit_workflow
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout
    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    (tmp_path / "app.py").write_text("print('hello')\n")
    (tmp_path / "other.txt").write_text("unrelated\n")
    git("add", "other.txt")
    checks = []
    monkeypatch.setattr(commit_workflow, "run_checks", lambda repo, **kw: (checks.append(kw) or (True, "")))
    result = commit_workflow.commit_git_revision(tmp_path, message="initial", push=False, paths=("app.py",) if scoped else ())
    assert result["status"] == "SUCCESS"
    assert checks == [{
        "paths": ["app.py"] if scoped else ["app.py", "other.txt"],
        "full": False,
    }]
    assert git("ls-tree", "--name-only", "HEAD").splitlines() == (["app.py"] if scoped else ["app.py", "other.txt"])
    if scoped:
        assert git("diff", "--cached", "--name-only").strip() == "other.txt"


def test_checkpoint_uses_git_even_with_legacy_metadata(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    with (
        patch("cli.lib.commit_workflow.commit_git_revision", return_value={"status": "SKIP"}) as commit,
        patch("cli.lib.commit_workflow.repo_lock"),
    ):
        assert commit_workflow.commit_repo(tmp_path, message="checkpoint", skip_checks=True) == {"status": "SKIP"}
    commit.assert_called_once_with(tmp_path, message="checkpoint", task_id="", push=False, skip_checks=True, paths=())


def test_retired_vcs_command_and_bookmark_option_are_absent() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Jujutsu" not in result.stdout
    rejected = runner.invoke(app, ["jj", "status"])
    assert rejected.exit_code == 2
    assert "No such command" in rejected.output
    help_result = runner.invoke(app, ["commit", "--help"])
    assert "--bookmark" not in help_result.stdout
