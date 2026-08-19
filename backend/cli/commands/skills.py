"""`st skills` — manage harness-neutral agent skills materialized via symlinks.

Canonical skills live in one repo (default ``~/agent-skills``, override with
``ST_AGENT_SKILLS_DIR``). Each harness (Claude Code, Codex, Antigravity/Gemini, future TUIs)
consumes them through per-item symlinks rather than copies, so a single edit propagates
everywhere and drift is structurally impossible.

Commands:
  install        create/repoint symlinks per manifest (--adopt to replace real dirs)
  doctor         full drift report; nonzero exit on divergence
  status         compact health line for hooks (--json / --quiet)
  sync           pull canonical, install, reseed memory
  audit          structural, link, scope, and semantic overlap audit of all skills
  create         scaffold a new canonical skill and link to all harnesses
  import-github  download/import a skill from GitHub, validate, link, and audit
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from ..output import output_error, output_json, output_success

app = typer.Typer(help="Manage harness-neutral agent skills (symlink distribution, audit, and import)")


def _canon() -> Path:
    return Path(os.environ.get("ST_AGENT_SKILLS_DIR", "~/agent-skills")).expanduser()


@dataclass
class Harness:
    name: str
    skills_dir: Path
    commands_dir: Path | None
    exclude: list[str] = field(default_factory=list)


def _load_harnesses(canon: Path) -> list[Harness]:
    """Read manifest.toml; fall back to built-in claude/codex/gemini defaults."""
    manifest = canon / "manifest.toml"
    if manifest.exists():
        data = tomllib.loads(manifest.read_text())
        out: list[Harness] = []
        for name, cfg in (data.get("harness") or {}).items():
            sd = cfg.get("skills_dir", "").strip()
            cd = cfg.get("commands_dir", "").strip()
            if not sd:
                continue
            out.append(
                Harness(
                    name=name,
                    skills_dir=Path(sd).expanduser(),
                    commands_dir=Path(cd).expanduser() if cd else None,
                    exclude=list(cfg.get("exclude") or []),
                )
            )
        if out:
            return out
    return [
        Harness("claude", Path("~/.claude/skills").expanduser(), Path("~/.claude/commands").expanduser()),
        Harness("codex", Path("~/.codex/skills").expanduser(), None, ["zzpersona_refiner"]),
        Harness("gemini", Path("~/.gemini/config/skills").expanduser(), None, ["zzpersona_refiner"]),
    ]


_IGNORE_NAMES = {".system", ".git", ".DS_Store", ".codex-system-skills.marker"}


def _canonical_items(canon: Path) -> tuple[list[str], list[str]]:
    """Return (skill dir names excluding _shared, command file names)."""
    sdir = canon / "skills"
    cdir = canon / "commands"
    skills = sorted(p.name for p in sdir.iterdir() if p.is_dir() and p.name != "_shared") if sdir.is_dir() else []
    commands = sorted(p.name for p in cdir.iterdir() if p.is_file()) if cdir.is_dir() else []
    return skills, commands


def _classify(dest: Path, target: Path) -> str:
    """ok | missing | dangling | wrong-target | real-copy."""
    if not dest.exists() and not dest.is_symlink():
        return "missing"
    if dest.is_symlink():
        try:
            resolved = dest.resolve(strict=False)
        except OSError:
            return "dangling"
        if not dest.exists():
            return "dangling"
        return "ok" if resolved == target.resolve(strict=False) else "wrong-target"
    return "real-copy"  # a real dir/file shadowing canonical — drift


def _expected(canon: Path) -> list[tuple[str, Path, Path]]:
    """Yield (harness, dest, canonical_target) for every item that should be a symlink."""
    skills, commands = _canonical_items(canon)
    rows: list[tuple[str, Path, Path]] = []
    for h in _load_harnesses(canon):
        rows.append((h.name, h.skills_dir / "_shared", canon / "skills" / "_shared"))
        for s in skills:
            if s in h.exclude:
                continue
            rows.append((h.name, h.skills_dir / s, canon / "skills" / s))
        if h.commands_dir is not None:
            for c in commands:
                rows.append((h.name, h.commands_dir / c, canon / "commands" / c))
    return rows


def _unmanaged(canon: Path) -> list[tuple[str, Path, str]]:
    """Find any item in a harness dir that is not declared in canonical expectations."""
    expected_by_harness: dict[str, set[Path]] = {}
    for h, dest, _target in _expected(canon):
        expected_by_harness.setdefault(h, set()).add(dest)

    unmanaged: list[tuple[str, Path, str]] = []
    for h in _load_harnesses(canon):
        expected_dests = expected_by_harness.get(h.name, set())
        if h.skills_dir.is_dir():
            for item in sorted(h.skills_dir.iterdir()):
                if item.name in _IGNORE_NAMES:
                    continue
                if item not in expected_dests:
                    kind = "unmanaged-link" if item.is_symlink() else "unmanaged-copy"
                    unmanaged.append((h.name, item, kind))
        if h.commands_dir and h.commands_dir.is_dir():
            for item in sorted(h.commands_dir.iterdir()):
                if item.name in _IGNORE_NAMES:
                    continue
                if item not in expected_dests:
                    kind = "unmanaged-link" if item.is_symlink() else "unmanaged-copy"
                    unmanaged.append((h.name, item, kind))
    return unmanaged


def _canon_dirty(canon: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(canon), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        return bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def _scan(canon: Path) -> dict[str, int]:
    counts = {"ok": 0, "missing": 0, "dangling": 0, "wrong-target": 0, "real-copy": 0, "unmanaged": 0}
    for _h, dest, target in _expected(canon):
        counts[_classify(dest, target)] += 1
    counts["unmanaged"] = len(_unmanaged(canon))
    return counts


# --- Audit Subsystem ---

def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    """Parse YAML frontmatter from markdown text. Returns (frontmatter, body, errors)."""
    if not text.startswith("---"):
        return {}, text, ["Missing starting '---' YAML frontmatter marker"]
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text, ["Malformed YAML frontmatter: closing '---' not found"]
    try:
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            return {}, parts[2], ["Frontmatter must be a YAML dictionary/mapping"]
        return fm, parts[2], []
    except Exception as e:
        return {}, parts[2], [f"YAML parsing error in frontmatter: {e}"]


def _audit_single_skill(skill_dir: Path, auto_fix: bool = False) -> dict[str, Any]:
    """Audit a single skill directory for frontmatter, link integrity, scripts, and progressive disclosure."""
    errors: list[str] = []
    warnings: list[str] = []
    fixes_applied: list[str] = []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {
            "name": skill_dir.name,
            "status": "fail",
            "errors": [f"Missing required SKILL.md in {skill_dir}"],
            "warnings": [],
            "fixes": [],
            "description": "",
            "lines": 0,
        }

    raw_content = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body, fm_errors = _parse_frontmatter(raw_content)
    errors.extend(fm_errors)

    name = fm.get("name")
    if not name:
        errors.append("Missing required 'name' field in frontmatter")
    elif not isinstance(name, str):
        errors.append("'name' must be a string")
    elif not re.match(r"^[a-zA-Z0-9_-]+$", name):
        errors.append(f"Invalid characters in name '{name}' (must be alphanumeric, hyphen, or underscore)")
    elif name != skill_dir.name:
        errors.append(f"Frontmatter name '{name}' does not match directory name '{skill_dir.name}'")

    desc = fm.get("description")
    if not desc:
        errors.append("Missing required 'description' field in frontmatter (needed for agent skill routing)")
    elif not isinstance(desc, str):
        errors.append("'description' must be a string")
    elif len(desc.strip()) < 20:
        errors.append(f"Description too short ({len(desc.strip())} chars; min 20 chars recommended for clear routing)")

    # Check for hardcoded harness paths that break cross-harness neutrality
    if skill_dir.name not in ("zzpersona_refiner", "zzskills"):
        for forbidden in ["~/.claude", "~/.codex", "~/.gemini", "/home/kasadis/.claude", "/home/kasadis/.codex", "/home/kasadis/.gemini"]:
            if forbidden in raw_content:
                warnings.append(f"Hardcoded harness path found: '{forbidden}' (use relative '_shared/...' or neutral commands)")

    # Check relative markdown links
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", body):
        link_target = match.group(2).strip().split("#")[0]
        if not link_target or link_target.startswith(("http://", "https://", "mailto:", "file://", "#")):
            continue
        resolved_target = (skill_dir / link_target).resolve()
        if not resolved_target.exists():
            errors.append(f"Broken relative markdown link: '{match.group(0)}' -> '{link_target}' (file not found)")

    # Check scripts / bin executability
    for sub in ["scripts", "bin"]:
        sub_dir = skill_dir / sub
        if sub_dir.is_dir():
            for script_file in sub_dir.iterdir():
                if script_file.is_file() and not os.access(script_file, os.X_OK):
                    if auto_fix:
                        script_file.chmod(script_file.stat().st_mode | 0o111)
                        fixes_applied.append(f"Made {sub}/{script_file.name} executable (+x)")
                    else:
                        warnings.append(f"Script '{sub}/{script_file.name}' is not executable (run chmod +x)")

    # Progressive disclosure check
    lines = len(raw_content.splitlines())
    if lines > 400 and skill_dir.name != "zzpersona_refiner":
        warnings.append(f"Large SKILL.md ({lines} lines). Consider moving reference manuals into 'references/' for progressive disclosure")

    status = "fail" if errors else ("warn" if warnings else "ok")
    return {
        "name": skill_dir.name,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "fixes": fixes_applied,
        "description": str(desc or ""),
        "lines": lines,
    }


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "on", "with", "to", "from", "by",
    "as", "is", "are", "this", "that", "it", "when", "use", "only", "not", "do", "all",
    "any", "be", "your", "you", "our", "their", "into", "than", "then", "more", "also",
    "using", "used", "will", "can", "should", "must"
}


def _detect_semantic_overlaps(skill_audits: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect potential trigger collisions or scope ambiguities across skills."""
    tokens_by_skill: dict[str, set[str]] = {}
    for name, audit in skill_audits.items():
        desc = audit.get("description", "").lower()
        words = set(re.findall(r"[a-zA-Z0-9_-]{3,}", desc)) - _STOP_WORDS
        tokens_by_skill[name] = words

    overlaps: list[dict[str, Any]] = []
    names = sorted(tokens_by_skill.keys())
    for i, s1 in enumerate(names):
        for s2 in names[i + 1:]:
            t1, t2 = tokens_by_skill[s1], tokens_by_skill[s2]
            if not t1 or not t2:
                continue
            shared = t1 & t2
            if len(shared) >= 4:
                jaccard = len(shared) / len(t1 | t2)
                if jaccard >= 0.10 or len(shared) >= 5:
                    overlaps.append({
                        "skills": [s1, s2],
                        "shared_terms": sorted(shared),
                        "similarity": round(jaccard, 2),
                    })
    return overlaps


