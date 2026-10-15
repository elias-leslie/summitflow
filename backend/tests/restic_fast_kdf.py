"""Re-key freshly initialized test Restic repositories with minimal scrypt cost.

Restic calibrates its key derivation to ~0.7s and pays it on every command.
Real-repository tests run dozens of commands, so that cost dominated them.
The re-keyed file wraps the same master key in Restic's own key format;
repository contents, IDs and every later command stay real.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.poly1305 import Poly1305


def _derive(password: bytes, salt: bytes, n: int, r: int, p: int) -> tuple[bytes, bytes, bytes]:
    derived = hashlib.scrypt(password, salt=salt, n=n, r=r, p=p, maxmem=2**31 - 1, dklen=64)
    return derived[:32], derived[32:48], derived[48:64]


def _mac(k: bytes, r: bytes, nonce: bytes, data: bytes) -> bytes:
    # Restic's Poly1305-AES: the one-time pad is AES_k(nonce), which is the
    # first CTR keystream block for counter=nonce (no raw block mode needed).
    pad = Cipher(algorithms.AES(k), modes.CTR(nonce)).encryptor().update(bytes(16))
    return Poly1305.generate_tag(r + pad, data)


def rekey_repository(repository: Path, password_file: Path) -> None:
    password = password_file.read_bytes().rstrip(b"\r\n")
    (path,) = (repository / "keys").iterdir()
    key = json.loads(path.read_text())
    encryption, k, r = _derive(password, base64.b64decode(key["salt"]), key["N"], key["r"], key["p"])
    sealed = base64.b64decode(key["data"])
    nonce, body, tag = sealed[:16], sealed[16:-16], sealed[-16:]
    if _mac(k, r, nonce, body) != tag:
        raise ValueError("fixture Restic key does not match its password file")
    master = Cipher(algorithms.AES(encryption), modes.CTR(nonce)).decryptor().update(body)
    salt, nonce = os.urandom(64), os.urandom(16)
    encryption, k, r = _derive(password, salt, 16, 1, 1)
    body = Cipher(algorithms.AES(encryption), modes.CTR(nonce)).encryptor().update(master)
    key.update(N=16, r=1, p=1, salt=base64.b64encode(salt).decode(),
               data=base64.b64encode(nonce + body + _mac(k, r, nonce, body)).decode())
    content = json.dumps(key).encode()
    (repository / "keys" / hashlib.sha256(content).hexdigest()).write_bytes(content)
    path.unlink()


@pytest.fixture
def fast_restic_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.backup_restic import ResticAdapter, command_operation

    original = ResticAdapter._run

    def run(self: ResticAdapter, command: list[str], *, phase: str, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        result = original(self, command, phase=phase, **kwargs)
        if command_operation(command)[0] == "restic init":
            repository = Path(command[command.index("--repo") + 1])
            if repository.is_dir():
                rekey_repository(repository, Path(command[command.index("--password-file") + 1]))
        return result

    monkeypatch.setattr(ResticAdapter, "_run", run)
