"""Tests for complete HTTP payload construction."""

from __future__ import annotations

import base64

import pytest
import typer
from typer.testing import CliRunner

from cli.commands._complete_http import build_payload, encode_audio
from cli.commands.agent import app as agent_app
from cli.commands.complete import app as complete_app


@pytest.mark.parametrize(
    ("suffix", "media_type"),
    [
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".aif", "audio/aiff"),
        (".aiff", "audio/aiff"),
        (".aac", "audio/aac"),
        (".ogg", "audio/ogg"),
        (".flac", "audio/flac"),
    ],
)
def test_encode_audio_emits_typed_base64_block(tmp_path, suffix: str, media_type: str) -> None:
    audio_path = tmp_path / f"clip{suffix}"
    audio_path.write_bytes(b"audio-bytes")

    block = encode_audio(str(audio_path))

    assert block["type"] == "audio"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == media_type
    assert base64.b64decode(block["source"]["data"]) == b"audio-bytes"


def test_encode_audio_rejects_unsupported_extension(tmp_path) -> None:
    audio_path = tmp_path / "clip.m4a"
    audio_path.write_bytes(b"not-supported")

    with pytest.raises(typer.Exit):
        encode_audio(str(audio_path))


def test_build_payload_keeps_images_and_adds_typed_audio(tmp_path) -> None:
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"image")
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"audio")

    payload = build_payload(
        "Review both",
        "summitflow",
        "critic",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        1,
        False,
        None,
        [str(image_path)],
        audios=[str(audio_path)],
    )

    content = payload["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "audio", "text"]
    assert content[1]["source"]["media_type"] == "audio/wav"


def test_complete_and_agent_help_expose_audio_without_removing_image() -> None:
    runner = CliRunner()

    complete_help = runner.invoke(complete_app, ["--help"])
    agent_help = runner.invoke(agent_app, ["run", "--help"])

    assert complete_help.exit_code == 0
    assert agent_help.exit_code == 0
    for output in (complete_help.output, agent_help.output):
        assert "--audio" in output
        assert "-A" in output
        assert "--image" in output


def test_build_payload_includes_explicit_false_for_use_memory() -> None:
    payload = build_payload(
        "Lean run",
        "summitflow",
        "persona",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        1,
        False,
        None,
    )

    assert payload["use_memory"] is False


def test_build_payload_includes_task_type_when_set() -> None:
    payload = build_payload(
        "Lean run",
        "summitflow",
        "persona",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        "heartbeat",
        1,
        False,
        None,
    )

    assert payload["task_type"] == "heartbeat"


def test_build_payload_includes_agentic_metadata_when_set() -> None:
    payload = build_payload(
        "Inspect only",
        "portfolio-ai",
        "explorer",
        None,
        "/repo",
        None,
        None,
        "trace-1",
        True,
        True,
        None,
        5000,
        False,
        None,
        parent_session_id="parent-1",
        read_only=True,
    )

    assert payload["execute_tools"] is True
    assert payload["max_turns"] == 5000
    assert payload["working_dir"] == "/repo"
    assert payload["parent_session_id"] == "parent-1"
    assert payload["read_only"] is True