def _audit_all_skills(canon: Path, auto_fix: bool = False) -> dict[str, Any]:
    """Run comprehensive audit across all canonical skills and harnesses."""
    skills_dir = canon / "skills"
    skill_audits: dict[str, dict[str, Any]] = {}
    if skills_dir.is_dir():
        for sdir in sorted(skills_dir.iterdir()):
            if not sdir.is_dir() or sdir.name == "_shared":
                continue
            skill_audits[sdir.name] = _audit_single_skill(sdir, auto_fix=auto_fix)

    overlaps = _detect_semantic_overlaps(skill_audits)
    drift = _scan(canon)
    dirty = _canon_dirty(canon)

    total_errors = sum(len(a["errors"]) for a in skill_audits.values())
    total_warnings = sum(len(a["warnings"]) for a in skill_audits.values())
    drift_problems = drift["wrong-target"] + drift["real-copy"] + drift["dangling"] + drift["unmanaged"] + (1 if dirty else 0)

    if total_errors > 0 or drift_problems > 0:
        overall = "fail"
    elif total_warnings > 0 or len(overlaps) > 0:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "canon": str(canon),
        "overall": overall,
        "skills": skill_audits,
        "overlaps": overlaps,
        "drift": drift,
        "canon_dirty": dirty,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "drift_problems": drift_problems,
    }


