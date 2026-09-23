"""The live producer's manifest is consumable before SummitFlow is installed."""

import hashlib
import subprocess
import sys
from pathlib import Path


def test_offsite_manifest_roundtrips_through_standalone_recovery(tmp_path, monkeypatch):
    from app.tasks import backup_native_offsite as offsite

    ciphertext = b"one unchanged encrypted archive across multiple transfer parts"
    archive = tmp_path / "source-20260923-120000.tar.gz.age"
    archive.write_bytes(ciphertext)
    staging = tmp_path / "staging"
    staging.mkdir()
    download = tmp_path / "download"
    download.mkdir()
    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 7)

    def publish(local_path, *, remote_name, expected_checksum, **_kwargs):
        payload = local_path.read_bytes()
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == expected_checksum
        (download / remote_name).write_bytes(payload)
        return {
            "location": f"google-drive://fixture/{remote_name}",
            "uploaded_bytes": len(payload),
            "downloaded_bytes": len(payload),
            "reused": False,
        }

    monkeypatch.setattr(offsite, "_publish_verified_file", publish)
    produced = offsite._replicate_parts(
        archive,
        source_folder_uri="google-drive://fixture",
        local_checksum="sha256:" + hashlib.sha256(ciphertext).hexdigest(),
        temporary_dir=staging,
        retry=False,
    )
    assert produced["layout"] == "parts-v1"
    restored = tmp_path / "restored"
    restored.mkdir()
    destination = restored / archive.name
    script = Path(__file__).resolve().parents[3] / "scripts/recovery-bootstrap.py"
    result = subprocess.run(
        [sys.executable, str(script), "--assemble-parts",
         str(download / f"{archive.name}.parts.json"), "--output-file", str(destination)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert destination.read_bytes() == ciphertext
    assert archive.read_bytes() == ciphertext
