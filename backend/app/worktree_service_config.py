"""Derive worktree service config from repo-local project identity + systemd templates."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .project_identity import get_project_identity, get_project_identity_root

_SUMMITFLOW_ROOT = Path(__file__).resolve().parents[2]
_WORKTREE_PORT_BASE = {
    "backend": 8100,
    "frontend": 3100,
}
_WORKTREE_PORT_RANGE = 100


@dataclass
class WorktreeServiceConfig:
    """Runtime config for one worktree service."""

    name: str
    command: str
    port: int
    worktree_port_base: int
    worktree_port_range: int = _WORKTREE_PORT_RANGE
    cwd: str | None = None
    env_files: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    build_command: str | None = None
    install_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectWorktreeServicesConfig:
    """Collection of services for worktree startup."""

    config_source: str
    services: dict[str, WorktreeServiceConfig]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_source": self.config_source,
            "services": {
                name: service.to_dict()
                for name, service in self.services.items()
            },
        }


def _default_env_prefix(project_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", project_id).strip("_").upper()


def _project_env_prefix(identity: dict[str, Any], project_id: str) -> str:
    artifacts = identity.get("artifacts")
    if isinstance(artifacts, dict):
        env_prefix = artifacts.get("env_prefix")
        if isinstance(env_prefix, str) and env_prefix.strip():
            return env_prefix.strip()
    return _default_env_prefix(project_id)


def _load_identity(project_id: str, root_path: str | None = None) -> tuple[dict[str, Any], Path]:
    identity = get_project_identity(project_id, root_path)
    if not identity:
        raise ValueError(f"Project identity manifest not found for {project_id}")
    root = get_project_identity_root(project_id, root_path)
    if not root:
        raise ValueError(f"Project identity root not found for {project_id}")
    return identity, Path(root).resolve()


def _replace_root_placeholders(text: str, project_root: Path) -> str:
    return (
        text.replace("__PROJECT_ROOT__", str(project_root))
        .replace("__SUMMITFLOW_ROOT__", str(_SUMMITFLOW_ROOT))
    )


def _parse_systemd_template(path: Path, project_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "working_directory": None,
        "environment_files": [],
        "environment": {},
        "exec_start": None,
    }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("WorkingDirectory="):
            value = line.split("=", 1)[1].strip()
            payload["working_directory"] = _replace_root_placeholders(value, project_root)
            continue
        if line.startswith("EnvironmentFile="):
            value = line.split("=", 1)[1].strip().lstrip("-")
            value = shlex.split(value)[0] if value else ""
            payload["environment_files"].append(
                _replace_root_placeholders(value, project_root)
            )
            continue
        if line.startswith("Environment="):
            value = line.split("=", 1)[1].strip()
            parts = shlex.split(value)
            if not parts or "=" not in parts[0]:
                continue
            key, env_value = parts[0].split("=", 1)
            payload["environment"][key] = _replace_root_placeholders(
                env_value, project_root
            )
            continue
        if line.startswith("ExecStart="):
            value = line.split("=", 1)[1].strip()
            payload["exec_start"] = _replace_root_placeholders(value, project_root)
    return payload


def _unwrap_exec_start(exec_start: str) -> str:
    parts = shlex.split(exec_start)
    if len(parts) >= 3 and parts[0] in {"/bin/bash", "/usr/bin/bash", "bash"} and parts[1] == "-lc":
        return parts[2]
    if (
        len(parts) >= 4
        and parts[0] == "/usr/bin/env"
        and parts[1] in {"bash", "sh"}
        and parts[2] == "-lc"
    ):
        return parts[3]
    return exec_start


def _normalize_repo_relative_path(path_text: str, project_root: Path) -> str | None:
    if not path_text:
        return None
    if path_text.startswith("%h/") or path_text.startswith("${HOME}/") or path_text.startswith("$HOME/"):
        return None
    candidate = Path(path_text)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(project_root))
        except ValueError:
            return None
    return str(candidate)


def _replace_localhost_port_refs(value: str, main_port: int, shell_var: str) -> str:
    if main_port <= 0:
        return value
    for prefix in ("http://localhost:", "http://127.0.0.1:"):
        value = value.replace(f"{prefix}{main_port}", f"{prefix}${{{shell_var}}}")
    return value


def _command_has_dynamic_port(command: str, env_prefix: str, kind: str) -> bool:
    tokens = ["$PORT", "${PORT}", f"${env_prefix}_PORT", f"${{{env_prefix}_PORT}}"]
    if kind == "frontend":
        tokens.extend(
            [
                f"${env_prefix}_FRONTEND_PORT",
                f"${{{env_prefix}_FRONTEND_PORT}}",
            ]
        )
    return any(token in command for token in tokens)


def _rewrite_static_port_literal(command: str, main_port: int) -> str:
    if main_port <= 0:
        return command
    return re.sub(rf"(?<![\w$]){main_port}(?![\w])", "${PORT}", command)


def _detect_node_runner(command: str, service_dir: Path, package_json: dict[str, Any]) -> str:
    package_manager = package_json.get("packageManager")
    if isinstance(package_manager, str) and package_manager.startswith("pnpm@"):
        return "pnpm"
    if "corepack pnpm" in command:
        return "corepack pnpm"
    if re.search(r"\bpnpm\b", command):
        return "pnpm"
    if re.search(r"\bnpm\b", command):
        return "npm"
    if (service_dir / "pnpm-lock.yaml").exists() or (service_dir.parent / "pnpm-workspace.yaml").exists():
        return "pnpm"
    return "npm"


def _node_commands(command: str, service_dir: Path) -> tuple[str | None, str | None]:
    package_file = service_dir / "package.json"
    if not package_file.exists():
        return None, None
    package_json = json.loads(package_file.read_text(encoding="utf-8"))
    runner = _detect_node_runner(command, service_dir, package_json)
    install_command = f"{runner} install"
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict) or "build" not in scripts:
        return install_command, None
    build_command = "npm run build" if runner == "npm" else f"{runner} build"
    return install_command, build_command


def _normalize_environment(
    raw_env: dict[str, str],
    *,
    kind: str,
    env_prefix: str,
    project_root: Path,
    backend_port: int,
    frontend_port: int,
    own_port: int,
) -> dict[str, str]:
    environment: dict[str, str] = {}
    for key, value in raw_env.items():
        if key in {"PATH", "HOME"}:
            continue
        normalized = value.replace(str(project_root), "${WORKTREE_ROOT}")
        normalized = _replace_localhost_port_refs(
            normalized, backend_port, "SF_WORKTREE_BACKEND_PORT"
        )
        normalized = _replace_localhost_port_refs(
            normalized, frontend_port, "SF_WORKTREE_FRONTEND_PORT"
        )
        if normalized == str(own_port):
            normalized = "${PORT}"
        environment[key] = normalized

    if kind == "backend":
        environment.setdefault("PORT", "${SF_WORKTREE_BACKEND_PORT}")
        environment.setdefault(f"{env_prefix}_PORT", "${SF_WORKTREE_BACKEND_PORT}")
    else:
        environment.setdefault("PORT", "${SF_WORKTREE_FRONTEND_PORT}")
        environment.setdefault(f"{env_prefix}_FRONTEND_PORT", "${SF_WORKTREE_FRONTEND_PORT}")
        environment.setdefault("HOSTNAME", "0.0.0.0")
        if backend_port > 0:
            environment.setdefault(f"{env_prefix}_PORT", "${SF_WORKTREE_BACKEND_PORT}")

    return environment


def _build_service(
    *,
    project_root: Path,
    runtime: dict[str, Any],
    service_name: str,
    kind: str,
    env_prefix: str,
) -> WorktreeServiceConfig:
    template_path = project_root / "scripts" / "systemd" / service_name
    if not template_path.exists():
        raise ValueError(f"Service template not found: {template_path}")

    parsed = _parse_systemd_template(template_path, project_root)
    main_backend_port = int(runtime.get("backend_port") or 0)
    main_frontend_port = int(runtime.get("frontend_port") or 0)
    own_port = main_backend_port if kind == "backend" else main_frontend_port
    command = _unwrap_exec_start(str(parsed.get("exec_start") or "")).replace(
        str(project_root), "${WORKTREE_ROOT}"
    )
    command = _replace_localhost_port_refs(
        command, main_backend_port, "SF_WORKTREE_BACKEND_PORT"
    )
    command = _replace_localhost_port_refs(
        command, main_frontend_port, "SF_WORKTREE_FRONTEND_PORT"
    )
    if not _command_has_dynamic_port(command, env_prefix, kind):
        command = _rewrite_static_port_literal(command, own_port)

    working_directory = str(parsed.get("working_directory") or "")
    cwd = _normalize_repo_relative_path(working_directory, project_root)
    env_files = [
        normalized
        for raw_path in parsed.get("environment_files", [])
        if (normalized := _normalize_repo_relative_path(str(raw_path), project_root))
    ]
    environment = _normalize_environment(
        dict(parsed.get("environment") or {}),
        kind=kind,
        env_prefix=env_prefix,
        project_root=project_root,
        backend_port=main_backend_port,
        frontend_port=main_frontend_port,
        own_port=own_port,
    )

    service_dir = project_root / cwd if cwd else project_root
    install_command, build_command = _node_commands(command, service_dir)

    return WorktreeServiceConfig(
        name=kind,
        command=command,
        port=own_port,
        worktree_port_base=_WORKTREE_PORT_BASE[kind],
        worktree_port_range=_WORKTREE_PORT_RANGE,
        cwd=cwd,
        env_files=env_files,
        environment=environment,
        build_command=build_command,
        install_command=install_command,
    )


def load_project_worktree_services(project_id: str, root_path: str | None = None) -> ProjectWorktreeServicesConfig:
    """Return worktree service config for a project."""
    identity, project_root = _load_identity(project_id, root_path)
    runtime = identity.get("runtime")
    services = identity.get("services")
    project = identity.get("project")
    if not isinstance(runtime, dict) or not isinstance(services, dict) or not isinstance(project, dict):
        raise ValueError(f"Incomplete project identity manifest for {project_id}")

    canonical_project_id = str(project.get("id") or project_id)
    env_prefix = _project_env_prefix(identity, canonical_project_id)
    config_services: dict[str, WorktreeServiceConfig] = {}

    for kind in ("backend", "frontend"):
        service_name = services.get(kind)
        if not isinstance(service_name, str) or not service_name.strip():
            continue
        config_services[kind] = _build_service(
            project_root=project_root,
            runtime=runtime,
            service_name=service_name.strip(),
            kind=kind,
            env_prefix=env_prefix,
        )

    if not config_services:
        raise ValueError(f"No worktree-runnable services found for {project_id}")

    return ProjectWorktreeServicesConfig(
        config_source="project_identity",
        services=config_services,
    )


def load_project_worktree_services_dict(project_id: str, root_path: str | None = None) -> dict[str, Any]:
    """Return a JSON-serializable config payload."""
    return load_project_worktree_services(project_id, root_path).to_dict()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Project id or alias")
    parser.add_argument("--root", help="Optional explicit project root")
    args = parser.parse_args(argv)
    print(json.dumps(load_project_worktree_services_dict(args.project, args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
