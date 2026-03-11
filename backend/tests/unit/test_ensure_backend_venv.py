import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "ensure_backend_venv.py"
_SPEC = importlib.util.spec_from_file_location("ensure_backend_venv", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_same_venv = _MODULE._same_venv


def test_same_venv_accepts_python_and_python3_shims_in_same_env() -> None:
    root = Path("/tmp/project/backend/.venv")

    assert _same_venv(root / "bin" / "python", root / "bin" / "python3")


def test_same_venv_rejects_different_envs_even_if_real_binary_matches() -> None:
    current = Path("/tmp/agent-hub/backend/.venv/bin/python")
    target = Path("/tmp/summitflow/backend/.venv/bin/python")

    assert _same_venv(current, target) is False
