"""Retain source/wheel/installed-module identity without invoking commands."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

PROJECTS = Path('/srv/workspaces/projects')
SUMMITFLOW = PROJECTS / 'summitflow'
PACKAGES = [
    ('code-intelligence', 'code_intelligence', PROJECTS / 'code-intelligence/code_intelligence'),
    ('summitflow-st-sdk', 'st_sdk', SUMMITFLOW / 'packages/st-sdk/st_sdk'),
    ('agent-hub-st', 'agent_hub_st', PROJECTS / 'agent-hub/packages/st-cli/agent_hub_st'),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('python', help='Installed environment interpreter')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = {'python': args.python, 'packages': []}
    for distribution, module, source in PACKAGES:
        probe = subprocess.run(
            [args.python, '-c', f'import importlib.util; print(importlib.util.find_spec({module!r}).origin)'],
            cwd='/tmp', capture_output=True, text=True, check=True,
        )
        installed = Path(probe.stdout.strip()).parent
        wheel = SUMMITFLOW / 'docker/workspace-packages' / f'{distribution.replace("-", "_")}-0.1.0-py3-none-any.whl'
        rows = []
        with zipfile.ZipFile(wheel) as archive:
            for path in sorted(source.rglob('*.py')):
                relative = path.relative_to(source)
                source_bytes = path.read_bytes()
                wheel_bytes = archive.read(f'{module}/{relative.as_posix()}')
                installed_bytes = (installed / relative).read_bytes()
                rows.append({
                    'path': relative.as_posix(), 'source_sha256': sha(source_bytes),
                    'wheel_sha256': sha(wheel_bytes), 'installed_sha256': sha(installed_bytes),
                    'match': source_bytes == wheel_bytes == installed_bytes,
                })
        result['packages'].append({
            'distribution': distribution, 'source': str(source), 'installed': str(installed),
            'wheel': str(wheel), 'wheel_sha256': sha(wheel.read_bytes()), 'files': rows,
        })
    result['all_match'] = all(row['match'] for package in result['packages'] for row in package['files'])
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'all_match': result['all_match'], 'files': sum(len(p['files']) for p in result['packages'])}))
    if not result['all_match']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
