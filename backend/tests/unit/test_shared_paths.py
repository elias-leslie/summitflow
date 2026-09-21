from pathlib import Path

from app.utils import shared_paths


def test_host_config_root_is_independent_from_immutable_source_root(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = tmp_path / "state" / "releases" / "build" / "source"
    host_root = tmp_path / "checkout"
    monkeypatch.setenv("SUMMITFLOW_ROOT", str(release_root))
    monkeypatch.setenv("SUMMITFLOW_HOST_CONFIG_ROOT", str(host_root))

    assert shared_paths.get_repo_root() == release_root.resolve()
    assert shared_paths.get_host_config_root() == host_root.resolve()


def test_host_config_root_defaults_to_repo_root(monkeypatch) -> None:
    monkeypatch.delenv("SUMMITFLOW_HOST_CONFIG_ROOT", raising=False)

    assert shared_paths.get_host_config_root() == shared_paths.get_repo_root()
