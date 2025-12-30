"""TDD suggestions service - Auto-suggest components and capabilities.

Analyzes explorer data to suggest:
- Components: Groups of related files (by directory) and endpoints (by prefix)
- Capabilities: What each component should do (derived from endpoints/pages)
- Existing tests: Test files that match suggested capabilities
- Coverage summary: How much of the codebase is covered

This service enables the /seed_tdd skill to bootstrap TDD structure.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..storage import explorer as explorer_storage


def suggest_components(project_id: str) -> list[dict[str, Any]]:
    """Suggest components by grouping files by directory and endpoints by prefix.

    Args:
        project_id: Project ID for scoping

    Returns:
        List of suggested components with entries
    """
    # Get all file entries
    files = explorer_storage.get_entries(project_id, {"type": "file", "limit": 10000})

    # Get all endpoint entries
    endpoints = explorer_storage.get_entries(project_id, {"type": "endpoint", "limit": 10000})

    # Get all page entries
    pages = explorer_storage.get_entries(project_id, {"type": "page", "limit": 10000})

    components: list[dict[str, Any]] = []

    # Group files by directory (first 2 levels)
    dir_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        path = f.get("path", "")
        parts = path.split("/")
        if len(parts) >= 2:
            key = "/".join(parts[:2])
        elif len(parts) == 1:
            key = parts[0]
        else:
            key = "root"
        dir_groups[key].append(f)

    for dir_path, entries in dir_groups.items():
        # Skip small groups (likely not meaningful components)
        if len(entries) < 3:
            continue
        # Skip common non-component directories
        skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build"}
        if any(skip in dir_path for skip in skip_dirs):
            continue

        component_name = _path_to_component_name(dir_path)
        components.append(
            {
                "suggested_name": component_name,
                "type": "directory",
                "path": dir_path,
                "entry_count": len(entries),
                "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
            }
        )

    # Group endpoints by path prefix
    endpoint_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in endpoints:
        path = ep.get("path", "")
        # Extract route prefix (e.g., /api/users/... -> users)
        prefix = _extract_endpoint_prefix(path)
        if prefix:
            endpoint_groups[prefix].append(ep)

    for prefix, entries in endpoint_groups.items():
        if len(entries) < 2:
            continue

        component_name = f"{prefix.replace('/', '-').title()}API"
        components.append(
            {
                "suggested_name": component_name,
                "type": "endpoint_group",
                "path": prefix,
                "entry_count": len(entries),
                "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
            }
        )

    # Group pages by route prefix
    page_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pg in pages:
        path = pg.get("path", "")
        parts = path.strip("/").split("/")
        if len(parts) >= 1 and parts[0]:
            prefix = parts[0]
            page_groups[prefix].append(pg)

    for prefix, entries in page_groups.items():
        if len(entries) < 2:
            continue

        component_name = f"{prefix.title()}Pages"
        components.append(
            {
                "suggested_name": component_name,
                "type": "page_group",
                "path": prefix,
                "entry_count": len(entries),
                "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
            }
        )

    return sorted(components, key=lambda c: c["entry_count"], reverse=True)


def suggest_capabilities(component_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suggest capabilities for a set of component entries.

    Args:
        component_entries: List of explorer entries in a component

    Returns:
        List of suggested capability names and descriptions
    """
    capabilities: list[dict[str, Any]] = []

    for entry in component_entries:
        path = entry.get("path", "")
        entry_type = entry.get("entry_type", "")

        if entry_type == "endpoint":
            method = entry.get("metadata", {}).get("method", "GET")
            cap_name = _endpoint_to_capability(path, method)
            if cap_name:
                capabilities.append(
                    {
                        "suggested_name": cap_name,
                        "source": "endpoint",
                        "source_path": path,
                        "description": f"{method} {path} should work correctly",
                    }
                )

        elif entry_type == "page":
            cap_name = _page_to_capability(path)
            if cap_name:
                capabilities.append(
                    {
                        "suggested_name": cap_name,
                        "source": "page",
                        "source_path": path,
                        "description": f"Page at {path} should render correctly",
                    }
                )

    return capabilities


def find_existing_tests(project_id: str) -> list[dict[str, Any]]:
    """Find test files and match them to potential capabilities.

    Args:
        project_id: Project ID for scoping

    Returns:
        List of test files with suggested capability matches
    """
    # Get all files and filter for test patterns
    all_files = explorer_storage.get_entries(project_id, {"type": "file", "limit": 10000})

    test_files: list[dict[str, Any]] = []
    test_patterns = ["test_", "_test.", ".test.", ".spec."]

    for f in all_files:
        path = f.get("path", "")
        name = f.get("name", "")

        is_test = any(p in path.lower() or p in name.lower() for p in test_patterns)
        if is_test:
            # Extract what this test might be testing
            tested_subject = _extract_test_subject(path, name)
            test_files.append(
                {
                    "path": path,
                    "name": name,
                    "tested_subject": tested_subject,
                    "entry_id": f.get("id"),
                }
            )

    return test_files