# --- Import / Ingestion Subsystem ---

def _parse_github_source(source: str, default_ref: str = "main") -> tuple[str, str, str, str | None]:
    """Parse 'owner/repo', 'owner/repo/sub/path', or GitHub URL into (owner, repo, ref, subpath)."""
    s = source.strip()
    if s.startswith("https://") or s.startswith("http://") or s.startswith("git@"):
        if "github.com" not in s:
            raise ValueError(f"Only GitHub sources are currently supported: {source}")
        if s.startswith("git@github.com:"):
            path_part = s.split("git@github.com:", 1)[1]
            if path_part.endswith(".git"):
                path_part = path_part[:-4]
            parts = [p for p in path_part.split("/") if p]
            owner = parts[0]
            repo = parts[1]
            ref = default_ref
            subpath = "/".join(parts[2:]) if len(parts) > 2 else None
            return owner, repo, ref, subpath
        parsed = urllib.parse.urlparse(s)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL structure: {source}")
        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        ref = default_ref
        subpath = None
        if len(parts) > 2:
            if parts[2] in ("tree", "blob") and len(parts) >= 4:
                ref = parts[3]
                subpath = "/".join(parts[4:]) if len(parts) > 4 else None
            else:
                subpath = "/".join(parts[2:])
        return owner, repo, ref, subpath

    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub shorthand '{source}'. Expected 'owner/repo' or 'owner/repo/path'")
    owner, repo = parts[0], parts[1]
    ref = default_ref
    subpath = "/".join(parts[2:]) if len(parts) > 2 else None
    return owner, repo, ref, subpath


