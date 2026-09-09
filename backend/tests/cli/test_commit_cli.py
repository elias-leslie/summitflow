from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from cli.lib import jj
from cli.lib.commit_workflow import CommitError, commit_repo
from cli.main import app

runner = CliRunner()


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
    assert calls == [{"paths": ["docs/note.md"]}]
    assert git("show", "--format=", "--name-only", "HEAD").strip() == "docs/note.md"
    assert git("diff", "--cached", "--name-only").strip() == "unrelated.py"


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
        "change_id": "change",
        "commit_id": "commit",
        "bookmark": "task/task-1",
        "operation_id": "op",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "--message", "test", "--task", "task-1"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="task-1",
        push=True,
        skip_checks=False,
        bookmark="",
        paths=(),
    )
    mock_log.assert_called_once_with(
        "task-1",
        "st commit change=change commit=commit bookmark=task/task-1 op=op pushed=true",
    )
    assert "COMMIT[1]:status=SUCCESS pushed=true detail=commit" in result.stdout


def test_commit_repo_rejects_publish_with_skipped_checks(tmp_path: Path) -> None:
    with pytest.raises(CommitError, match="refusing to publish with --skip-checks"):
        commit_repo(tmp_path, message="test", push=True, skip_checks=True)


def test_commit_repo_prunes_safe_residue_after_publish(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()
    with (
        patch(
            "cli.lib.commit_workflow.commit_current_revision",
            return_value={"repo": "repo", "status": "SUCCESS", "pushed": True},
        ),
        patch(
            "cli.commands.cleanup_handlers.cleanup_safe_git_residue",
            return_value=(0, 0, 0, 0, 1, 2),
        ) as cleanup,
    ):
        result = commit_repo(tmp_path, message="test", push=True)

    cleanup.assert_called_once_with([tmp_path], dry_run=False)
    assert result["residue_pruned"] == 3
    assert result["residue_pruned_counts"]["task_local"] == 1
    assert result["residue_pruned_counts"]["task_remote"] == 2


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
        "change_id": "change",
        "commit_id": "commit",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "-m", "test", "--path", "a.py", "--path", "b.py"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="",
        push=True,
        skip_checks=False,
        bookmark="",
        paths=("a.py", "b.py"),
    )


def test_st_commit_help_shows_repeated_paths_form() -> None:
    result = runner.invoke(app, ["commit", "--help"])

    assert result.exit_code == 0
    assert "--paths a --paths b" in result.stdout


@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_forwards_explicit_bookmark(
    mock_current_repo: MagicMock,
    mock_commit_repo: MagicMock,
) -> None:
    mock_current_repo.return_value = Path("/repo")
    mock_commit_repo.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "change_id": "change",
        "commit_id": "commit",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "-m", "test", "--bookmark", "main"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="",
        push=True,
        skip_checks=False,
        bookmark="main",
        paths=(),
    )


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
        patch.object(commit_workflow, "publish_git", return_value={"status": "SUCCESS", "pushed": True, "publication_complete": True}),
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

    def fake_run_git(_repo: Path, args: list[str]):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if args[:2] == ["status", "--porcelain"]:
            result.stdout = " M a.py\n"
        if args[:2] == ["diff", "--cached"] and "--quiet" in args:
            result.returncode = 1  # has staged changes
        if args[:1] == ["check-ignore"]:
            # default: not ignored (exit 1 means no match)
            result.returncode = 1
        if args[:2] == ["rev-parse", "HEAD"]:
            result.stdout = "abc1234"
        if args[:1] == ["push"]:
            result.stdout = "pushed"
        return result

    with (
        patch.object(commit_workflow, "run_git", side_effect=fake_run_git) as run,
        patch.object(commit_workflow, "run_checks", return_value=(True, "")),
        patch.object(commit_workflow, "publish_git", return_value={"status": "SUCCESS", "pushed": True, "publication_complete": True}),
        patch(
            "cli.commands.cleanup_handlers.cleanup_safe_git_residue",
            return_value=(0, 0, 0, 0, 0, 0),
        ),
    ):
        result = commit_repo(tmp_path, message="scoped", paths=("a.py",), push=True)

    assert result["status"] == "SUCCESS"
    assert result["selected_paths"] == ["a.py"]
    add_calls = [c for c in run.call_args_list if c.args[1][:1] == ["add"]]
    assert add_calls, "expected git add to be called"
    assert add_calls[0].args[1] == ["add", "--", "a.py"], "git add must be scoped, not -A"


