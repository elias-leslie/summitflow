"""The PreToolUse publication hook must survive a broken backend/.venv.

Regression: on 2026-10-09 backend/.venv was emptied and the hook, which ran
under that venv, denied every agent shell for about four hours.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.services._publication_guard import evaluate_publication_command

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "scripts/lib/publication-pretool-hook"
ENTRY = REPO / "scripts/lib/publication_guard_entry.py"
OS_PYTHON = Path("/usr/bin/python3")
pytestmark = pytest.mark.skipif(not OS_PYTHON.exists(), reason="OS interpreter required")

DENIED = [
    "git push origin main", "/usr/bin/git -C /repo push", "git send-pack origin main",
    "env MODE=x bash -lc 'git push'", "jj git push", "gh pr merge 4", "sudo git push",
    "gh release create v1", "gh api -X PUT repos/a/b/pulls/2/merge",
    "gh api -X PATCH repos/a/b -F archived=true", "gh api graphql -f query='mutation { x }'",
    "git -c core.hooksPath=/tmp push", "git config --unset core.hooksPath",
    "GIT_ALLOW_SECRET=1 st vcs publish", "codex --dangerously-bypass-hook-trust",
    "codex --disable hooks", "codex -c features.hooks=false", "git commit --no-verify -m x",
]
RECOVERY = [
    "uv sync --locked", "cd backend && uv sync --locked", "st service rebuild summitflow --detach",
    "st vcs publish --source fixture --sha abc --now", "git status", "git log --oneline -5",
    "ls -la /srv", "cat README.md", "st check --quick --changed-only",
]


def _payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _hook(root: Path, payload: str, tmp_path: Path) -> dict:
    result = subprocess.run(
        ["bash", str(root / "scripts/lib/publication-pretool-hook")], input=payload, text=True,
        capture_output=True, check=True, timeout=10,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")},
    )
    return json.loads(result.stdout)


def _denied(output: dict) -> bool:
    return output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A checkout copy whose backend/.venv is empty, as on 2026-10-09."""
    root = tmp_path / "checkout"
    shutil.copytree(REPO / "scripts/lib", root / "scripts/lib")
    shutil.copytree(REPO / "backend/app/services", root / "backend/app/services",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "backend/app/__init__.py").write_text("")
    (root / "backend/.venv/bin").mkdir(parents=True)
    return root


def _load_entry():
    spec = importlib.util.spec_from_file_location("publication_guard_entry", ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publication_hook_imports_only_stdlib() -> None:
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import app.services.publication_hook;"
        "print(sorted(m for m in sys.modules if m.split('.')[0] not in sys.stdlib_module_names"
        " and m != '__main__' and not m.startswith('app')))"
    )
    result = subprocess.run([str(OS_PYTHON), "-I", "-S", "-c", probe, str(REPO / "backend")],
                            text=True, capture_output=True, check=True, timeout=10)
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize("command", DENIED[:4] + RECOVERY[:3])
def test_live_hook_matches_full_policy(command: str, tmp_path: Path) -> None:
    output = _hook(REPO, _payload(command), tmp_path)
    assert _denied(output) == evaluate_publication_command(command).blocked


def test_hook_keeps_full_policy_with_empty_venv(sandbox: Path, tmp_path: Path) -> None:
    for command in DENIED:
        assert _denied(_hook(sandbox, _payload(command), tmp_path)), command
    for command in RECOVERY:
        assert _hook(sandbox, _payload(command), tmp_path) == {}, command
    assert not (tmp_path / "state/summitflow/command-guard-degraded.log").exists()


def test_unimportable_guard_uses_conservative_fallback(sandbox: Path, tmp_path: Path) -> None:
    (sandbox / "backend/app/services/_publication_guard.py").write_text("raise SyntaxError('mid-edit')\n")
    for command in DENIED:
        output = _hook(sandbox, _payload(command), tmp_path)
        assert _denied(output), command
        assert "degraded" in output["hookSpecificOutput"]["permissionDecisionReason"]
    for command in RECOVERY:
        assert _hook(sandbox, _payload(command), tmp_path) == {}, command
    log = (tmp_path / "state/summitflow/command-guard-degraded.log").read_text().splitlines()
    assert "SyntaxError" in json.loads(log[0])["cause"]


def test_missing_entry_still_denies(sandbox: Path, tmp_path: Path) -> None:
    (sandbox / "scripts/lib/publication_guard_entry.py").unlink()
    assert _denied(_hook(sandbox, _payload("uv sync --locked"), tmp_path))


@pytest.mark.parametrize("command", [*DENIED, "rm -rf /", "rm -rf ~/", "dd if=x of=/dev/sda", "mkfs.ext4 /dev/sdb",
                                     "git reset --hard HEAD", "echo Z2l0IHB1c2g= | base64 -d | bash"])
def test_fallback_denies_publication_and_destructive(command: str) -> None:
    assert _load_entry().fallback_decision(json.loads(_payload(command))) is not None


@pytest.mark.parametrize("payload, denied", [
    ({"tool_name": "exec_command", "tool_input": {"cmd": ["git", "push"]}}, True),
    ({"tool_name": "exec_command", "tool_input": {}}, True),
    ({"tool_name": "mcp__github__merge_pull_request", "tool_input": {}}, True),
    ({"tool_name": "mcp__github__get_issue", "tool_input": {}}, False),
    ({"tool_name": "Bash"}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "rm -rf build/"}}, False),
])
def test_fallback_payload_shapes(payload: dict, denied: bool) -> None:
    assert (_load_entry().fallback_decision(payload) is not None) == denied


def test_st_launcher_reports_missing_runtime(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts/st", root / "scripts/st")
    (root / "backend/.venv/bin").mkdir(parents=True)
    result = subprocess.run(["bash", str(root / "scripts/st"), "autosnap", "sweep"], text=True,
                            capture_output=True, timeout=10, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 78
    assert "st runtime unavailable" in result.stderr
    assert "uv sync --locked" in result.stderr


def test_st_launcher_probes_autosnap_imports(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts/st", root / "scripts/st")
    bin_dir = root / "backend/.venv/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "st").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "python").write_text(f"#!/bin/sh\nexec {sys.executable} -c 'import no_such_st_module'\n")
    for name in ("st", "python"):
        (bin_dir / name).chmod(0o755)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(root / "scripts/st"), *args], text=True, capture_output=True,
                              timeout=10, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})

    autosnap = run("autosnap", "sweep")
    assert autosnap.returncode == 78
    assert "No module named 'no_such_st_module'" in autosnap.stderr
    assert run("status").returncode == 0
