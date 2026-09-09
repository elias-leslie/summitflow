"""Persist server-advertised push ranges in Git metadata for CI reentry."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def push_scope(repo: Path, remote: str, branch: str, sha: str, summary: str = '') -> dict[str, Any] | None:
    """Unknown/new-branch/ambiguous pushes never borrow HEAD's parent as scope."""
    def git(*args: str) -> str:
        result = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True,
                                check=False, timeout=30)
        if result.returncode:
            raise ValueError('Git push scope unavailable')
        return result.stdout

    try:
        location = Path(git('rev-parse', '--git-path', 'st-publication').strip())
        if not location.is_absolute():
            location = repo / location
        key = hashlib.sha256(f'{remote}\0{branch}\0{sha}'.encode()).hexdigest()
        receipt = location / f'{key}.json'
        ranges = []
        for line in summary.splitlines():
            fields = line.split('\t')
            if len(fields) != 3 or fields[0] != ' ' or not fields[1].endswith(f':refs/heads/{branch}'):
                continue
            match = re.fullmatch(r'([0-9a-f]+)\.\.([0-9a-f]+)', fields[2])
            if match:
                before = git('rev-parse', '--verify', f'{match[1]}^{{commit}}').strip()
                after = git('rev-parse', '--verify', f'{match[2]}^{{commit}}').strip()
                if after == sha:
                    ranges.append(before)
        if ranges:
            if len(set(ranges)) != 1:
                return None
            before = ranges[0]
            count = int(git('rev-list', '--count', f'{before}..{sha}').strip())
            # GitHub runs filtered workflows unconditionally for >1000 commits.
            paths = None if count > 1000 else sorted(set(filter(None, git(
                'diff', '--no-renames', '--name-only', '-z', before, sha, '--').split('\0'))))
            evidence = {'remote': remote, 'branch': branch, 'sha': sha, 'before': before,
                        'paths': paths, 'commits': count, 'source': 'git_push_porcelain'}
            location.mkdir(parents=True, exist_ok=True)
            temporary = receipt.with_suffix('.tmp')
            temporary.write_text(json.dumps(evidence))
            temporary.replace(receipt)
            return evidence
        if receipt.exists():
            evidence = json.loads(receipt.read_text())
            if (evidence.get('remote'), evidence.get('branch'), evidence.get('sha')) == (remote, branch, sha):
                return evidence
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return None
