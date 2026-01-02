#!/usr/bin/env python3
"""Migrate learned-patterns.md files from markdown to JSON-lines format.

This script:
1. Parses existing learned-patterns.md files (markdown format)
2. Creates a backup of the original
3. Writes patterns in compact JSON-lines format

Usage:
    python migrate_patterns_to_jsonl.py --dry-run     # Preview without changes
    python migrate_patterns_to_jsonl.py               # Execute migration
    python migrate_patterns_to_jsonl.py --file PATH   # Migrate specific file

Note: This is optional - the system supports both formats via auto-detection.
The primary token savings come from progressive disclosure in context injection,
not from file format changes.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add backend to path for imports - must be before app imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.services.memory.pattern_service import PatternService  # noqa: E402

# Default pattern file locations
DEFAULT_PATTERN_FILES = [
    Path.home() / ".claude" / "rules" / "learned-patterns.md",
    Path.home() / "summitflow" / ".claude" / "rules" / "learned-patterns.md",
]


def count_tokens_estimate(text: str) -> int:
    """Rough token count estimate (chars / 4)."""
    return len(text) // 4


def migrate_file(file_path: Path, dry_run: bool = True) -> dict:
    """Migrate a single pattern file from markdown to JSON-lines.

    Args:
        file_path: Path to the learned-patterns.md file
        dry_run: If True, only preview changes

    Returns:
        Dict with migration results
    """
    if not file_path.exists():
        return {"file": str(file_path), "skipped": True, "reason": "File not found"}

    # Read and parse existing content
    content = file_path.read_text()
    original_tokens = count_tokens_estimate(content)

    # Parse patterns (auto-detects format)
    patterns = PatternService.parse_patterns_file(content)

    if not patterns:
        return {
            "file": str(file_path),
            "skipped": True,
            "reason": "No patterns found or already JSON-lines",
        }

    # Check if already JSON-lines format
    first_line = content.strip().split("\n")[0].strip()
    if first_line.startswith("{"):
        return {
            "file": str(file_path),
            "skipped": True,
            "reason": "Already in JSON-lines format",
        }

    # Convert to JSON-lines
    jsonl_lines = []
    for pattern in patterns:
        jsonl = PatternService.format_pattern_jsonl(pattern, include_content=True)
        jsonl_lines.append(jsonl)

    new_content = "\n".join(jsonl_lines)
    new_tokens = count_tokens_estimate(new_content)

    result = {
        "file": str(file_path),
        "patterns": len(patterns),
        "original_tokens": original_tokens,
        "new_tokens": new_tokens,
        "token_savings": original_tokens - new_tokens,
        "savings_percent": round((1 - new_tokens / original_tokens) * 100, 1)
        if original_tokens > 0
        else 0,
    }

    if dry_run:
        result["dry_run"] = True
        result["preview"] = jsonl_lines[:2]  # Show first 2 patterns
        return result

    # Create backup
    backup_path = file_path.with_suffix(f".md.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy(file_path, backup_path)
    result["backup"] = str(backup_path)

    # Write new content
    file_path.write_text(new_content)
    result["migrated"] = True

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Migrate learned-patterns.md from markdown to JSON-lines format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Migrate a specific file instead of defaults",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Pattern File Migration: Markdown → JSON-lines")
    print("=" * 60)

    # Determine files to process
    files_to_process = [args.file] if args.file else DEFAULT_PATTERN_FILES

    total_stats = {
        "files": 0,
        "migrated": 0,
        "skipped": 0,
        "patterns": 0,
        "tokens_saved": 0,
    }

    for file_path in files_to_process:
        total_stats["files"] += 1
        print(f"\nProcessing: {file_path}")

        result = migrate_file(file_path, dry_run=args.dry_run)

        if result.get("skipped"):
            total_stats["skipped"] += 1
            print(f"  [SKIP] {result['reason']}")
        elif result.get("dry_run"):
            total_stats["migrated"] += 1
            total_stats["patterns"] += result["patterns"]
            total_stats["tokens_saved"] += result["token_savings"]
            print(f"  [DRY] {result['patterns']} patterns")
            print(f"        Tokens: {result['original_tokens']} → {result['new_tokens']}")
            print(f"        Savings: {result['token_savings']} ({result['savings_percent']}%)")
            if result.get("preview"):
                print(f"        Preview: {result['preview'][0][:80]}...")
        elif result.get("migrated"):
            total_stats["migrated"] += 1
            total_stats["patterns"] += result["patterns"]
            total_stats["tokens_saved"] += result["token_savings"]
            print(f"  [OK] {result['patterns']} patterns migrated")
            print(f"       Tokens: {result['original_tokens']} → {result['new_tokens']}")
            print(f"       Savings: {result['token_savings']} ({result['savings_percent']}%)")
            print(f"       Backup: {result['backup']}")

    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary:")
    print("=" * 60)
    print(f"  Files processed: {total_stats['files']}")
    print(f"  Files migrated:  {total_stats['migrated']}")
    print(f"  Files skipped:   {total_stats['skipped']}")
    print(f"  Total patterns:  {total_stats['patterns']}")
    print(f"  Tokens saved:    {total_stats['tokens_saved']}")

    if args.dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to execute.")


if __name__ == "__main__":
    main()
