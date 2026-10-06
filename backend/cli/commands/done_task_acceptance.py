"""Accept an immutable local source while preserving a shared dirty checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.utils.heavy_work import heavy_work
from cli.lib import acceptance


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", "--no-optional-locks", "-c", "diff.autoRefreshIndex=false", *args], cwd=repo, capture_output=True,
        text=True, check=False,
        # Git restores regular/executable files as 0644/0755. A shared worker's
        # group-writable umask must not weaken protected configuration files in
        # the private accepted tree; never change the worker's global umask.
        umask=0o022,
        env={**{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
             "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    if result.returncode:
        raise acceptance.AcceptanceError("Cannot prepare the immutable local acceptance source")
    return result.stdout.strip()


def _require_local_objects(repo: Path) -> None:
    result = subprocess.run(
        ["git", "config", "--local", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    if result.returncode not in {0, 1} or any(
        line.lower().split(maxsplit=1)[0] == "extensions.partialclone"
        or line.lower().endswith(" true") for line in result.stdout.splitlines()
    ):
        raise acceptance.AcceptanceError("Isolated local acceptance requires complete local Git objects; partial/promisor checkout is unavailable")


def _preserve_equivalent_modes(repo: Path, source: Path, mode_entries: dict[str, int] | None = None) -> None:
    """Keep actual permissions only for demonstrably equivalent tracked files.

    Git records the owner execute bit, not ordinary permission bits. Prepared
    native input identities and protective checks still consume those bits.
    Restore them in the private tree without copying WIP, following links, or
    inheriting privileged file modes. Historical-only files keep Git defaults.
    """
    commit = _git(source, "rev-parse", "HEAD")
    for name, permissions in (mode_entries if mode_entries is not None else acceptance.projected_source_modes(repo, commit)).items():
        candidate = source / name
        if candidate.is_symlink() or not candidate.is_file() or candidate.parent.resolve() != candidate.parent:
            raise acceptance.AcceptanceError("Isolated tracked permission input is not a regular accepted file")
        candidate.chmod(permissions)


def _dependency_roots(repo: Path) -> list[Path]:
    """Borrow only existing local prepared dependency directories, never source."""
    from cli.commands.check_execution import read_tool_paths
    from cli.commands.check_native import native_plan

    candidates = {".venv", "backend/.venv", "node_modules", "frontend/node_modules"}
    # Workspace source remains in the accepted tree, but resolves peers from
    # its own prepared dependency directory (not the app's node_modules).
    workspace_dependencies = {path.relative_to(repo).as_posix() for path in repo.glob("packages/*/node_modules")}
    candidates.update(workspace_dependencies)
    declared = list(read_tool_paths(repo).values())
    native = native_plan(repo)
    if native is not None:
        declared.extend(native["paths"])
        # A required acceptance stage may not connect to an owner production DB.
        for name, value in native["environment"].items():
            if name in {"DATABASE_URL", "DATABASE_ADMIN_URL", "POSTGRES_ADMIN_URL"}:
                test_url = native["environment"].get("TEST_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
                if not test_url or value != test_url:
                    raise acceptance.AcceptanceError("Isolated acceptance requires a declared test database; production database inputs are unavailable")
    for value in declared:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise acceptance.AcceptanceError("Isolated acceptance requires project-local prepared dependency paths")
        # A whole venv/node_modules is needed for imports; a bin directory alone
        # loses its interpreter/package binding. Other paths must be ignored
        # prepared tools, rather than a tracked source directory.
        parts = path.parts
        boundary = next((index for index, part in enumerate(parts) if part in {".venv", "venv", "node_modules"}), None)
        candidates.add(Path(*parts[:boundary + 1]).as_posix() if boundary is not None else value)
    selected: list[Path] = []
    for value in sorted(candidates):
        path = repo / value
        if not path.exists():
            continue
        if not path.is_dir() or not path.resolve().is_relative_to(repo.resolve()):
            raise acceptance.AcceptanceError("Prepared dependency directory escapes this project; prepare the project environment explicitly")
        tracked = _git(repo, "ls-files", "--", value)
        if tracked:
            if value in declared:
                continue  # Tracked check scripts already belong to the accepted tree.
            raise acceptance.AcceptanceError("Prepared dependency directory contains tracked source")
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", value], cwd=repo, check=False)
        if ignored.returncode:
            raise acceptance.AcceptanceError("Prepared dependency directory is not declared as ignored local tooling")
        if native is None or value in workspace_dependencies:
            names = ({"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"}
                     if path.name == "node_modules" else {"uv.lock", "requirements.txt", "poetry.lock", "Pipfile.lock"})
            locations = [path.parent, repo]
            if not any((location / name).is_file() for location in locations for name in names):
                raise acceptance.AcceptanceError("Prepared dependency directory has no project dependency lock; prepare the managed project environment explicitly")
        if not any(path.is_relative_to(parent) for parent in selected):
            selected.append(path)
    return selected


def require_scope_matches_revision(repo: Path, sha: str, scope: tuple[str, ...]) -> None:
    """Keep an older task source valid only while its literal owned paths agree."""
    head = _git(repo, "rev-parse", "HEAD")
    if not scope:
        if head != sha:
            raise acceptance.AcceptanceError("Historical acceptance requires explicit task-owned literal paths")
        return
    for path in scope:
        candidate = Path(path)
        if (not path or candidate.is_absolute() or path in {".", "./"}
                or any(part in {"..", ".git"} for part in candidate.parts)
                or any(char in path for char in "*?[\\")):
            raise acceptance.AcceptanceError("Acceptance scope must contain project-local literal task paths")
    literal = [f":(literal){path}" for path in scope]
    if not _git(repo, "ls-tree", "-r", "--name-only", sha, "--", *literal):
        raise acceptance.AcceptanceError("Acceptance scope contains no source in the selected revision")
    if _git(repo, "diff", "--no-ext-diff", "--name-only", sha, head, "--", *literal):
        raise acceptance.AcceptanceError("Task-owned source changed since the selected acceptance revision")
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--", *literal):
        raise acceptance.AcceptanceError("Task-owned paths have uncommitted changes after the selected acceptance revision")


def require_task_created_paths(repo: Path, sha: str, task: dict[str, Any]) -> None:
    """A declared new file must exist in the accepted task source."""
    context = task.get("context") or {}
    for values in (task.get("files_to_create") or (), context.get("files_to_create") or ()):
        for path in values:
            if not isinstance(path, str):
                raise acceptance.AcceptanceError("Declared files to create must be literal project paths")
            if path not in _git(repo, "ls-tree", "-r", "--name-only", sha, "--", f":(literal){path}").splitlines():
                raise acceptance.AcceptanceError(f"Declared task file is missing from the accepted source: {path}")


def _bindings(repo: Path, source: Path) -> list[tuple[Path, Path]]:
    """Map same-project local inputs to canonical paths without copying WIP."""
    bindings = [(path, path) for path in _dependency_roots(repo)]
    # Existing prepared environments may only be borrowed for the committed
    # lock/configuration inputs. Foreign dependency updates remain untouched.
    # Both revisions' quality/dependency inputs must agree. The gate registry,
    # agent guidance and cloud workflows stay in the selected source receipt,
    # but do not prepare the local Python/frontend environment.
    inputs = set(acceptance._source_input_paths(repo, _git(repo, "rev-parse", "HEAD")))
    inputs.update(acceptance._source_input_paths(source, _git(source, "rev-parse", "HEAD")))
    for relative in sorted(inputs):
        if relative == "scripts/lib/tool-registry.json" or relative.startswith((".github/workflows/", ".agents/")):
            continue
        path = repo / relative
        accepted = source / relative
        if not path.is_file() or not accepted.is_file() or path.read_bytes() != accepted.read_bytes():
            raise acceptance.AcceptanceError("Prepared dependency/configuration inputs differ from the committed source; finish the owned configuration before completion")
    from cli.commands.check_native import native_plan
    native = native_plan(repo)
    if native is not None:
        for lock in native["locks"]:
            path = repo / lock["path"]
            accepted = source / lock["path"]
            if not path.is_file() or not accepted.is_file() or path.read_bytes() != accepted.read_bytes():
                raise acceptance.AcceptanceError("Prepared native lock inputs differ from the committed source")
    for _label, path in acceptance._local_gate_file_candidates(repo):
        if not path.is_relative_to(repo) or not path.exists():
            continue  # Shared home configuration remains globally read-only.
        if not path.is_file() or not path.resolve().is_relative_to(repo):
            raise acceptance.AcceptanceError("Local acceptance configuration escapes this project")
        relative = path.relative_to(repo)
        accepted = source / relative
        if _git(repo, "ls-files", "--", relative.as_posix()):
            if not accepted.is_file() or accepted.read_bytes() != path.read_bytes():
                raise acceptance.AcceptanceError("Acceptance configuration differs from the committed task source; commit the owned configuration first")
        else:
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.touch()
            bindings.append((path, path))
    for original, canonical in bindings:
        candidate = source / canonical.relative_to(repo)
        if original.is_dir():
            candidate.mkdir(parents=True, exist_ok=True)
    return bindings


def _sandbox_command(repo: Path, source: Path, metadata: Path, common: Path,
                     temporary: Path, bindings: list[tuple[Path, Path]],
                     sha: str, scope: tuple[str, ...], task_id: str, reuse: bool,
                     coverage: str = "full", required_stages: Sequence[str] = (), *,
                     private_var_tmp: Path | None = None) -> list[str]:
    binary = shutil.which("bwrap")
    if not binary:
        raise acceptance.AcceptanceError("Isolated acceptance is unavailable: bwrap is not installed; prepare the managed isolation capability")
    lane = Path(f"/tmp/st-heavy-{os.getuid()}")
    scratch = temporary / "t"
    scratch.mkdir(mode=0o700)
    # Nested runs replace /tmp, so give their private state distinct paths as
    # well as distinct mounts using the unique temporary-run directory name.
    home = Path("/tmp") / f"h-{temporary.name}"
    state = {"HOME": home, "XDG_CONFIG_HOME": home / ".config",
             "XDG_DATA_HOME": home / ".local/share", "XDG_CACHE_HOME": home / ".cache",
             "XDG_STATE_HOME": home / ".local/state"}
    for path in state.values():
        (scratch / path.relative_to("/tmp")).mkdir(mode=0o700, parents=True, exist_ok=True)
    command = [binary, "--die-with-parent", "--ro-bind", "/", "/"]
    if private_var_tmp is not None:
        # Only outer acceptance requests this private fallback. Nested native
        # helpers must retain their existing /var/tmp tool aliases instead.
        command.extend(["--bind", str(private_var_tmp), "/var/tmp"])
        # A direct native stage prepares its allowlisted tool aliases under
        # /var/tmp. Preserve that exact root without exposing host scratch.
        if tool_alias_root := os.environ.get("ST_NATIVE_TOOL_ALIAS_ROOT"):
            aliases = Path(tool_alias_root)
            if (aliases.is_absolute() and aliases != Path("/var/tmp")
                    and aliases.is_relative_to("/var/tmp") and aliases == aliases.resolve()
                    and aliases.is_dir()):
                command.extend(["--ro-bind", str(aliases), str(aliases)])
    # Restore the same host path after the optional overlay: temporary itself
    # may live under /var/tmp, and Docker/native tools consume its backing paths.
    command.extend(["--proc", "/proc", "--dev", "/dev",
                    "--bind", str(temporary), str(temporary), "--bind", str(scratch), "/tmp",
                    "--bind", str(source), str(repo), "--setenv", "TMPDIR", "/tmp",
                    "--setenv", "ST_NATIVE_TMP_HOST_ROOT", str(scratch)])
    for name, path in state.items():
        command.extend(["--setenv", name, str(path)])
    # Corepack launches the already-prepared package manager from its own
    # cache. Relocating XDG_CACHE_HOME must not silently download that tool.
    if "COREPACK_HOME" not in os.environ:
        cache = Path(os.environ.get("XDG_CACHE_HOME") or os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
        command.extend(["--setenv", "COREPACK_HOME", str(cache / "node/corepack")])
    # Tests may create leases, package-manager stores and other local state.
    # Retain only the shared configuration already fingerprinted by acceptance
    # at its private HOME location; the host home and dependencies stay read-only.
    shared = Path.home() / ".env.local"
    if shared.exists():
        command.extend(["--ro-bind", str(shared), str(home / ".env.local")])
    if common != repo / ".git":
        command.extend(["--bind", str(metadata), str(common)])
    command.extend(["--bind", str(lane), str(lane)])
    for original, canonical in bindings:
        command.extend(["--ro-bind", str(original), str(canonical)])
    # Editable imports naming the original project now resolve to the accepted
    # tree. Only the prepared dependencies and explicit local inputs are shared.
    bootstrap = (
        "import json,sys; sys.path.insert(0,sys.argv.pop(1)); "
        "from pathlib import Path; from cli.lib.acceptance import accept_revision; "
        "args=json.loads(sys.argv[1]); "
        "options={'coverage':args['coverage'],'required_stages':args['required_stages']} if args['coverage']=='task' else {}; "
        "receipt=accept_revision(Path(args['repo']),sha=args['sha'],scope=args['scope'],task_id=args['task_id'],reuse=args['reuse'],execution_basis='isolated',**options); "
        "print('ISOLATED_ACCEPTANCE:'+json.dumps(receipt,sort_keys=True))"
    )
    command.extend(["--chdir", str(repo), "--", sys.executable, "-P", "-c", bootstrap,
                    str(Path(acceptance.__file__).resolve().parents[2]),
                    json.dumps({"repo": str(repo), "sha": sha, "scope": list(scope), "task_id": task_id, "reuse": reuse,
                                "coverage": coverage, "required_stages": list(required_stages)})])
    return command


def accept_isolated_revision(repo: Path, *, sha: str, scope: tuple[str, ...], task_id: str, reuse: bool = True,
                             coverage: str = "full", required_stages: Sequence[str] = ()) -> dict[str, Any]:
    """Run canonical full acceptance over the committed tree, preserving WIP."""
    repo = repo.resolve()
    with acceptance.repo_lock(repo, purpose="capture isolated acceptance"):
        _require_local_objects(repo)
        before = acceptance.isolated_input_identity(repo, sha=sha, scope=scope)
        require_scope_matches_revision(repo, before["commit"], scope)
        plan = acceptance.requested_plan(repo, commit=before["commit"], coverage=coverage, scope=scope, required_stages=required_stages)
        if reuse:
            key = acceptance._accepted_source_cache_key(before, plan)
            artifact = acceptance._receipt_path(repo, key)
            if artifact.is_file():
                try:
                    validated = acceptance.validate_acceptance_receipt(repo, artifact, sha=before["commit"])
                except acceptance.AcceptanceError:
                    pass
                else:
                    return {**validated, "task_id": task_id, "scope": list(scope),
                            "reused": True, "working_tree_clean": not _git(repo, "status", "--porcelain=v1", "--untracked-files=all")}
    with heavy_work("isolated task acceptance") as work:
        # /tmp is private and short inside bwrap. Keep its backing directory
        # visible at the same host path for Docker, including nested acceptance.
        temporary_parent = os.environ.get("ST_NATIVE_TMP_HOST_ROOT", "/var/tmp")
        with tempfile.TemporaryDirectory(prefix="st-a-", dir=temporary_parent) as directory:
            temporary = Path(directory)
            # Preserve an inherited scratch mapping and its caller tool aliases.
            # Only the outer run needs a new private /var/tmp fallback.
            private_var_tmp = None
            if "ST_NATIVE_TMP_HOST_ROOT" not in os.environ:
                private_var_tmp = temporary / "v"
                private_var_tmp.mkdir(mode=0o700)
            source = temporary / "source"
            # A local object-only clone copies committed history and exact HEAD,
            # never staged/untracked files, hook configuration, or a mutable @.
            _git(repo, "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
                 "clone", "--local", "--no-recurse-submodules", "--no-hardlinks", "--no-checkout",
                 "--", str(repo), str(source))
            _git(source, "-c", "core.hooksPath=/dev/null", "checkout", "--detach", before["commit"])
            _preserve_equivalent_modes(repo, source, before["source_mode_entries"])
            common = acceptance._git_common_dir(repo)
            metadata = source / ".git"
            if common != repo / ".git":
                relocated = temporary / "metadata"
                metadata.rename(relocated)
                metadata.write_text(f"gitdir: {common}\n", encoding="utf-8")
                metadata = relocated
            bindings = _bindings(repo, source)
            # Borrowed environment/config files are not implementation source.
            # Keep their mount points out of isolated source dirtiness checks.
            excludes = metadata / "info" / "exclude"
            with excludes.open("a", encoding="utf-8") as handle:
                handle.write("/.dev-tools/\n")
                for _original, canonical in bindings:
                    handle.write("/" + canonical.relative_to(repo).as_posix() + "\n")
            command = _sandbox_command(repo, source, metadata, common, temporary, bindings,
                                       before["commit"], scope, task_id, reuse, coverage, required_stages,
                                       private_var_tmp=private_var_tmp)
            from cli.commands.check_native import transfer_native_stage_receipts

            stage_store = common / "st" / "native-stages"
            private_stages = metadata / "st" / "native-stages"
            if reuse:
                transfer_native_stage_receipts(stage_store, private_stages)
            evidence = metadata / "st" / "native-stages" / "artifacts"
            # Retain failed/interrupted observations without admitting them as
            # successful acceptance; retry creates a fresh isolated source.
            observations = common / "st" / "acceptance" / "isolated-observations"
            observations.mkdir(parents=True, exist_ok=True)
            log = observations / f"{uuid.uuid4().hex}.log"
            try:
                result = work.run(command, cwd=repo, capture_output=True, text=True, check=False)
            except BaseException as exc:
                log.write_text(f"Isolated acceptance interrupted: {type(exc).__name__}\n", encoding="utf-8")
                raise
            finally:
                # Successful exact-source stages remain reusable even when a
                # later stage fails. This is observation retention, not task
                # acceptance; each retry still validates its complete inputs.
                transfer_native_stage_receipts(private_stages, stage_store)
                retained = observations / log.stem
                retained.mkdir()
                for folder in (metadata / "st" / "acceptance", source / ".dev-tools"):
                    if folder.is_dir():
                        for artifact in folder.iterdir():
                            if artifact.is_file() and not artifact.is_symlink():
                                shutil.copy2(artifact, retained / artifact.name)
                if evidence.is_dir():
                    native_artifacts = retained / "native-artifacts"
                    native_artifacts.mkdir()
                    for artifact in evidence.iterdir():
                        if artifact.is_file() and not artifact.is_symlink():
                            shutil.copy2(artifact, native_artifacts / artifact.name)
            log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
            if result.returncode:
                raise acceptance.AcceptanceError(f"Isolated full acceptance failed or is unavailable; retained check evidence: {log}")
            lines = [line.removeprefix("ISOLATED_ACCEPTANCE:") for line in result.stdout.splitlines()
                     if line.startswith("ISOLATED_ACCEPTANCE:")]
            if len(lines) != 1:
                raise acceptance.AcceptanceError(f"Isolated acceptance returned no unique receipt; evidence: {log}")
            receipt = json.loads(lines[0])
            with acceptance.repo_lock(repo, purpose="finalize isolated acceptance"):
                after = acceptance.isolated_input_identity(repo, sha=before["commit"], captured=before, scope=scope)
                current_plan = acceptance.requested_plan(repo, commit=before["commit"], coverage=coverage,
                                                         scope=scope, required_stages=required_stages)
                if after != before or current_plan != plan:
                    raise acceptance.AcceptanceError("Consumed source or local inputs changed during isolated acceptance; retry with stable prepared inputs")
                require_scope_matches_revision(repo, before["commit"], scope)
                persisted = acceptance.persist_validated_receipt(repo, receipt, sha=before["commit"], evidence_directory=evidence)
            return {**persisted, "task_id": task_id, "scope": list(scope)}
