"""Neri artifact metadata and explicit local downloads preserve the retained bytes."""

import json
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands import neri

INVESTIGATION = "11111111-1111-4111-8111-111111111111"
EVIDENCE = "22222222-2222-4222-8222-222222222222"
ARTIFACT_PATH = f"/api/runs/{INVESTIGATION}/evidence/{EVIDENCE}/artifact"
CONTENT = b"Retained document\x00\xff\n"


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = SimpleNamespace(download_url=ARTIFACT_PATH, status=200, stream=None)

    def handle(request):
        calls.append(str(request.url))
        if request.url.path == f"/api/runs/{INVESTIGATION}/evidence/{EVIDENCE}":
            return httpx.Response(200, json={
                "id": EVIDENCE, "summary": "Evidence content is separate from artifact metadata",
                "artifact": {"filename": "document.bin", "media_type": "application/octet-stream",
                             "size": len(CONTENT), "download_url": state.download_url},
            })
        headers = {"Location": "https://external.invalid/private"}
        if state.stream is not None:
            return httpx.Response(state.status, headers=headers, stream=state.stream)
        return httpx.Response(state.status, headers=headers, content=CONTENT)

    client = httpx.Client
    monkeypatch.setenv("ST_NERI_API_URL", "https://neri.invalid")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    return calls, state


def test_artifact_command_prints_metadata_only(transport):
    calls, _ = transport
    result = CliRunner().invoke(neri.app, ["evidence", "artifact", INVESTIGATION, EVIDENCE])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "evidence_id": EVIDENCE,
        "artifact": {"filename": "document.bin", "media_type": "application/octet-stream",
                     "size": len(CONTENT), "download_url": ARTIFACT_PATH},
    }
    assert "Evidence content" not in result.output
    assert len(calls) == 1


@pytest.mark.parametrize("absolute", [True, False])
def test_artifact_download_follows_same_origin_metadata_url(transport, tmp_path, absolute):
    calls, state = transport
    if absolute:
        state.download_url = "https://neri.invalid" + ARTIFACT_PATH
    output = tmp_path / "artifact.bin"
    result = CliRunner().invoke(neri.app, ["evidence", "download", INVESTIGATION, EVIDENCE, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == CONTENT
    assert json.loads(result.output) == {"ok": True, "path": str(output), "bytes": len(CONTENT)}
    assert calls[-1] == "https://neri.invalid" + ARTIFACT_PATH
    assert len(calls) == 2


def test_report_download_is_explicit_and_preserves_an_existing_file(transport, tmp_path):
    calls, _ = transport
    output = tmp_path / "report.md"
    args = ["report", "download", INVESTIGATION, "--output", str(output)]
    runner = CliRunner()
    result = runner.invoke(neri.app, args)
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == CONTENT
    assert calls == [f"https://neri.invalid/api/runs/{INVESTIGATION}/report-download"]
    assert runner.invoke(neri.app, args).exit_code != 0
    assert output.read_bytes() == CONTENT
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://external.invalid/private", "//external.invalid/private", "file:///private", "https://neri.invalid@external.invalid/private"])
def test_artifact_download_does_not_follow_external_metadata_urls(transport, tmp_path, url):
    calls, state = transport
    state.download_url = url
    output = tmp_path / "artifact.bin"
    result = CliRunner().invoke(neri.app, ["evidence", "download", INVESTIGATION, EVIDENCE, "--output", str(output)])
    assert result.exit_code != 0
    assert not output.exists()
    assert len(calls) == 1


@pytest.mark.parametrize("status", [302, 404, 500])
def test_failed_or_redirected_download_creates_no_file(transport, tmp_path, status):
    calls, state = transport
    state.status = status
    output = tmp_path / "report.md"
    result = CliRunner().invoke(neri.app, ["report", "download", INVESTIGATION, "--output", str(output)])
    assert result.exit_code == 2
    assert not output.exists()
    assert len(calls) == 1
    assert "external.invalid" not in result.output


def test_interrupted_download_removes_only_its_partial_file(transport, tmp_path):
    calls, state = transport

    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("private-sentinel")

    state.stream = InterruptedStream()
    output = tmp_path / "report.md"
    result = CliRunner().invoke(neri.app, ["report", "download", INVESTIGATION, "--output", str(output)])
    assert result.exit_code == 2
    assert not output.exists()
    assert "private-sentinel" not in result.output
    assert len(calls) == 1
