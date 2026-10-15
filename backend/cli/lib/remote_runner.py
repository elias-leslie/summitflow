"""Offload heavy checks to the Proxmox CI runner while the workstation is busy.

The runner mirrors workstation paths (/srv/workspaces/projects/<project>) so
resolved tool paths stay valid. Each run pushes a snapshot commit of the
working tree (tracked + untracked, honoring .gitignore), checks it out on the
runner, installs locked dependencies when lockfiles changed, runs the command
under the runner's own environment (its own Postgres), and returns only the
exit code and output. Any transport failure falls back to local execution.

The runner is reached with its own key (``ST_CI_RUNNER_KEY``, default
~/.ssh/id_ed25519_st_ci_runner, pinned to the workstation address in the runner
user's authorized_keys), never the owner's Proxmox root key or the keyring agent.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.utils.heavy_work import admission_state, lane_activity

DEFAULT_RUNNER = "kasadis@192.168.86.235"
DEFAULT_KEY = Path.home() / ".ssh" / "id_ed25519_st_ci_runner"
# Projects whose test environment the runner provisions (scripts/ci-runner).
DEFAULT_PROJECTS = ("summitflow",)
# Only the test-shaping variables cross over; secrets stay on the workstation.
FORWARDED_ENV = ("CI", "NODE_ENV", "PYTEST_ADDOPTS", "NO_COLOR", "TERM", "COLUMNS")
TRANSPORT_FAILURE = 255


class RunnerUnavailable(RuntimeError):
    """The runner could not take the job; run it locally."""


@dataclass(frozen=True)
class Runner:
    target: str
    key: Path
    projects: tuple[str, ...]

    def ssh_args(self, *, timeout: int = 5) -> list[str]:
        control = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "st-ci-runner-%C"
        return ["ssh", "-i", str(self.key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=yes", "-o", "ControlMaster=auto",
                "-o", f"ControlPath={control}", "-o", "ControlPersist=120"]


def configured(environ: Mapping[str, str] | None = None) -> Runner | None:
    values = os.environ if environ is None else environ
    target = values.get("ST_CI_RUNNER", "").strip() or DEFAULT_RUNNER
    if target.lower() in {"0", "off", "none", "local"}:
        return None
    key = Path(values.get("ST_CI_RUNNER_KEY", "").strip() or DEFAULT_KEY)
    projects = tuple(p for p in values.get("ST_CI_RUNNER_PROJECTS", "").replace(",", " ").split() if p)
    return Runner(target, key, projects or DEFAULT_PROJECTS) if key.is_file() else None


_reachable: dict[str, bool] = {}


def reachable(runner: Runner) -> bool:
    if runner.target not in _reachable:
        try:
            result = subprocess.run([*runner.ssh_args(timeout=2), runner.target, "true"],
                                    capture_output=True, timeout=6, check=False)
            _reachable[runner.target] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _reachable[runner.target] = False
    return _reachable[runner.target]


def offload_reason(project_root: Path, environ: Mapping[str, str] | None = None) -> tuple[Runner, str] | None:
    """The runner and why this heavy job should leave the workstation, or None."""
    runner = configured(environ)
    if runner is None or project_root.name not in runner.projects:
        return None
    admission = admission_state()
    if not admission.admit:
        reason = f"workstation admission closed ({admission.reason})"
    elif busy := lane_activity("heavy"):
        reason = f"heavy lane busy ({busy[0].get('label', 'unknown')})"
    else:
        return None
    return (runner, reason) if reachable(runner) else None


def _git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def snapshot_commit(root: Path) -> str:
    """Commit object for the working tree without touching the real index or refs."""
    with tempfile.TemporaryDirectory(prefix="st-ci-index-") as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(root, "read-tree", "HEAD", env=index)
        _git(root, "add", "-A", env=index)
        tree = _git(root, "write-tree", env=index)
    identity = {"GIT_AUTHOR_NAME": "st ci runner", "GIT_AUTHOR_EMAIL": "st-ci@localhost",
                "GIT_COMMITTER_NAME": "st ci runner", "GIT_COMMITTER_EMAIL": "st-ci@localhost"}
    # Orphan commit: only the tree crosses the wire, never repository history.
    return _git(root, "commit-tree", tree, "-m", "st ci runner snapshot", env=identity)


def _remote(runner: Runner, script: str, *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*runner.ssh_args(), runner.target, f"bash -c {shlex.quote(script)}"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, check=False)


SNAPSHOT_REF = "refs/st-ci/snapshot"
BASE_REF = "refs/st-ci/runner-base"


def _sync(runner: Runner, root: Path) -> str:
    """Ship the snapshot as a git bundle the runner fetches; never a publication push."""
    commit = snapshot_commit(root)
    _git(root, "update-ref", SNAPSHOT_REF, commit)
    path = shlex.quote(str(root))
    probe = _remote(runner, f"git init -q {path} >/dev/null && git -C {path} rev-parse -q --verify {BASE_REF} || true")
    if probe.returncode != 0:
        raise RunnerUnavailable(f"runner repo unavailable: {probe.stderr.strip()[:200]}")
    remote_base = probe.stdout.strip()
    try:
        local_base = _git(root, "rev-parse", "-q", "--verify", BASE_REF)
    except subprocess.CalledProcessError:
        local_base = ""
    # Send only objects the runner lacks; the last synced snapshot is the basis.
    exclude = [f"^{local_base}"] if local_base and local_base == remote_base and local_base != commit else []
    if local_base == commit == remote_base:
        return commit
    bundle = subprocess.run(["git", "-C", str(root), "bundle", "create", "-", SNAPSHOT_REF, *exclude],
                            capture_output=True, check=False)
    if bundle.returncode != 0:
        raise RunnerUnavailable(f"snapshot bundle failed: {bundle.stderr.decode(errors='replace')[:200]}")
    receive = (f"cat > /srv/ci/{shlex.quote(root.name)}.bundle && "
               f"git -C {path} fetch -q /srv/ci/{shlex.quote(root.name)}.bundle +{SNAPSHOT_REF}:{BASE_REF}")
    fetched = subprocess.run([*runner.ssh_args(), runner.target, f"bash -c {shlex.quote(receive)}"],
                             input=bundle.stdout, capture_output=True, check=False)
    if fetched.returncode != 0:
        raise RunnerUnavailable(f"runner fetch failed: {fetched.stderr.decode(errors='replace')[:200]}")
    _git(root, "update-ref", BASE_REF, commit)
    return commit


def _locks_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("backend/uv.lock", "backend/pyproject.toml", "pnpm-lock.yaml", "package.json",
                 "frontend/package.json", "frontend/pnpm-lock.yaml", "uv.lock", "pyproject.toml"):
        path = root / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def _prepare_script(root: Path, commit: str) -> str:
    from .cleanroom import plan_dependency_installs

    path = shlex.quote(str(root))
    marker = shlex.quote(f"/srv/ci/deps-{root.name}-{_locks_digest(root)}")
    installs = " && ".join(
        f"(cd {shlex.quote(str(cwd))} && {shlex.join(command)})" for command, cwd in plan_dependency_installs(root, ())
    ) or "true"
    # Keep installed environments across runs; remove everything else untracked.
    return (f"cd {path} && git checkout -qf --detach {commit} && "
            "git clean -qfdx -e .venv -e node_modules -e '**/.venv' -e '**/node_modules' && "
            f"if [ ! -e {marker} ]; then ({installs}) >&2 && rm -f /srv/ci/deps-{shlex.quote(root.name)}-* && touch {marker}; fi")


def run(
    runner: Runner,
    root: Path,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float | None = None,
    fetch: Sequence[Path] = (),
) -> subprocess.CompletedProcess[str]:
    """Run on the runner and return its result; RunnerUnavailable means run locally."""
    started = time.monotonic()
    commit = _sync(runner, root)
    forwarded = " ".join(f"{key}={shlex.quote(env[key])}" for key in FORWARDED_ENV if key in env)
    local_path = os.environ.get("PATH", "")
    project_paths = [entry for entry in env.get("PATH", "").split(":")
                     if entry and entry.startswith(str(root)) and entry not in local_path.split(":")]
    path_prefix = ":".join([*project_paths, "$HOME/.local/bin", "/usr/local/bin"])
    script = (
        f"set -o pipefail; exec 9>/srv/ci/locks/{shlex.quote(root.name)}.lock && flock 9 && "
        f"export PATH={path_prefix}:$PATH && {_prepare_script(root, commit)} && "
        f"set -a && . $HOME/.env.local && set +a && "
        # Project-owned hook, e.g. bootstrap/migrate the runner's test database.
        f"{{ [ ! -x scripts/ci-runner/prepare.sh ] || scripts/ci-runner/prepare.sh >&2; }} && "
        f"cd {shlex.quote(str(cwd))} && "
        f"env {forwarded} {shlex.join(command)}"
    )
    try:
        result = _remote(runner, script, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RunnerUnavailable("runner job timed out") from exc
    if result.returncode == TRANSPORT_FAILURE:
        raise RunnerUnavailable(f"runner transport failed: {result.stderr.strip()[:200]}")
    for path in fetch:
        subprocess.run(["scp", "-q", *runner.ssh_args()[1:], f"{runner.target}:{path}", str(path)],
                       capture_output=True, check=False)
    print(f"[st] ran on CI runner {runner.target.split('@')[-1]} in {time.monotonic() - started:.1f}s",
          file=sys.stderr, flush=True)
    return result
