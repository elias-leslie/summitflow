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

    # ok
    dest_ok = tmp_path / "dest_ok"
    dest_ok.symlink_to(target)
    assert skills._classify(dest_ok, target) == "ok"

    # missing
    dest_missing = tmp_path / "dest_missing"
    assert skills._classify(dest_missing, target) == "missing"

    # real-copy
    dest_real = tmp_path / "dest_real"
    dest_real.mkdir()
    assert skills._classify(dest_real, target) == "real-copy"

    # wrong-target
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


def test_audit_single_skill_validation(tmp_path: Path) -> None:
    skill_dir = tmp_path / "valid-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: valid-skill
description: Use when testing the valid skill audit capabilities in summitflow.
---

# Valid Skill Title

Step by step procedures.
""")
    res = skills._audit_single_skill(skill_dir)
    assert res["status"] == "ok"
    assert len(res["errors"]) == 0

    # Test broken relative link
    (skill_dir / "SKILL.md").write_text("""---
name: valid-skill
description: Use when testing the valid skill audit capabilities in summitflow.
---

Check [documentation](references/missing.md) here.
""")
    res2 = skills._audit_single_skill(skill_dir)
    assert res2["status"] == "fail"
    assert any("Broken relative markdown link" in e for e in res2["errors"])


def test_parse_github_source() -> None:
    owner, repo, ref, subpath = skills._parse_github_source("owner/my-repo")
    assert owner == "owner"
    assert repo == "my-repo"
    assert ref == "main"
    assert subpath is None

    owner, repo, ref, subpath = skills._parse_github_source("https://github.com/my-org/awesome-skills/tree/develop/skills/docker")
    assert owner == "my-org"
    assert repo == "awesome-skills"
    assert ref == "develop"
    assert subpath == "skills/docker"


def test_create_skill_scaffold(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills").mkdir(parents=True)
    with patch.object(skills, "_canon", return_value=canon):
        res = runner.invoke(skills.app, ["create", "test-helper", "--description", "Use for test helper automated execution routines."])
        assert res.exit_code == 0
        skill_file = canon / "skills" / "test-helper" / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text()
        assert "name: test-helper" in content
        assert "Use for test helper" in content
