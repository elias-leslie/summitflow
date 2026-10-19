"""Run acceptance tools the way the project's CI runs them.

CI starts from a clean runner: no host tools beyond what the workflow sets up,
only the workflow's declared environment, a fresh service database, and (where
pytest-randomly is installed) a random test order. Local acceptance mirrors
that so order- and host-dependent failures surface before publication, with a
printed seed that ``st check --ci-repro --seed N`` replays.

Projects without a CI workflow keep their existing environment: there is no CI
to match. ``st check --quick`` never enters this mode.
"""

from __future__ import annotations

import contextlib
import os
import pwd
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.transient_scratch import managed_temp_parent

PARITY_FLAG = "ST_CHECK_CI_PARITY"
SEED_VAR = "ST_CHECK_SEED"
# The runner image's base. /usr/local/bin is left out: on this host it holds
# st, uv and pnpm, which CI only has when the workflow sets them up.
SYSTEM_PATH = ("/usr/bin", "/bin")

# Tools a workflow's setup actions put on the runner's PATH.
_SETUP_ACTION_TOOLS = {
    "astral-sh/setup-uv": ("uv", "uvx"),
    "actions/setup-node": ("node", "npm", "npx", "corepack"),
    "pnpm/action-setup": ("pnpm",),
    "actions/setup-go": ("go", "gofmt"),
    "actions/setup-python": ("python3", "python"),
    "oven-sh/setup-bun": ("bun",),
    "dtolnay/rust-toolchain": ("cargo", "rustc"),
}
# Runner-image basics that live outside SYSTEM_PATH on this host.
_RUNNER_IMAGE_TOOLS = ("git",)
_UV_RUN_FLAGS = {"--locked", "--frozen", "--no-sync", "--all-extras", "--dev", "--offline", "--no-dev", "-q", "--quiet"}
_UV_RUN_VALUE_FLAGS = {"--extra", "--group", "--with", "--python", "-p", "--package", "--project", "--directory"}
_SERVICE_PORTS = {"postgres": 5432}
_EXPRESSION = re.compile(r"\$\{\{\s*([^}]*?)\s*\}\}")
_GATE = re.compile(r"\bcheck\s+--check\b")


class CiParityError(RuntimeError):
    """The workflow's CI environment cannot be reproduced locally."""


@dataclass
class CiJob:
    workflow: str
    name: str
    working_directory: str
    env: dict[str, str]
    services: dict[str, dict[str, Any]]
    setup: list[list[str]]
    tests: list[list[str]]
    tools: set[str] = field(default_factory=set)
    gate: bool = False  # a run step is the st gate (`st check --check`), which runs pytest itself


def canonical_tool_path(home: Path | None = None) -> str:
    """Binary lookup for acceptance plans, independent of the caller's PATH.

    The nightly worker, an owner shell and an agent shell all resolve the same
    tool, so a receipt one of them writes validates in the others.
    """
    # The account's home, not $HOME: isolated acceptance redirects HOME.
    home = home or Path(pwd.getpwuid(os.getuid()).pw_dir)
    return os.pathsep.join([str(home / ".local" / "bin"), "/usr/local/bin", *SYSTEM_PATH])


def which(name: str) -> str | None:
    return shutil.which(name, path=canonical_tool_path())


def container_cli() -> tuple[list[str], bool] | None:
    """The command that runs CI service containers, and whether it needs registry-qualified image names.

    Docker when this user can reach it. Else the user's own rootless podman service (service and agent
    users have no docker access, by design), reached over its socket: the podman.socket user unit runs it
    in the user's manager, outside a sandbox (the deploy gate's) that blocks the setuid uid-mapping
    helpers rootless podman needs. Podman resolves no short image names without a search-registry config.
    """
    docker = which("docker")
    if docker and ("DOCKER_HOST" in os.environ or os.access("/var/run/docker.sock", os.R_OK | os.W_OK)):
        return [docker], False
    podman, runtime = which("podman"), os.environ.get("XDG_RUNTIME_DIR")
    if podman and runtime:
        sock = Path(runtime) / "podman" / "podman.sock"
        # idempotent; a socket file alone may be left over from a stopped unit
        started = subprocess.run(["systemctl", "--user", "start", "podman.socket"], capture_output=True, timeout=60, check=False)
        if started.returncode == 0 and sock.exists():
            return [podman, "--remote", "--url", f"unix://{sock}"], True
    return ([docker], False) if docker else None


