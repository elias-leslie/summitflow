from __future__ import annotations

import base64
import os
import subprocess

import pytest
import typer

from app.utils import agent_execution as execution


def _cross_user(monkeypatch):
    monkeypatch.setattr(execution.tether, "_agent_uid", lambda: os.getuid() + 1)


def _reply(monkeypatch, *, code=0, out=b"output\n", err=b"", uid=None, status=200):
    def request(method, path, body, **kwargs):
        calls.append((method, path, body, kwargs))
        return status, {"uid": execution.tether._agent_uid() if uid is None else uid,
                        "returncode": code, "stdout_base64": base64.b64encode(out).decode(),
                        "stderr_base64": base64.b64encode(err).decode()}
    calls = []
    monkeypatch.setattr(execution.tether, "request", request)
    return calls


def test_cross_user_uses_only_agent_socket_and_explicit_safe_environment(monkeypatch, tmp_path):
    _cross_user(monkeypatch)
    calls = _reply(monkeypatch)
    monkeypatch.setattr(execution.tether, "agent_socket_path", lambda: "/fixture/agent.sock")
    monkeypatch.setenv("TETHER_SOCKET", "/fixture/owner.sock")
    monkeypatch.setenv("OWNER_SECRET", "never-forward")
    result = execution.run_as_agent(["git", "status"], cwd=tmp_path, capture_output=True,
                                    text=True, input="input", timeout=7,
                                    env={"HOME": "/owner", "PATH": "/owner/bin", "SSH_AUTH_SOCK": "/owner/socket",
                                         "OWNER_SECRET": "never-forward", "GIT_CONFIG_COUNT": "1",
                                         "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false",
                                         "GIT_OPTIONAL_LOCKS": "0"})
    assert result.stdout == "output\n"
    method, path, body, kwargs = calls[0]
    assert (method, path) == ("POST", "/v1/exec")
    assert kwargs["socket_file"] == "/fixture/agent.sock"
    assert body["cwd"] == str(tmp_path)
    assert body["timeout_ms"] == 7000
    assert base64.b64decode(body["stdin_base64"]) == b"input"
    assert body["env"] == {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                           "GIT_CONFIG_VALUE_0": "false", "GIT_OPTIONAL_LOCKS": "0"}


def test_cross_user_refuses_wrong_uid_and_never_falls_back(monkeypatch):
    _cross_user(monkeypatch)
    _reply(monkeypatch, uid=os.getuid())
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: pytest.fail("owner fallback"))
    with pytest.raises(OSError, match="identity"):
        execution.run_as_agent(["git", "status"], capture_output=True)


@pytest.mark.parametrize("status", [403, 404, 413, 500])
def test_cross_user_reports_transport_failure(monkeypatch, status):
    _cross_user(monkeypatch)
    _reply(monkeypatch, status=status)
    with pytest.raises(OSError, match=str(status)):
        execution.run_as_agent(["git", "status"], capture_output=True)


def test_cross_user_timeout_and_check_semantics(monkeypatch):
    _cross_user(monkeypatch)
    _reply(monkeypatch, status=408)
    with pytest.raises(subprocess.TimeoutExpired):
        execution.run_as_agent(["git", "status"], capture_output=True, timeout=2)
    _reply(monkeypatch, code=128, out=b"", err=b"refused\n")
    with pytest.raises(subprocess.CalledProcessError) as raised:
        execution.run_as_agent(["git", "status"], capture_output=True, text=True, check=True)
    assert (raised.value.returncode, raised.value.stderr) == (128, "refused\n")


def test_cross_user_bounds_output_and_validates_encoding(monkeypatch):
    _cross_user(monkeypatch)
    _reply(monkeypatch, out=b"12345")
    with pytest.raises(OSError, match="bound"):
        execution.run_as_agent(["git", "status"], capture_output=True, max_output_bytes=4)
    _reply(monkeypatch, out=b"a\r\nb\rc\xff")
    result = execution.run_as_agent(["git", "status"], capture_output=True, encoding="utf-8", errors="replace")
    assert result.stdout == "a\nb\nc\ufffd"
    result = execution.run_as_agent(["git", "status"], capture_output=True)
    assert result.stdout == b"a\r\nb\rc\xff"


def test_socket_unavailable_is_an_error_without_owner_fallback(monkeypatch):
    _cross_user(monkeypatch)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("agent socket unavailable")
    monkeypatch.setattr(execution.tether, "request", unavailable)
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: pytest.fail("owner fallback"))
    with pytest.raises(FileNotFoundError):
        execution.run_as_agent(["git", "status"], capture_output=True)


def test_same_agent_uid_executes_actual_local_process(monkeypatch, tmp_path):
    monkeypatch.setattr(execution.tether, "_agent_uid", os.getuid)
    monkeypatch.setattr(execution.tether, "request", lambda *a, **kw: pytest.fail("unexpected Tether"))
    result = execution.run_as_agent(["/bin/cat"], cwd=tmp_path, input=b"actual bytes", capture_output=True, check=True)
    assert result.stdout == b"actual bytes"


def test_checkout_ownership_detection_uses_real_metadata_without_git(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "child").mkdir()
    real_uid = os.getuid()
    monkeypatch.setattr(execution.tether, "_agent_uid", lambda: real_uid)
    assert not execution.source_requires_agent(tmp_path)
    monkeypatch.setattr(execution.os, "getuid", lambda: real_uid + 1)
    assert execution.source_requires_agent(tmp_path / "child")
    monkeypatch.setattr(execution.tether, "_agent_uid", lambda: real_uid + 2)
    assert not execution.source_requires_agent(tmp_path)


