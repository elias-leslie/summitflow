from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "codex-session-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_session_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_runs_with_registered_client_id_and_no_secret(monkeypatch) -> None:
    module = _load_module()
    captured = {}
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")

    def fake_run_sync(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(module, "run_sync", fake_run_sync)

    assert module.main(["--scan"]) == 0
    assert captured["kwargs"]["client_id"] == "summitflow"
    assert "client_secret" not in captured["kwargs"]


def test_entrypoint_skips_only_when_registered_client_id_is_missing(monkeypatch) -> None:
    module = _load_module()
    messages: list[str] = []
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")
    monkeypatch.setattr(module, "log", messages.append)

    assert module.main(["--scan"]) == 0
    assert messages == ["[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync"]


def test_entrypoint_requires_complete_project_binding_arguments(monkeypatch) -> None:
    module = _load_module()
    messages: list[str] = []
    monkeypatch.setattr(module, "log", messages.append)

    assert module.main(["--bind-session", "thread-1"]) == 2
    assert messages == [
        "[WARN] Binding requires --bind-session, --bind-project, and --project-root"
    ]


def test_binding_requires_current_thread_and_credentials(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")

    args = [
        "--bind-session",
        "thread-1",
        "--bind-project",
        "rootfall",
        "--project-root",
        "/srv/workspaces/projects/rootfall",
    ]
    assert module.main(args) == 2
    assert "Missing SUMMITFLOW_CLIENT_ID" in capsys.readouterr().err

    args[1] = "another-thread"
    assert module.main(args) == 2
    assert "must match the current CODEX_THREAD_ID" in capsys.readouterr().err


def test_binding_warnings_are_visible_to_cli_subprocess(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")

    def fake_run_sync(_args, **kwargs):
        kwargs["log_fn"]("[WARN] simulated binding conflict")
        return 2

    monkeypatch.setattr(module, "run_sync", fake_run_sync)
    result = module.main(
        [
            "--bind-session",
            "thread-1",
            "--bind-project",
            "rootfall",
            "--project-root",
            "/srv/workspaces/projects/rootfall",
        ]
    )

    assert result == 2
    assert "simulated binding conflict" in capsys.readouterr().err
