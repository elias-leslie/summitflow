from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import skills

runner = CliRunner()


def test_load_harnesses_with_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("""[harness.claude]
skills_dir = "~/.claude/skills"
commands_dir = "~/.claude/commands"
exclude = []

[harness.codex]
skills_dir = "~/.codex/skills"
exclude = ["zzpersona_refiner"]

[harness.gemini]
skills_dir = "~/.gemini/config/skills"
exclude = ["zzpersona_refiner"]
""")
    harnesses = skills._load_harnesses(tmp_path)
    names = [h.name for h in harnesses]
    assert names == ["claude", "codex", "gemini"]
    gemini = next(h for h in harnesses if h.name == "gemini")
    assert gemini.skills_dir == Path("~/.gemini/config/skills").expanduser()
    assert gemini.commands_dir is None
    assert gemini.exclude == ["zzpersona_refiner"]


def test_load_harnesses_fallback(tmp_path: Path) -> None:
    harnesses = skills._load_harnesses(tmp_path)
    names = [h.name for h in harnesses]
    assert "claude" in names
    assert "codex" in names
    assert "gemini" in names


def test_classify_states(tmp_path: Path) -> None:
    target = tmp_path / "canon" / "skill-a"
    target.mkdir(parents=True)

    dest_ok = tmp_path / "dest_ok"
    dest_ok.symlink_to(target)
    assert skills._classify(dest_ok, target) == "ok"

    dest_missing = tmp_path / "dest_missing"
    assert skills._classify(dest_missing, target) == "missing"

    dest_real = tmp_path / "dest_real"
    dest_real.mkdir()
    assert skills._classify(dest_real, target) == "real-copy"

    other_target = tmp_path / "other"
    other_target.mkdir()
    dest_wrong = tmp_path / "dest_wrong"
    dest_wrong.symlink_to(other_target)
    assert skills._classify(dest_wrong, target) == "wrong-target"


def test_unmanaged_detection(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills" / "skill-a").mkdir(parents=True)
    test_harness = tmp_path / "test_harness"
    test_harness.mkdir(parents=True)
    (canon / "manifest.toml").write_text(f"[harness.test]\nskills_dir = \"{test_harness}\"\n")
    (test_harness / "skill-a").symlink_to(canon / "skills" / "skill-a")
    (test_harness / "unmanaged-real").mkdir()
    (test_harness / ".system").mkdir()

    unmanaged = skills._unmanaged(canon)
    assert len(unmanaged) == 1
    hname, path, kind = unmanaged[0]
    assert hname == "test"
    assert path.name == "unmanaged-real"
    assert kind == "unmanaged-copy"


def test_doctor_and_status(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills" / "_shared").mkdir(parents=True)
    (canon / "skills" / "skill-a").mkdir(parents=True)
    test_harness = tmp_path / "test_harness"
    test_harness.mkdir(parents=True)
    (canon / "manifest.toml").write_text(f"[harness.test]\nskills_dir = \"{test_harness}\"\n")
    (test_harness / "_shared").symlink_to(canon / "skills" / "_shared")
    (test_harness / "skill-a").symlink_to(canon / "skills" / "skill-a")

    with patch.object(skills, "_canon", return_value=canon), patch.object(skills, "_canon_dirty", return_value=False):
        res = runner.invoke(skills.app, ["status"])
        assert res.exit_code == 0
        assert "skills ok" in res.stdout

        res_doc = runner.invoke(skills.app, ["doctor"])
        assert res_doc.exit_code == 0
        assert "ok: all skills materialized" in res_doc.stdout
