#!/usr/bin/env python3
"""
Project Scanner for /refactor_it workflow.

Scans project files, calculates complexity metrics, and identifies refactor targets.
The refactor_targets list prioritizes files that need modularization (high complexity,
too many lines, too many functions).

Modes:
  --init     Create baseline project_index.json with metrics and refactor targets
  --refresh  Update current metrics and recalculate refactor targets
  --report   Generate before/after improvement report
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class FileMetrics:
    """Metrics for a single file."""

    lines: int = 0
    functions: int = 0
    classes: int = 0
    imports: int = 0
    complexity_score: int = 0


@dataclass
class FileEntry:
    """Entry for a file in the project index."""

    baseline: FileMetrics = field(default_factory=FileMetrics)
    current: FileMetrics = field(default_factory=FileMetrics)


def count_python_metrics(filepath: Path) -> FileMetrics:
    """Count metrics for a Python file."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # Count functions (def)
        functions = len(re.findall(r"^\s*(?:async\s+)?def\s+\w+", content, re.MULTILINE))

        # Count classes
        classes = len(re.findall(r"^\s*class\s+\w+", content, re.MULTILINE))

        # Count imports
        imports = len(re.findall(r"^\s*(?:from|import)\s+", content, re.MULTILINE))

        # Calculate complexity score
        complexity = calculate_complexity(len(lines), functions, classes, imports)

        return FileMetrics(
            lines=len(lines),
            functions=functions,
            classes=classes,
            imports=imports,
            complexity_score=complexity,
        )
    except Exception:
        return FileMetrics()