@pytest.mark.parametrize("argv,cwd,env,expected", [
    (["git", "-C", "/source", "status"], "/owner", None, "/source"),
    (["git", "-C", "source", "-C", "nested", "status"], "/owner", None, "/owner/source/nested"),
    (["git", "-C/source", "status"], "/owner", None, "/source"),
    (["git", "--no-replace-objects", "--git-dir=/source/.git", "status"], "/owner", None, "/source/.git"),
    (["git", "status"], "/owner", {"GIT_WORK_TREE": "/source"}, "/source"),
])
def test_source_routing_inspects_effective_git_paths(monkeypatch, argv, cwd, env, expected):
    _cross_user(monkeypatch)
    seen = []
    def requires(path):
        seen.append(str(path))
        return str(path) == expected
    monkeypatch.setattr(execution, "source_requires_agent", requires)
    sentinel = subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(execution, "run_as_agent", lambda *a, **kw: sentinel)
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: pytest.fail("owner Git"))
    assert execution.run_source_git(argv, cwd=cwd, env=env) is sentinel
    assert expected in seen


def test_private_owner_mirror_stays_local(monkeypatch, tmp_path):
    _cross_user(monkeypatch)
    (tmp_path / "objects").mkdir()
    (tmp_path / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setattr(execution, "run_as_agent", lambda *a, **kw: pytest.fail("private mirror delegated"))
    sentinel = subprocess.CompletedProcess([], 0, b"", b"")
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: sentinel)
    assert execution.run_source_git(["git", "-C", str(tmp_path), "rev-parse", "HEAD"]) is sentinel


def test_source_routing_prevents_owner_checkout_helper(monkeypatch, tmp_path):
    # Real fixture ownership and helper file; UID/socket execution are simulated.
    (tmp_path / ".git").mkdir()
    marker = tmp_path / "owner-helper-ran"
    (tmp_path / ".git" / "config").write_text(f'[core]\nfsmonitor = touch "{marker}"\n')
    real_uid = os.getuid()
    monkeypatch.setattr(execution.tether, "_agent_uid", lambda: real_uid)
    monkeypatch.setattr(execution.os, "getuid", lambda: real_uid + 1)
    calls = _reply(monkeypatch, uid=real_uid)
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: pytest.fail("owner Git/helper"))
    execution.run_source_git(["git", "-C", str(tmp_path), "status"], capture_output=True)
    assert len(calls) == 1
    assert not marker.exists()


def test_claim_refusal_is_not_reported_as_clean(monkeypatch):
    from cli.commands import claim_helpers
    def refusal(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ["git", "status"], stderr="dubious ownership")
    monkeypatch.setattr(claim_helpers, "run_source_git", refusal)
    with pytest.raises(typer.Exit) as raised:
        claim_helpers.require_claim_safe_tree()
    assert raised.value.exit_code == 1


def test_cancellable_same_uid_uses_tether_and_preserves_callback(monkeypatch):
    monkeypatch.setattr(execution.tether, "_agent_uid", os.getuid)
    calls = _reply(monkeypatch)
    def callback():
        pass
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: pytest.fail("uncancellable local process"))
    execution.run_as_agent(["st", "checkout-job", "capture"], capture_output=True, cancel_check=callback)
    calls[0][3]["cancel_check"]()


def test_missing_agent_account_preserves_portable_local_git(monkeypatch, tmp_path):
    monkeypatch.setattr(execution.tether, "_agent_uid", lambda: None)
    assert not execution.source_requires_agent(tmp_path)
    result = execution.run_source_git(["git", "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    with pytest.raises(OSError, match="agent user"):
        execution.run_as_agent(["git", "--version"], capture_output=True)


def test_source_git_ownership_refusal_never_looks_like_missing_repo(monkeypatch):
    monkeypatch.setattr(execution.tether, "_agent_uid", os.getuid)
    monkeypatch.setattr(execution.safe_subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 128, "", "fatal: detected dubious ownership in repository"))
    with pytest.raises(OSError, match="ownership"):
        execution.run_source_git(["git", "status"], capture_output=True, text=True)


def test_callback_value_error_is_not_wrapped_as_transport_failure(monkeypatch):
    _cross_user(monkeypatch)
    error = ValueError("cancelled callback")
    def cancellation():
        raise error
    def request(*args, **kwargs):
        kwargs["cancel_check"]()
    monkeypatch.setattr(execution.tether, "request", request)
    with pytest.raises(ValueError) as raised:
        execution.run_as_agent(["git", "status"], capture_output=True, cancel_check=cancellation)
    assert raised.value is error


def test_source_git_cwd_does_not_require_owner_private_working_directory(monkeypatch):
    _cross_user(monkeypatch)
    monkeypatch.setattr(execution, "source_requires_agent", lambda path: str(path) == "/agent/source")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(execution, "run_as_agent", run)
    execution.run_source_git(["git", "-C", "/agent/source", "status"], cwd="/owner/private")
    assert calls[0][0] == ["git", "-C", "/agent/source", "status"]
    assert str(calls[0][1]["cwd"]) == "/agent/source"
