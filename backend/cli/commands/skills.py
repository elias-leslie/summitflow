"""`st skills` — manage harness-neutral agent skills materialized via symlinks.

Canonical skills live in one repo (default ``~/agent-skills``, override with
``ST_AGENT_SKILLS_DIR``). Each harness (Claude Code, Codex, future TUIs) consumes
them through per-item symlinks rather than copies, so a single edit propagates
everywhere and drift is structurally impossible.

Commands:
  install   create/repoint symlinks per manifest (--adopt to replace real dirs)
  doctor    full drift report; nonzero exit on divergence
  status    compact health line for hooks (--json / --quiet)
  sync      pull canonical, install, reseed memory
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from ..output import output_json

app = typer.Typer(help="Manage harness-neutral agent skills (symlink distribution)")


def _canon() -> Path:
    return Path(os.environ.get("ST_AGENT_SKILLS_DIR", "~/agent-skills")).expanduser()


@dataclass
class Harness:
    name: str
    skills_dir: Path
    commands_dir: Path | None
    exclude: list[str] = field(default_factory=list)


def _load_harnesses(canon: Path) -> list[Harness]:
    """Read manifest.toml; fall back to built-in claude/codex defaults."""
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
    ]


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
    counts = {"ok": 0, "missing": 0, "dangling": 0, "wrong-target": 0, "real-copy": 0}
    for _h, dest, target in _expected(canon):
        counts[_classify(dest, target)] += 1
    return counts


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
        typer.echo(f"{state:12} [{h}] {dest}")
    if _canon_dirty(canon):
        problems += 1
        typer.echo(f"dirty-canon  {canon} has uncommitted changes (edits made through a symlink?)")
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
    drifted = counts["wrong-target"] + counts["real-copy"] + counts["dangling"]
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
    # Best-effort: reseed memory from canonical skills (idempotent via skill:<file> tags).
    subprocess.run(["st", "memory", "seed", str(canon / "skills")], check=False)
