"""Real Vitest config loading keeps acceptance's borrowed dependencies read-only."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from app.utils.heavy_work import heavy_work
from cli.commands.done_task_acceptance import _sandbox_command


def test_isolated_vitest_loads_esm_config_with_pnpm_store_shim() -> None:
    project = Path(__file__).resolve().parents[3]
    backend = project / "backend"
    store = project / "node_modules" / ".pnpm"
    vitest = (project / "frontend" / "node_modules" / "vitest").resolve()
    vite = (project / "frontend" / "node_modules" / "vite").resolve()
    if not shutil.which("bwrap") or not vitest.is_dir() or not vite.is_dir():
        pytest.skip("Installed managed isolation and prepared frontend tools required")
    assert vitest.is_relative_to(store) and vite.is_relative_to(store)
    with tempfile.TemporaryDirectory(dir=os.environ.get("ST_NATIVE_TMP_HOST_ROOT", "/var/tmp")) as directory:
        fixture = Path(directory)
        repo = fixture / "project"
        source = fixture / "accepted"
        repo.mkdir()
        source.mkdir()
        (source / ".git").mkdir()
        package = {"type": "module", "scripts": {"test": "vitest run"}}
        config = "export default { test: { include: ['isolation.test.ts'] } }\n"
        for root in (repo, source):
            (root / "package.json").write_text(json.dumps(package))
            (root / "vitest.config.ts").write_text(config)
        protected_source = fixture / "protected-source.ts"
        protected_source.write_text("host source\n")
        test = (
            "import { expect, test } from 'vitest'\n"
            "import { writeFileSync } from 'node:fs'\n"
            "test('dependencies stay read-only', () => {\n"
            "  expect(() => writeFileSync('node_modules/vitest/package.json', '{}')).toThrow(/read-only/)\n"
            "  expect(() => writeFileSync('node_modules/.pnpm/forbidden-write', 'changed')).toThrow(/read-only/)\n"
            "})\n"
        )
        (source / "isolation.test.ts").write_text(test)
        modules = fixture / "dependencies"
        (modules / ".pnpm").mkdir(parents=True)
        (modules / ".bin").mkdir()
        (modules / ".vite-temp").mkdir()
        for name, path in (("vitest", vitest), ("vite", vite)):
            (modules / name).symlink_to(Path(".pnpm") / path.relative_to(store), target_is_directory=True)
        launch = Path(".pnpm") / vitest.relative_to(store) / "vitest.mjs"
        shim = modules / ".bin" / "vitest"
        shim.write_text(f'#!/bin/sh\nbasedir=${{0%/*}}\nexec node "$basedir/../{launch}" "$@"\n')
        shim.chmod(0o755)
        (source / "node_modules").mkdir()
        temporary = fixture / "run"
        temporary.mkdir()
        command = _sandbox_command(
            repo, source, source / ".git", repo / ".git", temporary,
            [(modules, repo / "node_modules"), (store, repo / "node_modules" / ".pnpm")],
            "fixture", (), "fixture", False,
        )
        probe = (
            "import errno\nfrom pathlib import Path\nimport sys\n"
            f"sys.path.insert(0, {str(backend)!r})\n"
            "from cli.commands import check\n"
            f"root=Path({str(repo)!r})\n"
            "check._resolve_repo_root=lambda:root\n"
            "check.run_architecture_check=lambda *args,**kwargs:0\n"
            "check.run_project_identity_check=lambda *args,**kwargs:0\n"
            "config={'label':'VITEST','binary':'vitest','args':'run','working_dir':'.'}\n"
            "status=check._run_selected(['vitest'], {'vitest':config}, fix=False, changed_only=False)\n"
            "for details in root.glob('.dev-tools/vitest-*-details.txt'):\n    print(details.read_text())\n"
            "assert status == 0, 'isolated Vitest failed to load config and execute its test'\n"
            f"for protected in [Path({str(modules / '.bin' / 'vitest')!r}),Path({str(protected_source)!r})]:\n"
            "    try:\n        protected.write_text('unapproved host change')\n"
            "    except OSError as exc:\n        assert exc.errno in {errno.EROFS, errno.EACCES}\n"
            "    else:\n        raise AssertionError('Host source or dependencies became writable')\n"
            "(root/'vitest.config.ts').write_text('disposable accepted source change')\n"
            "assert not list((root/'node_modules/.vite-temp').iterdir())\n"
        )
        with heavy_work("isolated Vitest regression") as work:
            result = work.run(
                [*command[:command.index("--") + 1], sys.executable, "-P", "-c", probe],
                capture_output=True, text=True, check=False, timeout=20,
            )
        assert result.returncode == 0, result.stdout + result.stderr
        assert (repo / "vitest.config.ts").read_text() == config
        assert (source / "vitest.config.ts").read_text() == "disposable accepted source change"
        assert protected_source.read_text() == "host source\n"
        assert shim.read_text().startswith("#!/bin/sh\n")
        assert not (store / "forbidden-write").exists()
