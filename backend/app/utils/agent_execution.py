"""Run source-checkout work under its agent identity, never an owner fallback."""
from __future__ import annotations

import base64
import binascii
import http.client
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..services import tether
from . import safe_subprocess

# Explicit caller overrides only. Tether supplies the agent's ordinary environment.
_ENV_KEYS = frozenset({
    "GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_COUNT", "GIT_OPTIONAL_LOCKS", "GIT_NO_LAZY_FETCH",
    "GIT_TERMINAL_PROMPT", "LC_ALL", "LANG", "TZ",
})


def source_requires_agent(path: str | os.PathLike[str]) -> bool:
    """Whether this caller must delegate an agent-owned checkout.

    Inspect ownership without invoking Git or reading config. An agent caller
    and hosts without a configured agent account keep their native execution.
    Worktree gitfiles, symlink targets and bare Git directories are included.
    Owner-owned deployment mirrors remain owner work until their ownership changes.
    """
    agent_uid = tether._agent_uid()
    if agent_uid is None or os.getuid() == agent_uid:
        return False
    root = Path(path).absolute()
    while True:
        try:
            if root.stat().st_uid == agent_uid:
                return True
        except FileNotFoundError:
            pass
        metadata = root / ".git"
        if metadata.exists():
            return metadata.stat().st_uid == agent_uid
        # Bare mirrors have no .git child; their root ownership decides.
        if (root / "HEAD").is_file() and (root / "objects").is_dir():
            return False
        if root.parent == root:
            return False
        root = root.parent