def count_typescript_metrics(filepath: Path) -> FileMetrics:
    """Count metrics for a TypeScript/JavaScript file."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # Count functions (function keyword, arrow functions in declarations)
        func_patterns = [
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+\w+",
            r"^\s*(?:export\s+)?const\s+\w+\s*=\s*(?:async\s+)?\(",
            r"^\s*(?:async\s+)?\w+\s*\([^)]*\)\s*[:{]",
        ]
        functions = sum(
            len(re.findall(p, content, re.MULTILINE)) for p in func_patterns
        )

        # Count classes/components
        classes = len(re.findall(r"^\s*(?:export\s+)?class\s+\w+", content, re.MULTILINE))
        classes += len(
            re.findall(
                r"^\s*(?:export\s+)?(?:const|function)\s+[A-Z]\w*",
                content,
                re.MULTILINE,
            )
        )

        # Count imports
        imports = len(re.findall(r"^\s*import\s+", content, re.MULTILINE))

        complexity = calculate_complexity(len(lines), functions, classes, imports)

        return FileMetrics(
            lines=len(lines),
            functions=functions,
            classes=classes,
            imports=imports,
            complexity_score=complexity,
        )
    except Exception:
        return FileMetrics()


def calculate_complexity(
    lines: int, functions: int, classes: int, imports: int
) -> int:
    """Calculate heuristic complexity score."""
    score = 0

    if lines > 200:
        score += 2
    if functions > 15:
        score += 2
    if classes > 3:
        score += 1
    if imports > 20:
        score += 1

    # Base complexity from size
    score += min(lines // 100, 5)

    return score


def determine_complexity_tier(total_score: int, file_count: int) -> str:
    """Determine project complexity tier."""
    if file_count <= 2 and total_score < 5:
        return "SIMPLE"
    elif file_count <= 10 and total_score <= 15:
        return "STANDARD"
    else:
        return "COMPLEX"


def scan_project(root: Path) -> dict[str, FileEntry]:
    """Scan project and collect file metrics."""
    files: dict[str, FileEntry] = {}

    # Python files
    for py_file in root.rglob("*.py"):
        # Skip common non-source directories
        if any(
            part in py_file.parts
            for part in [
                ".venv",
                "venv",
                "__pycache__",
                ".git",
                "node_modules",
                ".mypy_cache",
            ]
        ):
            continue

        rel_path = str(py_file.relative_to(root))
        metrics = count_python_metrics(py_file)
        files[rel_path] = FileEntry(baseline=metrics, current=metrics)

    # TypeScript/JavaScript files
    for ext in ["*.ts", "*.tsx", "*.js", "*.jsx"]:
        for ts_file in root.rglob(ext):
            if any(
                part in ts_file.parts
                for part in [
                    "node_modules",
                    ".next",
                    "dist",
                    ".git",
                    "build",
                    ".venv",
                    "venv",
                ]
            ):
                continue

            rel_path = str(ts_file.relative_to(root))
            metrics = count_typescript_metrics(ts_file)
            files[rel_path] = FileEntry(baseline=metrics, current=metrics)

    return files


def get_refactor_targets(files: dict[str, FileEntry]) -> list[dict[str, Any]]:
    """Identify files that need refactoring based on metrics."""
    targets = []

    for path, entry in files.items():
        metrics = entry.current
        reasons = []

        if metrics.complexity_score > 10:
            reasons.append(f"complexity > 10 ({metrics.complexity_score})")
        if metrics.lines > 300:
            reasons.append(f"lines > 300 ({metrics.lines})")
        if metrics.functions > 20:
            reasons.append(f"functions > 20 ({metrics.functions})")

        if reasons:
            priority = (
                "high" if metrics.complexity_score > 15 or metrics.lines > 500 else "medium"
            )
            # Calculate priority score for sorting (higher = more urgent)
            priority_score = metrics.complexity_score + (metrics.lines // 50) + metrics.functions
            targets.append({
                "file": path,
                "reason": ", ".join(reasons),
                "priority": priority,
                "priority_score": priority_score,
                "metrics": {
                    "lines": metrics.lines,
                    "functions": metrics.functions,
                    "classes": metrics.classes,
                    "complexity": metrics.complexity_score,
                },
            })

    return sorted(targets, key=lambda x: (-x["priority_score"], x["priority"] != "high"))


def init_project_index(output_path: Path, project_root: Path) -> None:
    """Create baseline project_index.json."""
    print(f"Scanning project at {project_root}...")

    files = scan_project(project_root)

    # Calculate total complexity
    total_complexity = sum(e.baseline.complexity_score for e in files.values())
    tier = determine_complexity_tier(total_complexity, len(files))

    # Get refactor targets
    targets = get_refactor_targets(files)

    # Convert to serializable format
    files_dict = {}
    for path, entry in files.items():
        files_dict[path] = {
            "baseline": asdict(entry.baseline),
            "current": asdict(entry.current),
        }

    index = {
        "meta": {
            "baseline_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "project_root": str(project_root),
        },
        "complexity_tier": tier,
        "files": files_dict,
        "refactor_targets": targets,
        "summary": {
            "type_errors_fixed": 0,
            "lint_errors_fixed": 0,
            "dead_code_removed": 0,
            "duplicates_consolidated": 0,
            "lines_removed": 0,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2))

    print(f"Created project index at {output_path}")
    print(f"  Files scanned: {len(files)}")
    print(f"  Complexity tier: {tier}")
    print(f"  Refactor targets: {len(targets)}")


def refresh_metrics(index_path: Path) -> None:
    """Refresh current metrics."""
    if not index_path.exists():
        print(f"Error: Project index not found at {index_path}", file=sys.stderr)
        sys.exit(1)

    index = json.loads(index_path.read_text())
    project_root = Path(index["meta"]["project_root"])

    # Re-scan current state
    current_files = scan_project(project_root)

    # Update current metrics
    for path, entry in current_files.items():
        if path in index["files"]:
            index["files"][path]["current"] = asdict(entry.current)
        else:
            index["files"][path] = {
                "baseline": asdict(entry.baseline),
                "current": asdict(entry.current),
            }

    # Update refactor targets based on current state
    index["refactor_targets"] = get_refactor_targets(current_files)

    index["meta"]["last_updated"] = datetime.now().isoformat()
    index_path.write_text(json.dumps(index, indent=2))
    print(f"Refreshed metrics for {len(current_files)} files")
    print(f"Refactor targets: {len(index['refactor_targets'])}")


def generate_report(index_path: Path) -> None:
    """Generate improvement report comparing baseline to current."""
    if not index_path.exists():
        print(f"Error: Project index not found at {index_path}", file=sys.stderr)
        sys.exit(1)

    index = json.loads(index_path.read_text())

    # Refresh current metrics first
    project_root = Path(index["meta"]["project_root"])
    current_files = scan_project(project_root)

    for path, entry in current_files.items():
        if path in index["files"]:
            index["files"][path]["current"] = asdict(entry.current)

    # Calculate totals
    baseline_lines = sum(
        f["baseline"]["lines"] for f in index["files"].values() if f["baseline"]
    )
    current_lines = sum(
        f["current"]["lines"] for f in index["files"].values() if f["current"]
    )

    baseline_complexity = sum(
        f["baseline"]["complexity_score"] for f in index["files"].values() if f["baseline"]
    )
    current_complexity = sum(
        f["current"]["complexity_score"] for f in index["files"].values() if f["current"]
    )

    # Find top improvements
    improvements = []
    for path, entry in index["files"].items():
        baseline = entry["baseline"]
        current = entry["current"]

        if not baseline or not current:
            continue

        line_diff = baseline["lines"] - current["lines"]
        complexity_diff = baseline["complexity_score"] - current["complexity_score"]

        if line_diff > 0 or complexity_diff > 0:
            improvements.append(
                {
                    "file": path,
                    "lines_before": baseline["lines"],
                    "lines_after": current["lines"],
                    "complexity_before": baseline["complexity_score"],
                    "complexity_after": current["complexity_score"],
                }
            )

    improvements.sort(
        key=lambda x: (x["lines_before"] - x["lines_after"]), reverse=True
    )

    # Calculate duration
    baseline_time = datetime.fromisoformat(index["meta"]["baseline_at"])
    current_time = datetime.fromisoformat(index["meta"]["last_updated"])
    duration = current_time - baseline_time

    # Print report
    print("=" * 60)
    print("IMPROVEMENT REPORT")
    print("=" * 60)
    print(f"Project: {project_root}")
    print(f"Duration: {duration}")
    print()

    print("METRICS BEFORE -> AFTER")
    print("-" * 40)

    line_change = baseline_lines - current_lines
    line_pct = (line_change / baseline_lines * 100) if baseline_lines else 0
    print(f"Lines of code:     {baseline_lines:,} -> {current_lines:,} ({line_change:+,}, {line_pct:+.1f}%)")

    complexity_change = baseline_complexity - current_complexity
    complexity_pct = (complexity_change / baseline_complexity * 100) if baseline_complexity else 0
    print(f"Total complexity:  {baseline_complexity} -> {current_complexity} ({complexity_change:+}, {complexity_pct:+.1f}%)")

    summary = index.get("summary", {})
    if summary.get("type_errors_fixed"):
        print(f"Type errors fixed: {summary['type_errors_fixed']}")
    if summary.get("lint_errors_fixed"):
        print(f"Lint errors fixed: {summary['lint_errors_fixed']}")
    if summary.get("dead_code_removed"):
        print(f"Dead code removed: {summary['dead_code_removed']}")
    if summary.get("duplicates_consolidated"):
        print(f"Duplicates consolidated: {summary['duplicates_consolidated']}")
    print()

    if improvements[:10]:
        print("TOP IMPROVEMENTS")
        print("-" * 40)
        for i, imp in enumerate(improvements[:10], 1):
            print(f"{i}. {imp['file']}")
            print(f"   Lines: {imp['lines_before']} -> {imp['lines_after']} ({imp['lines_before'] - imp['lines_after']:+})")
            print(f"   Complexity: {imp['complexity_before']} -> {imp['complexity_after']}")
            print()

    # Show remaining refactor targets
    remaining_targets = get_refactor_targets(current_files)
    if remaining_targets:
        print("REMAINING REFACTOR TARGETS")
        print("-" * 40)
        for i, target in enumerate(remaining_targets[:10], 1):
            priority_icon = "🔴" if target["priority"] == "high" else "🟡"
            print(f"{priority_icon} {target['file']}")
            print(f"   Reason: {target['reason']}")
        if len(remaining_targets) > 10:
            print(f"   ... and {len(remaining_targets) - 10} more")
        print()
    else:
        print("✅ No remaining refactor targets!")
        print()

    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Scanner for /refactor_it workflow"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create baseline project_index.json with file metrics and refactor targets",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate improvement report comparing baseline to current state",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Update current metrics and refactor targets",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("project_index.json"),
        help="Output path for project index (default: project_index.json)",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        help="Input path for project index (for --report/--refresh)",
    )
    parser.add_argument(
        "--root",
        "-r",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )

    args = parser.parse_args()

    if args.init:
        init_project_index(args.output, args.root.resolve())
    elif args.report:
        index_path = args.input or args.output
        generate_report(index_path)
    elif args.refresh:
        index_path = args.input or args.output
        refresh_metrics(index_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
