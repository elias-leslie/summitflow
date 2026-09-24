"""Read-only capture of installed extension help and owner-defined help."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PROJECTS = Path('/srv/workspaces/projects')
SUMMITFLOW = PROJECTS / 'summitflow'
OUT = SUMMITFLOW / '.dev-tools/st-help-review/extensions'
REGISTRY = json.loads((SUMMITFLOW / 'scripts/lib/tool-registry.json').read_text())

APP_IMPORTS = {
    'neri': 'from app.st_cli.neri import app',
    'learn': 'from app.st_cli.learn import app',
    'jobs': 'from app.st_cli.jobs import app',
    'portfolio': 'from app.st_cli.portfolio import app',
    'ui': 'from desktop_automation.ui import app',
    'selection': 'from desktop_automation.selection import app',
    'wiki': 'from vault_tools.wiki import app',
    'browser': 'from browser_automation.cli import app',
    'graph': 'from code_intelligence.cli.graph import app',
    'search': 'from code_intelligence.cli.search import app',
    'design': 'from design_tools.commands.design import app',
}


def run(argv: list[str], cwd: Path, timeout: int = 40) -> dict:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return {'argv': argv, 'cwd': str(cwd), 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired as exc:
        return {'argv': argv, 'cwd': str(cwd), 'error': f'timeout after {timeout}s',
                'stdout': (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or '',
                'stderr': (exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''}


def argparse_help(import_line: str, constructor: str) -> str:
    return f'''import argparse, json
{import_line}
root = {constructor}
result = {{}}
def visit(parser, path):
    result[path] = parser.format_help()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                visit(child, (path + ' ' + name).strip())
visit(root, '')
print(json.dumps({{'help': result, 'usage': []}}))'''


for entry in REGISTRY['extensions']:
    name = entry['namespace']
    owner = entry['owner']
    root = PROJECTS / owner
    venv = 'backend/.venv/bin/python' if (root / 'backend/.venv/bin/python').exists() else '.venv/bin/python'
    python = str(root / venv)
    manifest_path = SUMMITFLOW / 'scripts/lib' / entry['manifest']
    manifest = json.loads(manifest_path.read_text())
    if owner == 'agent-hub' and name != 'web':
        script = f'''import json
from st_sdk.runtime import describe_app
from agent_hub_st.__main__ import OWNED_APPS
print(json.dumps(describe_app(OWNED_APPS[{name!r}], {name!r})))'''
    elif name in APP_IMPORTS:
        namespace = 'st.browser' if name == 'browser' else ('code-graph' if name == 'graph' else 'code-search' if name == 'search' else name)
        script = f'''import json
from st_sdk.runtime import describe_app
{APP_IMPORTS[name]}
print(json.dumps(describe_app(app, {namespace!r})))'''
    elif name == 'web':
        script = argparse_help('from app.cli.web_research import _build_parser', '_build_parser()')
    elif name == 'slopminer':
        script = argparse_help('from slopminer.cli import parser', 'parser()')
    else:
        raise RuntimeError(f'no source help extractor for {name}')
    owner_run = run([python, '-c', script], root)
    described = None
    if owner_run.get('returncode') == 0:
        try:
            described = json.loads(owner_run['stdout'])
        except json.JSONDecodeError:
            pass
    installed_run = run(['st', name, '--help'], SUMMITFLOW)
    revision = run(['git', 'rev-parse', 'HEAD'], root)
    status = run(['git', 'status', '--porcelain', '--untracked-files=no'], root)
    capture = {
        'namespace': name, 'owner': owner, 'owner_root': str(root),
        'manifest_path': str(manifest_path),
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'owner_revision': revision['stdout'].strip(),
        'owner_dirty_tracked_paths': status['stdout'].splitlines(),
        'owner_description': described,
        'owner_capture': owner_run,
        'installed_root_help': installed_run,
        'installed_manifest_help': manifest['help'],
        'installed_manifest_usage': manifest.get('usage', []),
        'installed_manifest_summary': manifest.get('summary'),
        'installed_manifest_effects': manifest.get('effects', []),
    }
    (OUT / f'{name}.json').write_text(json.dumps(capture, indent=2, ensure_ascii=False) + '\n')
    print(name, 'owner', owner_run.get('returncode', owner_run.get('error')),
          'installed', installed_run.get('returncode', installed_run.get('error')),
          'paths', len(described['help']) if described else '-')
