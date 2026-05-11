"""Vault wiki commands — pure filesystem ops against /srv/workspaces/vault/."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(
    name="wiki",
    help="Vault wiki: page lookup, search, lint, ingest, log.",
    no_args_is_help=True,
)

VAULT_ROOT = Path("/srv/workspaces/vault")
WIKI_ROOT = VAULT_ROOT / "wiki"
SOURCES_ROOT = VAULT_ROOT / "sources"
INDEX_PATH = VAULT_ROOT / "index.md"
LOG_PATH = VAULT_ROOT / "log.md"
DEFAULT_STALE_DAYS = 90

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TOKEN_RE = re.compile(r"\w+")
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _strip_code(text: str) -> str:
    text = _CODE_BLOCK_RE.sub("", text)
    return _CODE_SPAN_RE.sub("", text)


def _ensure_vault() -> None:
    if not VAULT_ROOT.exists():
        output_error(f"vault not found: {VAULT_ROOT}")
        raise typer.Exit(2)


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _iter_pages(scope: str | None = None) -> list[Path]:
    root = WIKI_ROOT / scope if scope else WIKI_ROOT
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _slug_for(page: Path, fm: dict[str, str] | None = None) -> str:
    if fm is None:
        fm = _parse_frontmatter(page.read_text(encoding="utf-8"))
    return fm.get("slug") or page.stem


def _find_page(slug: str) -> Path | None:
    for page in _iter_pages():
        if _slug_for(page) == slug:
            return page
    return None


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(VAULT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _append_log(message: str) -> None:
    now = datetime.now(UTC)
    date = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%H:%M:%SZ")
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "# Vault Log\n"
    header = f"## [{date}]"
    if header in existing:
        new_text = existing.rstrip() + f"\n- {timestamp} {message}\n"
    else:
        new_text = existing.rstrip() + f"\n\n{header}\n- {timestamp} {message}\n"
    LOG_PATH.write_text(new_text, encoding="utf-8")


@app.command("page")
@usage(
    surface="st.wiki.page",
    cmd="st wiki page <slug> [--format concise|detailed]",
    when="read a vault page by slug",
    precautions=(
        "concise emits frontmatter + TL;DR (~50 tokens)",
        "detailed emits full body — only when drilling",
    ),
    tier="reference",
)
def page_cmd(
    slug: Annotated[str, typer.Argument(help="Page slug")],
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="concise|detailed")
    ] = "concise",
) -> None:
    """Print a vault page by slug."""
    _ensure_vault()
    page = _find_page(slug)
    if page is None:
        output_error(f"page not found: {slug}")
        raise typer.Exit(1)
    text = page.read_text(encoding="utf-8")
    if fmt == "detailed":
        print(text, end="")
        return
    if fmt != "concise":
        output_error(f"unknown --format: {fmt}")
        raise typer.Exit(2)
    fm_match = _FRONTMATTER_RE.match(text)
    if fm_match:
        print(fm_match.group(0), end="")
        body = text[fm_match.end():]
    else:
        body = text
    summary_lines: list[str] = []
    in_summary = False
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("> [!summary]"):
            in_summary = True
            summary_lines.append(line)
            continue
        if in_summary:
            if stripped.startswith(">"):
                summary_lines.append(line)
            else:
                break
    if summary_lines:
        print("\n".join(summary_lines))


def _score(query_tokens: list[str], text: str, slug: str) -> float:
    body_tokens = _tokenize(text)
    if not body_tokens:
        return 0.0
    title_tokens = set(_tokenize(slug))
    total = 0.0
    for q in query_tokens:
        title_hit = 5 if q in title_tokens else 0
        body_hits = body_tokens.count(q)
        total += title_hit + body_hits
    return total


@app.command("query")
@usage(
    surface="st.wiki.query",
    cmd='st wiki query "..." [--scope ...] [--include-memories]',
    when="search the vault for matching pages",
    precautions=(
        "keyword + title-boost ranking; no embeddings yet",
        "scope is a wiki subpath, e.g. projects/agent-hub",
    ),
    tier="reference",
)
def query_cmd(
    query: Annotated[str, typer.Argument(help="Search terms")],
    scope: Annotated[
        str | None, typer.Option("--scope", "-s", help="Wiki sub-scope (e.g. projects/agent-hub)")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Result count")] = 10,
    include_memories: Annotated[
        bool,
        typer.Option(
            "--include-memories",
            help="Also print related memory IDs from frontmatter",
        ),
    ] = False,
) -> None:
    """Keyword search over vault pages."""
    _ensure_vault()
    tokens = _tokenize(query)
    if not tokens:
        output_error("empty query")
        raise typer.Exit(2)
    hits: list[tuple[float, Path, dict[str, str]]] = []
    for page in _iter_pages(scope):
        text = page.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        slug = _slug_for(page, fm)
        score = _score(tokens, text, slug)
        if score > 0:
            hits.append((score, page, fm))
    hits.sort(key=lambda h: (-h[0], h[1].as_posix()))
    if not hits:
        print(f"WIKI:query:NONE|query={query!r}")
        return
    print(f"WIKI:query:OK|hits={len(hits)}|shown={min(limit, len(hits))}")
    for score, page, fm in hits[:limit]:
        slug = _slug_for(page, fm)
        line = f"WIKI:hit|slug={slug}|score={score:.1f}|path={_rel(page)}"
        if include_memories and (mem := fm.get("related_memories")):
            line += f"|memories={mem}"
        print(line)


@app.command("ingest")
@usage(
    surface="st.wiki.ingest",
    cmd="st wiki ingest <path> [--scope ...]",
    when="explicitly add a source document into the vault",
    precautions=(
        "local paths only for now; URL ingest deferred — use `st web fetch --raw` then ingest the saved file",
        "copies into vault/sources/[scope]/ with timestamp prefix; appends log entry",
    ),
    tier="reference",
)
def ingest_cmd(
    target: Annotated[str, typer.Argument(help="Local file path")],
    scope: Annotated[
        str | None, typer.Option("--scope", "-s", help="Sub-scope under sources/")
    ] = None,
) -> None:
    """Ingest a source document into the vault."""
    _ensure_vault()
    if target.startswith(("http://", "https://")):
        output_error("URL ingest not yet wired; use a local path or `st web fetch --raw` first")
        raise typer.Exit(2)
    src = Path(target).expanduser().resolve()
    if not src.exists() or not src.is_file():
        output_error(f"source not found: {target}")
        raise typer.Exit(2)
    dest_dir = SOURCES_ROOT / scope if scope else SOURCES_ROOT
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{stamp}-{src.name}"
    shutil.copy2(src, dest)
    _append_log(f"ingested {src.name} -> {_rel(dest)}")
    print(f"WIKI:ingest:OK|src={src}|dest={_rel(dest)}")


def _regenerate_index(page_meta: dict[str, dict]) -> None:
    lines = [
        "# Vault Index",
        "",
        "Regenerated by `st wiki lint`. Do not edit by hand.",
        "",
    ]
    by_scope: dict[str, list[tuple[str, dict]]] = {}
    for slug, info in page_meta.items():
        path: Path = info["path"]
        try:
            rel = path.relative_to(WIKI_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) <= 1:
            scope = "root"
        elif parts[0] == "projects" and len(parts) > 2:
            scope = f"projects/{parts[1]}"
        else:
            scope = parts[0]
        by_scope.setdefault(scope, []).append((slug, info))
    for scope in sorted(by_scope):
        lines.append(f"## {scope}")
        lines.append("")
        for slug, info in sorted(by_scope[scope]):
            lines.append(f"- [[{slug}]] — `{_rel(info['path'])}`")
        lines.append("")
    INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")


@app.command("lint")
@usage(
    surface="st.wiki.lint",
    cmd="st wiki lint [--scope ...] [--stale-days N]",
    when="check vault integrity; regenerate index.md",
    precautions=(
        "flags orphans, broken wikilinks, stale last_verified, missing frontmatter",
        "rewrites index.md from current pages",
    ),
    tier="reference",
)
def lint_cmd(
    scope: Annotated[
        str | None, typer.Option("--scope", "-s", help="Limit scan to wiki sub-scope")
    ] = None,
    stale_days: Annotated[
        int, typer.Option("--stale-days", help="Pages older than this many days are stale")
    ] = DEFAULT_STALE_DAYS,
) -> None:
    """Lint the vault and regenerate index.md."""
    _ensure_vault()
    pages = _iter_pages(scope)
    all_slugs: set[str] = set()
    linked_slugs: set[str] = set()
    page_meta: dict[str, dict] = {}
    duplicate_slugs: list[tuple[str, Path]] = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        slug = _slug_for(page, fm)
        if slug in all_slugs:
            duplicate_slugs.append((slug, page))
        all_slugs.add(slug)
        scan_text = _strip_code(text)
        for link in _WIKILINK_RE.findall(scan_text):
            linked_slugs.add(link.split("|")[0].strip())
        page_meta[slug] = {"path": page, "fm": fm, "text": text}

    issues: list[str] = []
    now = datetime.now(UTC)
    for slug, info in page_meta.items():
        fm = info["fm"]
        if not fm:
            issues.append(f"WIKI:lint:no-frontmatter|slug={slug}")
            continue
        lv = fm.get("last_verified")
        if not lv:
            issues.append(f"WIKI:lint:no-last-verified|slug={slug}")
            continue
        try:
            dt = datetime.fromisoformat(lv.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age = (now - dt).days
            if age > stale_days:
                issues.append(f"WIKI:lint:stale|slug={slug}|age_days={age}")
        except ValueError:
            issues.append(f"WIKI:lint:bad-last-verified|slug={slug}|value={lv}")

    for slug, path in duplicate_slugs:
        issues.append(f"WIKI:lint:duplicate-slug|slug={slug}|path={_rel(path)}")
    for orphan in sorted(s for s in all_slugs if s not in linked_slugs):
        issues.append(f"WIKI:lint:orphan|slug={orphan}")
    for broken in sorted(linked_slugs - all_slugs):
        issues.append(f"WIKI:lint:broken-link|slug={broken}")

    _regenerate_index(page_meta)
    status = "OK" if not issues else "ISSUES"
    print(
        f"WIKI:lint:{status}|pages={len(pages)}|issues={len(issues)}|"
        f"index={_rel(INDEX_PATH)}"
    )
    for line in issues:
        print(line)


@app.command("log")
@usage(
    surface="st.wiki.log",
    cmd="st wiki log [--last N]",
    when="review recent vault activity",
    precautions=("reads vault/log.md tail",),
    tier="reference",
)
def log_cmd(
    last: Annotated[int, typer.Option("--last", "-n", help="Show last N day-entries")] = 10,
) -> None:
    """Tail the vault log."""
    _ensure_vault()
    if not LOG_PATH.exists():
        print("WIKI:log:EMPTY")
        return
    text = LOG_PATH.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^## \[", text)
    entries = ["## [" + c for c in chunks[1:]]
    if not entries:
        print("WIKI:log:EMPTY")
        return
    for entry in entries[-last:]:
        print(entry, end="")
