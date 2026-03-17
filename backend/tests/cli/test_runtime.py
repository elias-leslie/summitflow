"""Tests for Docker compose runtime helpers."""

from __future__ import annotations

from pathlib import Path

from cli import runtime


def test_compose_env_strips_keys_defined_in_compose_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "HATCHET_CLIENT_TOKEN=canonical-token",
                "SUMMITFLOW_CLIENT_ID=canonical-client",
            ]
        )
    )

    monkeypatch.setattr(runtime, "COMPOSE_ENV_FILE", env_file)
    monkeypatch.setenv("HATCHET_CLIENT_TOKEN", "stale-token")
    monkeypatch.setenv("SUMMITFLOW_CLIENT_ID", "stale-client")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = runtime.compose_env()

    assert "HATCHET_CLIENT_TOKEN" not in env
    assert "SUMMITFLOW_CLIENT_ID" not in env
    assert env["PATH"] == "/usr/bin"


def test_compose_cmd_for_mode_uses_explicit_env_file(monkeypatch, tmp_path: Path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n")
    compose_dev_file = tmp_path / "docker-compose.dev.yml"
    compose_dev_file.write_text("services: {}\n")
    env_file = tmp_path / ".env"
    env_file.write_text("TAG=latest\n")

    monkeypatch.setattr(runtime, "COMPOSE_FILE", compose_file)
    monkeypatch.setattr(runtime, "COMPOSE_DEV_FILE", compose_dev_file)
    monkeypatch.setattr(runtime, "COMPOSE_ENV_FILE", env_file)

    command = runtime.compose_cmd_for_mode("dev", "up", "-d")

    assert command[:5] == [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
    ]
    assert str(compose_file) in command
    assert str(compose_dev_file) in command
    assert command[-2:] == ["up", "-d"]