def _download_and_extract_skill(owner: str, repo: str, ref: str, subpath: str | None, temp_dir: Path) -> Path:
    """Clone or download the repo and return the directory containing the skill."""
    clone_dir = temp_dir / f"{owner}_{repo}"
    repo_url = f"https://github.com/{owner}/{repo}.git"
    res = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(clone_dir)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        res2 = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(clone_dir)],
            capture_output=True, text=True,
        )
        if res2.returncode != 0:
            raise RuntimeError(f"Failed to clone {repo_url}: {res.stderr.strip() or res2.stderr.strip()}")

    search_root = clone_dir / subpath if subpath else clone_dir
    if not search_root.exists():
        raise FileNotFoundError(f"Subpath '{subpath}' not found inside {owner}/{repo}")

    if (search_root / "SKILL.md").exists():
        return search_root

    skill_mds = list(search_root.glob("**/SKILL.md"))
    if len(skill_mds) == 1:
        return skill_mds[0].parent

    return search_root


# --- Commands ---

@app.command()
def audit(
    ctx: typer.Context,
    strict: Annotated[bool, typer.Option("--strict", help="Exit nonzero on warnings or overlaps as well as errors")] = False,
    fix: Annotated[bool, typer.Option("--fix", help="Automatically fix issues like script permissions (+x)")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON audit report")] = False,
) -> None:
    """Run comprehensive audit of canonical skills, link integrity, and scope overlaps."""
    canon = _canon()
    report = _audit_all_skills(canon, auto_fix=fix)

    if as_json:
        output_json(report)
        return

    typer.echo(f"=== Canonical Skills Audit ({canon}) ===\n")
    for name, res in report["skills"].items():
        status = res["status"]
        symbol = {"ok": "✓", "warn": "⚠", "fail": "✗"}[status]
        typer.echo(f"[{symbol}] {name:24} ({status.upper()})")
        for err in res["errors"]:
            typer.echo(f"    ERROR: {err}")
        for warn in res["warnings"]:
            typer.echo(f"    WARN:  {warn}")
        for f in res.get("fixes", []):
            typer.echo(f"    FIXED: {f}")

    if report["overlaps"]:
        typer.echo("\n--- Semantic Overlap & Scope Analysis ---")
        for ov in report["overlaps"]:
            s1, s2 = ov["skills"]
            shared = ", ".join(ov["shared_terms"])
            typer.echo(f"  • Overlap [{s1} <-> {s2}] (similarity: {ov['similarity']})")
            typer.echo(f"    Shared trigger terms: {shared}")

    typer.echo(f"\n--- Harness Symlink & Drift Status ---")
    drift = report["drift"]
    dirty = report["canon_dirty"]
    typer.echo(
        f"Harness links: {drift['ok']} linked, {drift['wrong-target'] + drift['real-copy'] + drift['dangling'] + drift['unmanaged']} drifted, "
        f"{drift['missing']} missing, {drift['unmanaged']} unmanaged{' (canon dirty)' if dirty else ''}"
    )

    typer.echo(f"\nAudit Summary: {report['total_errors']} error(s), {report['total_warnings']} warning(s), {len(report['overlaps'])} overlap note(s).")
    if report["overall"] == "fail" or (strict and report["overall"] != "pass"):
        raise typer.Exit(1)


@app.command(name="import-github")
def import_github(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="GitHub URL, 'owner/repo', or subpath URL")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="Destination skill name")] = None,
    ref: Annotated[str, typer.Option("--ref", "-r", help="Git branch/tag")] = "main",
    subpath: Annotated[str | None, typer.Option("--subpath", "-s", help="Subpath within repository")] = None,
    adopt: Annotated[bool, typer.Option("--adopt", help="Adopt and materialize into all harnesses")] = True,
) -> None:
    """Import a skill from GitHub, normalize frontmatter, link, and audit."""
    canon = _canon()
    try:
        owner, repo, resolved_ref, resolved_subpath = _parse_github_source(source, default_ref=ref)
    except Exception as e:
        output_error(f"Invalid source: {e}")
        raise typer.Exit(1)

    effective_subpath = subpath or resolved_subpath
    typer.echo(f"Fetching {owner}/{repo} (ref: {resolved_ref}, subpath: {effective_subpath or 'root'})...")

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        try:
            skill_source_dir = _download_and_extract_skill(owner, repo, resolved_ref, effective_subpath, temp_dir)
        except Exception as e:
            output_error(f"Failed to download skill: {e}")
            raise typer.Exit(1)

        skill_md = skill_source_dir / "SKILL.md"
        if not skill_md.exists():
            readme = skill_source_dir / "README.md" if (skill_source_dir / "README.md").exists() else (skill_source_dir / "readme.md")
            if readme.exists():
                readme_text = readme.read_text(encoding="utf-8", errors="replace")
                synth_name = name or (effective_subpath.split("/")[-1] if effective_subpath else repo).lower()
                synth_desc = f"Use for {synth_name} workflows imported from {owner}/{repo}."
                skill_md.write_text(f"---\nname: {synth_name}\ndescription: {synth_desc}\n---\n\n{readme_text}")
            else:
                output_error(f"No SKILL.md or README.md found in imported directory.")
                raise typer.Exit(1)

        raw_content = skill_md.read_text(encoding="utf-8", errors="replace")
        fm, body, _ = _parse_frontmatter(raw_content)

        dest_name = (name or fm.get("name") or (effective_subpath.split("/")[-1] if effective_subpath else repo)).strip().lower()
        dest_name = re.sub(r"[^a-z0-9_-]+", "-", dest_name)

        if not fm.get("name") or fm.get("name") != dest_name:
            fm["name"] = dest_name
            if not fm.get("description"):
                fm["description"] = f"Use for {dest_name} procedures and tasks."
            new_frontmatter = yaml.dump(fm, sort_keys=False).strip()
            skill_md.write_text(f"---\n{new_frontmatter}\n---\n\n{body.strip()}\n")

        dest_dir = canon / "skills" / dest_name
        if dest_dir.exists():
            typer.echo(f"Updating existing skill at {dest_dir}...")
            shutil.rmtree(dest_dir)
        else:
            typer.echo(f"Creating new skill at {dest_dir}...")

        shutil.copytree(skill_source_dir, dest_dir, ignore=shutil.ignore_patterns(".git", "*.pyc", "__pycache__"))

    typer.echo(f"Linking {dest_name} into all harnesses...")
    script = canon / "install.sh"
    if script.exists():
        args = ["bash", str(script)]
        if adopt:
            args.append("--adopt")
        subprocess.run(args, check=False)

    typer.echo(f"\nRunning audit on {dest_name}...")
    single_audit = _audit_single_skill(dest_dir, auto_fix=True)
    if single_audit["status"] == "fail":
        typer.echo(f"✗ Imported skill has validation errors:")
        for err in single_audit["errors"]:
            typer.echo(f"    {err}")
    else:
        output_success(f"Skill '{dest_name}' successfully imported and linked!")


