"""Owner-selected portable Codex inputs; Veeam owns full-profile recovery."""

from __future__ import annotations

from pathlib import PurePosixPath

CODEX_CAPTURE_PROFILE = "codex-restore-essentials-v1"
CODEX_ESSENTIAL_FILES = frozenset({
    "config.toml", "AGENTS.md", "README.md", "hooks.json",
    ".backupignore", ".gitignore", "aftertimes-clean.config.toml",
    "package.json", "package-lock.json", "tsconfig.json",
})
CODEX_ESSENTIAL_DIRECTORIES = frozenset({
    "agents", "hooks", "skills", "skills-disabled", "session-integrations",
    # These are originals, not replaceable model/tool caches. Keep them even
    # though conversation continuity itself is outside this recovery profile.
    "generated_images", "attachments", "pets", "visualizations",
})


def is_codex_recovery_input(relative: str) -> bool:
    """Positive selection prevents future native runtime names entering capture.

    Existing ignore rules and sensitive-path/symlink checks remain authoritative
    inside selected roots. No history, provider auth, native DB, downloaded
    package, generated proxy certificate, or unknown root is selected.
    """
    path = PurePosixPath(relative.removeprefix("./"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        return False
    if len(path.parts) == 1 and path.name in CODEX_ESSENTIAL_FILES:
        return True
    if path.parts[0] not in CODEX_ESSENTIAL_DIRECTORIES:
        return False
    if path.parts[:2] == ("skills", ".system"):
        return False
    # Rotated diagnostics must not bypass the usual *.log ignore rule.
    return not any(part.endswith(".log") or ".log." in part for part in path.parts)