def get_coverage_summary(project_id: str) -> dict[str, Any]:
    """Calculate coverage stats for endpoints and pages.

    Args:
        project_id: Project ID for scoping

    Returns:
        Coverage statistics
    """
    # Get coverage gaps (uncovered entities)
    gaps = explorer_storage.get_coverage_gaps(project_id)

    # Get totals
    endpoints = explorer_storage.get_entries(project_id, {"type": "endpoint", "limit": 10000})
    pages = explorer_storage.get_entries(project_id, {"type": "page", "limit": 10000})

    total_endpoints = len(endpoints)
    total_pages = len(pages)
    uncovered_endpoints = gaps["summary"]["endpoint_count"]
    uncovered_pages = gaps["summary"]["page_count"]

    return {
        "endpoints": {
            "total": total_endpoints,
            "covered": total_endpoints - uncovered_endpoints,
            "uncovered": uncovered_endpoints,
            "coverage_pct": round(
                ((total_endpoints - uncovered_endpoints) / total_endpoints * 100)
                if total_endpoints > 0
                else 0,
                1,
            ),
        },
        "pages": {
            "total": total_pages,
            "covered": total_pages - uncovered_pages,
            "uncovered": uncovered_pages,
            "coverage_pct": round(
                ((total_pages - uncovered_pages) / total_pages * 100) if total_pages > 0 else 0,
                1,
            ),
        },
    }


def get_tdd_suggestions(project_id: str) -> dict[str, Any]:
    """Get complete TDD suggestions for a project.

    Combines component suggestions, test discovery, and coverage stats.

    Args:
        project_id: Project ID for scoping

    Returns:
        Complete TDD suggestion response
    """
    suggested_components = suggest_components(project_id)
    existing_tests = find_existing_tests(project_id)
    coverage_summary = get_coverage_summary(project_id)

    return {
        "suggested_components": suggested_components,
        "existing_tests": existing_tests,
        "coverage_summary": coverage_summary,
        "recommendation": _generate_recommendation(
            suggested_components, existing_tests, coverage_summary
        ),
    }


def get_component_suggestions_by_source(project_id: str, source_type: str) -> list[dict[str, Any]]:
    """Get component suggestions filtered by source type.

    Args:
        project_id: Project ID for scoping
        source_type: One of 'pages', 'endpoints', 'directories', 'manual'

    Returns:
        List of suggested components matching the source type
    """
    if source_type == "manual":
        return []

    all_suggestions = suggest_components(project_id)

    # Map source_type to suggestion types
    type_map = {
        "pages": "page_group",
        "endpoints": "endpoint_group",
        "directories": "directory",
    }

    target_type = type_map.get(source_type)
    if not target_type:
        return []

    return [s for s in all_suggestions if s.get("type") == target_type]


# --- Helper functions ---


def _path_to_component_name(path: str) -> str:
    """Convert a directory path to a component name."""
    parts = path.strip("/").split("/")
    # Take last 1-2 meaningful parts
    meaningful = [p for p in parts if p and p not in {"app", "src", "lib"}]
    if meaningful:
        return "".join(p.title().replace("_", "").replace("-", "") for p in meaningful[-2:])
    return "".join(p.title().replace("_", "").replace("-", "") for p in parts[-2:])


def _extract_endpoint_prefix(path: str) -> str:
    """Extract the prefix from an endpoint path."""
    # Remove HTTP method if present
    parts = path.split()
    if len(parts) > 1:
        path = parts[-1]

    # Split by /
    path_parts = path.strip("/").split("/")

    # Skip common prefixes
    skip = {"api", "v1", "v2", "projects", "{project_id}"}
    meaningful = [p for p in path_parts if p and p not in skip and not p.startswith("{")]

    if meaningful:
        return meaningful[0]
    return ""


def _endpoint_to_capability(path: str, method: str) -> str:
    """Convert an endpoint to a capability name."""
    prefix = _extract_endpoint_prefix(path)
    if not prefix:
        return ""

    action_map = {
        "GET": "view",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }
    action = action_map.get(method, "handle")
    return f"{action}_{prefix}"


def _page_to_capability(path: str) -> str:
    """Convert a page path to a capability name."""
    parts = path.strip("/").split("/")
    meaningful = [p for p in parts if p and not p.startswith("[")]

    if meaningful:
        return f"view_{meaningful[-1]}"
    return ""


def _extract_test_subject(path: str, name: str) -> str:
    """Extract what a test file is testing."""
    # Remove test prefixes/suffixes
    subject = name
    for pattern in ["test_", "_test", ".test", ".spec"]:
        subject = subject.replace(pattern, "")
    subject = subject.replace(".py", "").replace(".ts", "").replace(".js", "")
    return subject


def _generate_recommendation(
    components: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> str:
    """Generate a natural language recommendation."""
    parts = []

    if components:
        parts.append(f"Found {len(components)} potential components to organize.")

    if tests:
        parts.append(f"Discovered {len(tests)} existing test files.")

    endpoint_cov = coverage.get("endpoints", {}).get("coverage_pct", 0)
    page_cov = coverage.get("pages", {}).get("coverage_pct", 0)

    if endpoint_cov < 50:
        parts.append(
            f"Endpoint coverage is low ({endpoint_cov}%). Consider adding capability links."
        )
    if page_cov < 50:
        parts.append(f"Page coverage is low ({page_cov}%). Consider adding capability links.")

    if not parts:
        parts.append("Codebase looks well organized. Run a scan to update metrics.")

    return " ".join(parts)
