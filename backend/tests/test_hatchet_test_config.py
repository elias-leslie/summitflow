"""Collection keeps real Hatchet decorators without operator credentials."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("inherited", [False, True])
def test_hatchet_collection_config_is_offline(inherited: bool) -> None:
    backend = Path(__file__).resolve().parents[1]
    env = {"PATH": os.defpath, "PYTHON_DOTENV_DISABLED": "1"}
    if inherited:
        env.update({
            "HATCHET_CLIENT_TOKEN": "synthetic-operator-token-must-be-replaced",
            "HATCHET_CLIENT_HOST_PORT": "operator.invalid:7070",
            "HATCHET_CLIENT_SERVER_URL": "https://operator.invalid",
            "HATCHET_CLIENT_TENANT_ID": "operator-tenant",
        })
    result = subprocess.run(
        [sys.executable, "-c", '''
import runpy
from unittest.mock import patch

runpy.run_path("tests/conftest.py")
from app.hatchet_app import get_hatchet, hatchet
from hatchet_sdk.runnables.workflow import Standalone, Workflow

# Client construction and decorators must remain local SDK operations.
with patch("socket.socket.connect", side_effect=AssertionError("network access")):
    client = get_hatchet()
    config = client._client.config
    assert config.tenant_id == "00000000-0000-0000-0000-000000000000"
    assert config.host_port == "127.0.0.1:1"
    assert config.server_url == "http://127.0.0.1:1"
    assert config.token.endswith(".")  # Unsigned fixture; no server authority.

    def original(input, context) -> dict[str, str]:
        return {"status": "local"}

    task = hatchet.task(name="offline-test")(original)
    assert isinstance(task, Standalone)
    assert task._task.fn is original
    assert task._task.fn(None, None) == {"status": "local"}
    workflow = hatchet.workflow(name="offline-workflow")
    assert isinstance(workflow, Workflow)
'''],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