def test_jj_run_checks_scopes_changed_files_for_selected_paths(tmp_path: Path) -> None:
    with patch("cli.lib.jj.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""

        ok, detail = jj.run_checks(tmp_path, paths=("frontend/a.tsx", "backend/b.py"))

    assert ok is True
    assert detail == "ok"
    env = run.call_args.kwargs["env"]
    assert env["ST_CHECK_CHANGED_FILES"] == "frontend/a.tsx\nbackend/b.py"


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


def test_refresh_symbols_after_publish_skips_unpushed_result() -> None:
    from cli.lib.commit_workflow import _refresh_symbols_after_publish

    with patch("cli.client.STClient") as client_cls:
        result = _refresh_symbols_after_publish(Path("/repo"), _publish_result(pushed=False))

    assert "symbol_refresh_queued" not in result
    client_cls.assert_not_called()


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


def test_publication_checks_include_vitest(tmp_path):
    from cli.lib import commit_workflow
    with patch.object(commit_workflow.subprocess, 'run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, 'ok', '')
        assert commit_workflow.run_checks(tmp_path, paths=['frontend/a.tsx'])[0]
    assert run.call_args.args[0] == ['st', 'check', '--check', '--changed-only']


def test_outgoing_scope_includes_previously_committed_files(tmp_path):
    from cli.lib import commit_workflow
    with patch.object(commit_workflow, 'run_git') as run:
        run.side_effect = [subprocess.CompletedProcess([], 0, 'main\n', ''),
                           subprocess.CompletedProcess([], 0, 'a'*40, ''),
                           subprocess.CompletedProcess([], 0, 'backend/old.py\0frontend/new.tsx\0', '')]
        assert commit_workflow.outgoing_paths(tmp_path) == ['backend/old.py', 'frontend/new.tsx']


def test_clean_ahead_failed_gate_does_not_push(tmp_path):
    from cli.lib import commit_workflow
    with (patch.object(commit_workflow, 'dirty', return_value=False),
          patch.object(commit_workflow, 'outgoing_paths', return_value=['backend/a.py']),
          patch.object(commit_workflow, 'run_checks', return_value=(False, 'test failed')),
          patch.object(commit_workflow, 'publish_git') as publish):
        result = commit_workflow.commit_git_revision(tmp_path, message='resume')
    assert result['status'] == 'BLOCKED'
    publish.assert_not_called()


def test_cli_pending_ci_returns_nonzero_and_prints_revision():
    with (patch('cli.main.current_repo', return_value=Path('/repo')),
          patch('cli.main.commit_repo', return_value={'status': 'PENDING', 'pushed': True, 'sha': 'abc',
                'publication_complete': False, 'ci': {'state': 'pending', 'sha': 'abc', 'checks': []}})):
        result = runner.invoke(app, ['commit', '-m', 'resume'])
    assert result.exit_code == 2
    assert 'CI:state=pending sha=abc' in result.stdout


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


def test_outgoing_scope_uses_publish_destination_when_upstream_is_elsewhere(tmp_path):
    from cli.lib import commit_workflow

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q', '--initial-branch=main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'app.py').write_text('before')
    git('add', '.')
    git('commit', '-qm', 'baseline')
    git('remote', 'add', 'origin', '/tmp/unused-origin.git')
    git('remote', 'add', 'elsewhere', '/tmp/unused-elsewhere.git')
    git('update-ref', 'refs/remotes/origin/main', 'HEAD')
    (tmp_path / 'app.py').write_text('unpublished change')
    git('add', '.')
    git('commit', '-qm', 'ahead of publication remote')
    git('update-ref', 'refs/remotes/elsewhere/main', 'HEAD')
    git('branch', '--set-upstream-to=elsewhere/main')
    assert commit_workflow.outgoing_paths(tmp_path) == ['app.py']


@pytest.mark.parametrize('paths', [(), ('app.py',)])
def test_git_status_error_blocks_before_publication(tmp_path, monkeypatch, paths):
    from cli.lib import commit_workflow

    monkeypatch.setattr(commit_workflow, 'run_git', Mock(return_value=subprocess.CompletedProcess([], 1, '', 'index unreadable')))
    monkeypatch.setattr(commit_workflow, 'outgoing_paths', lambda _: [])
    publish = Mock()
    monkeypatch.setattr(commit_workflow, '_publish_revision', publish)
    with pytest.raises(CommitError, match='index unreadable'):
        commit_workflow.commit_git_revision(tmp_path, message='publish', paths=paths)
    publish.assert_not_called()
