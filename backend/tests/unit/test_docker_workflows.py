from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest


def test_backend_docker_preserves_lock_paths_and_exact_checked_in_wheel_hashes():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "docker/backend.Dockerfile").read_text()
    assert "WORKDIR /app/backend" in dockerfile
    assert "COPY docker/workspace-packages/ /app/docker/workspace-packages/" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable --no-install-project" in dockerfile
    assert "--no-hashes" not in dockerfile and "uv pip install" not in dockerfile and "*.whl" not in dockerfile
    assert "/app/backend/.venv /app/backend/.venv" in dockerfile
    locked = tomllib.loads((root / "backend/uv.lock").read_text())
    wheels = [package for package in locked["package"] if package["source"].get("path", "").endswith(".whl")]
    assert len(wheels) >= 4
    st_sdk = next(package for package in locked["package"] if package["name"] == "summitflow-st-sdk")
    assert st_sdk["source"] == {"directory": "../packages/st-sdk"}
    assert "COPY packages/st-sdk/ /app/packages/st-sdk/" in dockerfile
    assert "summitflow_st_sdk" not in (root / "docker/workspace-packages/.gitignore").read_text()
    for package in wheels:
        wheel = root / "backend" / package["source"]["path"]
        assert package["wheels"] == [{"filename": wheel.name, "hash": "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()}]


@pytest.mark.parametrize("tamper", [False, True])
def test_docker_build_rejects_same_name_rebuilt_wheel(tmp_path, tamper):
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "docker/backend.Dockerfile").read_text()
    script = dockerfile.split("RUN python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    backend = tmp_path / "backend"
    backend.mkdir()
    wheels = tmp_path / "docker/workspace-packages"
    wheels.mkdir(parents=True)
    wheel = wheels / "fixture-0.1.0-py3-none-any.whl"
    content = b"locked wheel"
    wheel.write_bytes(b"rebuilt wheel" if tamper else content)
    (backend / "uv.lock").write_text('[[package]]\nname = "fixture"\nsource = { path = "../docker/workspace-packages/' + wheel.name + '" }\nwheels = [{ filename = "' + wheel.name + '", hash = "sha256:' + hashlib.sha256(content).hexdigest() + '" }]\n')
    result = subprocess.run(["python3", "-c", script], cwd=backend, capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is not tamper