@app.command()
def create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the skill (lowercase slug, e.g. docker-helper)")],
    description: Annotated[str | None, typer.Option("--description", "-d", help="Trigger description")] = None,
    adopt: Annotated[bool, typer.Option("--adopt", help="Adopt and materialize symlinks immediately")] = True,
) -> None:
    """Scaffold a new canonical skill, link to all harnesses, and audit."""
    canon = _canon()
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower())
    skill_dir = canon / "skills" / slug
    if skill_dir.exists():
        output_error(f"Skill '{slug}' already exists at {skill_dir}")
        raise typer.Exit(1)

    skill_dir.mkdir(parents=True, exist_ok=True)
    desc = description or f"Use when working with {slug} tasks and workflows."
    skill_content = f"""---
name: {slug}
description: {desc}
---

# {slug.replace('-', ' ').title()} Guide

Provide clear, step-by-step procedures and runbooks for the agent.

## Quick Commands
```bash
# Example commands
```
"""
    (skill_dir / "SKILL.md").write_text(skill_content)
    typer.echo(f"Created canonical skill template at {skill_dir}/SKILL.md")

    script = canon / "install.sh"
    if script.exists():
        args = ["bash", str(script)]
        if adopt:
            args.append("--adopt")
        subprocess.run(args, check=False)

    typer.echo(f"\nRunning audit...")
    res = _audit_single_skill(skill_dir)
    output_success(f"Skill '{slug}' created and materialized across all harnesses.")