def qualified_image(image: str) -> str:
    """Docker Hub's implicit naming, spelled out: postgres:16 -> docker.io/library/postgres:16."""
    first, _, rest = image.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        return image
    return f"docker.io/{image}" if rest else f"docker.io/library/{image}"


def active(environ: Mapping[str, str] | None = None) -> bool:
    return (os.environ if environ is None else environ).get(PARITY_FLAG) == "1"


def seed(environ: Mapping[str, str] | None = None) -> int | None:
    value = (os.environ if environ is None else environ).get(SEED_VAR, "")
    return int(value) if value.isdigit() else None


def new_seed() -> int:
    return secrets.randbelow(2**32)


def _settings(root: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads((root / ".st-check.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return {}
    value = data.get("acceptance")
    return value if isinstance(value, dict) else {}


def _literal(value: Any, root: Path) -> str | None:
    """Workflow values usable locally: literals and the workspace path only."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if not isinstance(value, str):
        return None
    unresolved = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal unresolved
        if match[1] == "github.workspace":
            return str(root)
        unresolved = True
        return ""

    text = _EXPRESSION.sub(substitute, value)
    return None if unresolved else text


def _env(block: Any, root: Path) -> dict[str, str]:
    if not isinstance(block, dict):
        return {}
    values = {str(key): _literal(value, root) for key, value in block.items()}
    return {key: value for key, value in values.items() if value is not None}


def translate(command: str, root: Path, workdir: Path) -> list[str] | None:
    """`uv run X` / `.venv/bin/X` / `X` as the prepared local executable, without syncing."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or any(token in {"&&", "||", "|", ";"} for token in argv):
        return None
    if argv[:2] == ["uv", "run"]:
        index = 2
        while index < len(argv) and argv[index].startswith("-"):
            if argv[index] in _UV_RUN_VALUE_FLAGS:
                index += 2
            elif argv[index] in _UV_RUN_FLAGS or "=" in argv[index]:
                index += 1
            else:
                return None
        argv = argv[index:]
        if not argv:
            return None
        executable = workdir / ".venv" / "bin" / argv[0]
        return [str(executable), *argv[1:]] if executable.is_file() else None
    first = Path(argv[0])
    if "/" in argv[0]:
        executable = first if first.is_absolute() else workdir / first
        return [str(executable), *argv[1:]] if executable.is_file() else None
    local = workdir / ".venv" / "bin" / argv[0]
    return [str(local), *argv[1:]] if local.is_file() else None


def _is_pytest(argv: list[str]) -> bool:
    name = Path(argv[0]).name
    return name in {"pytest", "py.test"} or (name.startswith("python") and argv[1:3] == ["-m", "pytest"])


def _is_setup(step: Mapping[str, Any], command: str) -> bool:
    """Steps preparing the service database: migrations and role/database creation."""
    return (bool(re.search(r"\balembic\b.*\bupgrade\b|\b(createdb|createuser|psql|pg_restore)\b", command))
            or "migrat" in str(step.get("name") or "").lower())


def load_jobs(root: Path) -> list[CiJob]:
    import yaml

    jobs: list[CiJob] = []
    directory = root / ".github" / "workflows"
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]) if directory.is_dir() else []:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
            continue
        # PyYAML reads the bare `on:` key as boolean True.
        triggers = document.get("on", document.get(True))
        names = set(triggers) if isinstance(triggers, dict) else set(triggers) if isinstance(triggers, list) else {triggers}
        if not names & {"push", "pull_request", "workflow_call"}:
            continue
        for job_name, job in document["jobs"].items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                continue
            defaults = ((job.get("defaults") or {}).get("run") or {}) if isinstance(job.get("defaults"), dict) else {}
            working = str(defaults.get("working-directory") or ".")
            env = {**_env(document.get("env"), root), **_env(job.get("env"), root)}
            services = {str(name): spec for name, spec in (job.get("services") or {}).items() if isinstance(spec, dict)}
            tools = set(_RUNNER_IMAGE_TOOLS)
            setup: list[list[str]] = []
            tests: list[list[str]] = []
            gate = False
            for step in job["steps"]:
                if not isinstance(step, dict):
                    continue
                uses = str(step.get("uses") or "").split("@", 1)[0]
                tools.update(_SETUP_ACTION_TOOLS.get(uses, ()))
                command = step.get("run")
                if not isinstance(command, str):
                    continue
                gate = gate or bool(_GATE.search(command))
                step_dir = root / str(step.get("working-directory") or working)
                argv = translate(command.strip(), root, step_dir) if "\n" not in command.strip() else None
                if argv is None:
                    # Shell scripts are mirrored only as database setup.
                    if not tests and _is_setup(step, command):
                        step_env = [f"{key}={value}" for key, value in _env(step.get("env"), root).items()]
                        setup.append(["/usr/bin/env", *step_env, "bash", "-e", "-c", command])
                    continue
                if _is_pytest(argv):
                    if not tests:
                        # Steps may set their own working-directory instead of a job default.
                        working = str(step.get("working-directory") or working)
                    tests.append(argv)
                elif _is_setup(step, command) and not tests:
                    setup.append(argv)
            jobs.append(CiJob(path.name, str(job_name), working, env, services, setup, tests, tools, gate))
    return jobs


def pytest_job(root: Path, workdir: Path) -> CiJob | None:
    """The CI job that tests the same directory the local pytest gate runs in.

    CI that only calls the st gate runs pytest inside it, so that job's env
    and services still apply; it has no tests of its own to mirror.
    """
    jobs = load_jobs(root)
    for job in jobs:
        if job.tests and (root / job.working_directory).resolve() == workdir.resolve():
            return job
    return next((job for job in jobs if job.gate and not job.tests), None)


def has_ci(root: Path) -> bool:
    directory = root / ".github" / "workflows"
    return directory.is_dir() and any(directory.glob("*.y*ml"))


def admitted_tools(root: Path, job: CiJob | None) -> set[str]:
    """The job's setup tools; for tools outside a pytest job, every job's."""
    declared = _settings(root).get("host_tools", [])
    tools = set(job.tools) if job else {tool for each in load_jobs(root) for tool in each.tools}
    return {*_RUNNER_IMAGE_TOOLS, *tools, *(item for item in declared if isinstance(item, str))}


def environment(root: Path, *, tool_dirs: list[Path], job: CiJob | None, scratch: Path,
                base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Scrubbed CI-like env: workflow env, declared passthrough, CI tools only."""
    source = os.environ if base is None else base
    settings = _settings(root)
    admitted = admitted_tools(root, job)
    aliases = scratch / "bin"
    aliases.mkdir(parents=True, exist_ok=True)
    for name in sorted(admitted):
        found = which(name)
        if found and not (aliases / name).exists():
            (aliases / name).symlink_to(found)
    home = scratch / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
        "CI": "true", "GITHUB_ACTIONS": "true",  # runners leave TMPDIR unset
        "PATH": os.pathsep.join([*(str(path) for path in tool_dirs), str(aliases), *SYSTEM_PATH]),
    }
    # This host's pnpm is a corepack shim; its prepared cache is the runner's tool cache.
    corepack = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "node" / "corepack"
    if admitted & {"pnpm", "corepack"} and corepack.is_dir():
        env["COREPACK_HOME"] = str(corepack)
    env.update(job.env if job else {})
    env.update({key: str(value) for key, value in (settings.get("env") or {}).items() if isinstance(value, str)})
    for key in settings.get("pass_env", []):
        if isinstance(key, str) and key in source:
            env[key] = source[key]
    for key in (PARITY_FLAG, SEED_VAR):
        if key in source:
            env[key] = source[key]
    return env


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def services(job: CiJob | None, env: dict[str, str]) -> Iterator[list[str]]:
    """Start the job's service containers fresh; rewrite env to their ports."""
    started: list[str] = []
    names: list[str] = []
    try:
        for name, spec in (job.services if job else {}).items():
            # Known by service key or image (agent-hub's `postgres` runs pgvector).
            port = next((value for key, value in _SERVICE_PORTS.items()
                         if key in name or key in str(spec.get("image") or "")), None)
            if port is None:
                raise CiParityError(f"CI service {name} ({spec.get('image')}) has no local equivalent")
            engine = container_cli()
            if engine is None:
                raise CiParityError("docker or podman is required to provide the CI service database")
            cli, qualify = engine
            host_port = _free_port()
            container = f"st-ci-{name}-{secrets.token_hex(4)}"
            service_env = [item for key, value in (spec.get("env") or {}).items()
                           for item in ("-e", f"{key}={value}")]
            result = subprocess.run(
                [*cli, "run", "-d", "--rm", "--name", container, "-p", f"127.0.0.1:{host_port}:{port}",
                 "--tmpfs", "/var/lib/postgresql/data", *service_env,
                 qualified_image(str(spec["image"])) if qualify else str(spec["image"])],
                capture_output=True, text=True, timeout=600, check=False)
            if result.returncode:
                raise CiParityError(f"CI service {name} did not start: {result.stderr.strip()[-300:]}")
            started.append(container)
            names.append(name)
            user = str((spec.get("env") or {}).get("POSTGRES_USER") or "postgres")
            database = str((spec.get("env") or {}).get("POSTGRES_DB") or user)
            deadline = time.monotonic() + 60
            # pg_isready inside the container passes on the init server too;
            # a TCP query through the mapped port only answers once it is final.
            while subprocess.run([*cli, "exec", container, "psql", "-h", "127.0.0.1", "-U", user, "-d", database,
                                  "-tAc", "select 1"], capture_output=True, check=False).returncode:
                if time.monotonic() > deadline:
                    raise CiParityError(f"CI service {name} did not become ready")
                time.sleep(0.5)
            # libpq clients in CI setup steps (`createdb -h localhost`) use the default port.
            env.update(PGHOST="127.0.0.1", PGPORT=str(host_port))
            for key, value in list(env.items()):
                env[key] = re.sub(rf"(?<=@)(localhost|127\.0\.0\.1):{port}\b", f"127.0.0.1:{host_port}", value)
        yield names
    finally:
        engine = container_cli()
        for container in started:
            if engine:
                subprocess.run([*engine[0], "rm", "-f", container], capture_output=True, timeout=60, check=False)


def randomly_installed(argv: list[str]) -> bool:
    venv = Path(argv[0]).parent.parent
    return any(venv.glob("lib/python*/site-packages/pytest_randomly*"))


def seeded(argv: list[str], value: int | None) -> list[str]:
    """CI shuffles where pytest-randomly is installed; pin that shuffle's seed."""
    if value is None or not randomly_installed(argv) or any("no:randomly" in arg for arg in argv) \
            or any(arg.startswith("--randomly-seed") for arg in argv):
        return argv
    return [*argv, f"--randomly-seed={value}"]


@contextlib.contextmanager
def scratch_directory() -> Iterator[Path]:
    # Not under /tmp: sandboxed tests (bwrap --tmpfs /tmp) must still see the
    # CI tools on PATH, as they do in a runner's tool cache. Managed scratch is
    # writable inside isolated acceptance too, where the home is read-only.
    base = managed_temp_parent("st-ci-parity", label="CI parity")
    with tempfile.TemporaryDirectory(prefix="run-", dir=base) as directory:
        yield Path(directory)


def repro_command(value: int | None) -> str:
    return "st check --ci-repro" + (f" --seed {value}" if value is not None else "")
