"""Push event scopes survive reentry and never collapse a multi-commit push."""
import subprocess

from cli.lib.publish_scope import push_scope
from cli.lib.workflow_filters import ordered_match


def test_ordered_github_paths():
    assert ordered_match('backend/api/x.py', ['backend/**', '!backend/api/**']) is False
    assert ordered_match('backend/api/x.py', ['backend/**', '!backend/api/**', 'backend/api/x.py']) is True
    assert ordered_match('readme.md', ['**/*.md']) is True
    assert ordered_match('deep/readme.md', ['*.md']) is False
    assert ordered_match('page.js', ['*.jsx?']) is True
    assert ordered_match('v12', ['v[0-9]+']) is True


def test_server_push_range_persists_multiple_commits(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Test')
    (tmp_path / 'base').write_text('base')
    git('add', '.')
    git('commit', '-qm', 'base')
    before = git('rev-parse', 'HEAD')
    (tmp_path / 'backend.py').write_text('changed')
    git('add', '.')
    git('commit', '-qm', 'backend')
    (tmp_path / 'docs.md').write_text('docs')
    git('add', '.')
    git('commit', '-qm', 'docs')
    sha = git('rev-parse', 'HEAD')
    summary = f' \t{sha}:refs/heads/main\t{before[:12]}..{sha[:12]}\n'
    first = push_scope(tmp_path, 'owner/repo', 'main', sha, summary)
    assert first is not None
    assert first['before'] == before
    assert first['paths'] == ['backend.py', 'docs.md']
    assert push_scope(tmp_path, 'owner/repo', 'main', sha) == first
    assert push_scope(tmp_path, 'owner/repo', 'other', sha) is None
    assert push_scope(tmp_path, 'other/repo', 'main', sha) is None
    assert push_scope(tmp_path, 'owner/repo', 'main', before) is None


def test_real_porcelain_capture_uses_server_before_not_stale_tracking(tmp_path):
    remote = tmp_path / 'remote.git'
    local = tmp_path / 'local'
    other = tmp_path / 'other'
    def git(cwd, *args):
        return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()
    git(tmp_path, 'init', '--bare', '-q', str(remote))
    git(tmp_path, 'clone', '-q', str(remote), str(local))
    for path in (local,):
        git(path, 'config', 'user.email', 'test@example.invalid')
        git(path, 'config', 'user.name', 'Test')
    (local / 'base').write_text('base')
    git(local, 'add', '.')
    git(local, 'commit', '-qm', 'base')
    git(local, 'branch', '-M', 'main')
    git(local, 'push', '-q', 'origin', 'main')
    git(tmp_path, 'clone', '-q', '-b', 'main', str(remote), str(other))
    git(other, 'config', 'user.email', 'test@example.invalid')
    git(other, 'config', 'user.name', 'Test')
    (other / 'remote-only').write_text('remote')
    git(other, 'add', '.')
    git(other, 'commit', '-qm', 'remote advance')
    before = git(other, 'rev-parse', 'HEAD')
    git(other, 'push', '-q', 'origin', 'main')
    # Fetch by object ID leaves origin/main stale; HEAD contains the actual server base.
    git(local, 'fetch', '-q', str(remote), before)
    git(local, 'merge', '-q', '--ff-only', 'FETCH_HEAD')
    (local / 'docs.md').write_text('docs')
    git(local, 'add', '.')
    git(local, 'commit', '-qm', 'docs')
    sha = git(local, 'rev-parse', 'HEAD')
    summary = subprocess.check_output(['git', 'push', '--porcelain', 'origin', f'{sha}:refs/heads/main'],
                                      cwd=local, text=True)
    result = push_scope(local, 'owner/repo', 'main', sha, summary)
    assert result is not None
    assert result['before'] == before
    assert result['paths'] == ['docs.md']
    assert push_scope(local, 'owner/repo', 'main', sha) == result