@app.command()
def install(
    ctx: typer.Context,
    adopt: Annotated[bool, typer.Option("--adopt", help="Replace existing real dirs/files with symlinks")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show actions, change nothing")] = False,
) -> None:
    """Materialize canonical skills into each harness via per-item symlinks."""
    canon = _canon()
    script = canon / "install.sh"
    if not script.exists():
        typer.echo(f"error: {script} not found (is {canon} cloned?)", err=True)
        raise typer.Exit(2)
    args = ["bash", str(script)]
    if adopt:
        args.append("--adopt")
    if dry_run:
        args.append("--dry-run")
    raise typer.Exit(subprocess.run(args).returncode)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Full drift report. Exits nonzero when any item diverges from canonical."""
    canon = _canon()
    if not (canon / "skills").is_dir():
        typer.echo(f"error: canonical skills not found at {canon}", err=True)
        raise typer.Exit(2)
    problems = 0
    for h, dest, target in _expected(canon):
        state = _classify(dest, target)
        if state == "ok":
            continue
        problems += 1
        typer.echo(f"{state:14} [{h}] {dest}")
    for h, dest, kind in _unmanaged(canon):
        problems += 1
        typer.echo(f"{kind:14} [{h}] {dest}")
    if _canon_dirty(canon):
        problems += 1
        typer.echo(f"dirty-canon    {canon} has uncommitted changes (edits made through a symlink?)")
    if problems == 0:
        typer.echo(f"ok: all skills materialized as symlinks into canonical ({canon})")
        raise typer.Exit(0)
    typer.echo(f"\n{problems} issue(s). Run `st skills install --adopt` to fix real-copy drift.", err=True)
    raise typer.Exit(1)


@app.command()
def status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="One line; only emit when drifted")] = False,
) -> None:
    """Compact health, cheap enough for SessionStart hooks."""
    canon = _canon()
    counts = _scan(canon)
    dirty = _canon_dirty(canon)
    drifted = counts["wrong-target"] + counts["real-copy"] + counts["dangling"] + counts["unmanaged"]
    if as_json:
        output_json({"canon": str(canon), "counts": counts, "dirty_canon": dirty, "drifted": drifted})
        return
    if quiet and drifted == 0 and not dirty:
        return
    flag = "DRIFT" if (drifted or dirty) else "ok"
    typer.echo(
        f"skills {flag}: {counts['ok']} linked, {drifted} drifted, "
        f"{counts['missing']} missing{' , canon dirty' if dirty else ''}"
    )


@app.command()
def sync(ctx: typer.Context) -> None:
    """Pull canonical, re-install symlinks, reseed memory from skills."""
    canon = _canon()
    if (canon / ".git").exists():
        subprocess.run(["git", "-C", str(canon), "pull", "--ff-only"], check=False)
    install_script = canon / "install.sh"
    if install_script.exists():
        subprocess.run(["bash", str(install_script)], check=False)
    subprocess.run(["st", "memory", "seed", str(canon / "skills")], check=False)