def _agent_environment(env: Mapping[str, str] | None) -> dict[str, str]:
    return {key: value for key, value in (env or {}).items()
            if key in _ENV_KEYS or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_[0-9]+", key)}


def _deliver(data: bytes, destination: Any, default: Any, *, text: bool,
             encoding: str, errors: str) -> str | bytes | None:
    value = data.decode(encoding, errors).replace("\r\n", "\n").replace("\r", "\n") if text else data
    if destination == subprocess.PIPE:
        return value
    if destination != subprocess.DEVNULL:
        stream = default if destination is None else destination
        if isinstance(value, bytes) and hasattr(stream, "buffer"):
            stream.buffer.write(value)
        else:
            stream.write(value)
        stream.flush()
    return None


def run_as_agent(
    argv: Sequence[str | os.PathLike[str]], *, cwd: str | os.PathLike[str] | None = None,
    input: str | bytes | None = None, capture_output: bool = False, text: bool = False,
    encoding: str | None = None, errors: str | None = None, check: bool = False,
    timeout: float | None = None, env: Mapping[str, str] | None = None,
    stdin: Any = None, stdout: Any = None, stderr: Any = None,
    max_output_bytes: int = 16 * 1024 * 1024,
    cancel_check: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Bounded subprocess-style execution on the explicit agent Tether socket.

    Pipes and DEVNULL are supported; cross-user stdin is EOF unless input is
    provided. File descriptors, shells and arbitrary environment forwarding are
    deliberately outside this adapter. The same agent UID uses native spawning.
    """
    args = [os.fspath(arg) for arg in argv]
    if not args:
        raise ValueError("agent execution requires argv")
    agent_uid = tether._agent_uid()
    if agent_uid is None:
        raise OSError("Configured agent user is unavailable")
    if os.getuid() == agent_uid and cancel_check is None:
        return safe_subprocess.run(args, cwd=cwd, input=input, capture_output=capture_output,
                                   text=text, encoding=encoding, errors=errors, check=check,
                                   timeout=timeout, env=env, stdin=stdin, stdout=stdout, stderr=stderr)
    if stdin not in (None, subprocess.DEVNULL):
        raise ValueError("cross-user stdin requires explicit input")
    if input is not None and stdin is not None:
        raise ValueError("stdin and input cannot both be supplied")
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("capture_output conflicts with stdout or stderr")
        stdout = stderr = subprocess.PIPE
    if stderr == subprocess.STDOUT:
        raise ValueError("cross-user stderr=STDOUT is unsupported")
    codec, error_mode = encoding or "utf-8", errors or "strict"
    execution_timeout = timeout if timeout is not None else 60.0
    text_mode = text or encoding is not None or errors is not None
    if input is not None and isinstance(input, str) != text_mode:
        raise TypeError("input must match text mode")
    body: dict[str, Any] = {
        "argv": args, "cwd": str(Path(cwd or Path.cwd()).absolute()),
        "env": _agent_environment(env), "max_output_bytes": max_output_bytes,
    }
    if timeout is not None:
        if timeout <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        body["timeout_ms"] = max(1, int(timeout * 1000))
    if input is not None:
        body["stdin_base64"] = base64.b64encode(input.encode(codec, error_mode) if isinstance(input, str) else input).decode("ascii")
    cancelled: list[BaseException] = []

    def checked_cancellation() -> None:
        assert cancel_check is not None
        try:
            cancel_check()
        except BaseException as exc:
            cancelled.append(exc)
            raise

    try:
        status, result = tether.request(
            "POST", "/v1/exec", body, socket_file=tether.agent_socket_path(),
            timeout=execution_timeout + 5,
            max_bytes=2 * max_output_bytes + 64 * 1024,
            **({"cancel_check": checked_cancellation} if cancel_check is not None else {}),
        )
    except TimeoutError as exc:
        if cancelled:
            raise cancelled[0] from None
        raise subprocess.TimeoutExpired(args, execution_timeout) from exc
    except (ValueError, http.client.HTTPException) as exc:
        if cancelled:
            raise cancelled[0] from None
        raise OSError("Agent execution transport failed") from exc
    if status != 200 or not isinstance(result, dict):
        if status == 408:
            raise subprocess.TimeoutExpired(args, execution_timeout)
        raise OSError(f"Agent execution failed (HTTP {status})")
    if type(result.get("uid")) is not int or result["uid"] != agent_uid:
        raise OSError("Agent execution returned an unexpected identity")
    if type(result.get("returncode")) is not int:
        raise OSError("Agent execution returned an invalid exit status")
    try:
        out = base64.b64decode(result["stdout_base64"], validate=True)
        err = base64.b64decode(result["stderr_base64"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise OSError("Agent execution returned invalid output") from exc
    if len(out) + len(err) > max_output_bytes:
        raise OSError("Agent execution output exceeds bound")
    completed = subprocess.CompletedProcess(
        args, result["returncode"],
        _deliver(out, stdout, sys.stdout, text=text_mode, encoding=codec, errors=error_mode),
        _deliver(err, stderr, sys.stderr, text=text_mode, encoding=codec, errors=error_mode),
    )
    if check:
        completed.check_returncode()
    return completed


def _source_result(result: subprocess.CompletedProcess[Any]) -> subprocess.CompletedProcess[Any]:
    stderr = result.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    if result.returncode and isinstance(stderr, str) and "dubious ownership" in stderr:
        raise OSError("Git refused checkout ownership; source inspection is unavailable")
    return result


def run_source_git(argv: Sequence[str | os.PathLike[str]], *, max_output_bytes: int = 16 * 1024 * 1024,
                   **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Route a Git argv using its effective -C/cwd, preserving private mirrors.

    Git -C may occur more than once and is relative to the preceding cwd. The
    adapter does not interpret subcommands or execute Git to discover identity.
    """
    args = [os.fspath(arg) for arg in argv]
    if not args or Path(args[0]).name != "git":
        raise ValueError("source Git execution requires a Git argv")
    if os.getuid() == tether._agent_uid() and kwargs.get("cancel_check") is None:
        return _source_result(safe_subprocess.run(args, **kwargs))
    root = Path(kwargs.get("cwd") or Path.cwd()).absolute()
    git_paths: list[str] = []
    environment = os.environ if kwargs.get("env") is None else kwargs["env"]
    git_paths.extend(environment[key] for key in ("GIT_DIR", "GIT_WORK_TREE") if environment.get(key))
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "-C":
            index += 1
            if index >= len(args):
                raise ValueError("Git -C requires a directory")
            root = (root / args[index]).absolute()
            args[index] = str(root)
        elif arg.startswith("-C"):
            root = (root / arg[2:]).absolute()
            args[index] = "-C" + str(root)
        elif arg in {"--git-dir", "--work-tree"}:
            index += 1
            if index >= len(args):
                raise ValueError(f"Git {arg} requires a directory")
            git_paths.append(args[index])
        elif arg.startswith(("--git-dir=", "--work-tree=")):
            git_paths.append(arg.split("=", 1)[1])
        elif arg in {"-c", "--config-env"}:
            index += 1
        elif not arg.startswith("-") or arg == "--":
            break
        index += 1
    if kwargs.get("cancel_check") is not None or any(source_requires_agent(path) for path in [root, *(root / path for path in git_paths)]):
        # The owner worker may start in a private release directory. Its cwd is
        # irrelevant to an explicit Git -C source and need not be agent-readable.
        kwargs["cwd"] = root
        return _source_result(run_as_agent(args, max_output_bytes=max_output_bytes, **kwargs))
    return _source_result(safe_subprocess.run(args, **kwargs))
