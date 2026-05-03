"""Tests for explorer text search primitives."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_search_text_uses_ripgrep_when_available(mocker, tmp_path: Path) -> None:
    from app.services.explorer.text_search import search_text

    project_root = tmp_path / "project"
    project_root.mkdir()

    rg_stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "backend/app/api/files.py"},
                        "lines": {"text": '    marker = "special fallback token"\n'},
                        "line_number": 8,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "summary",
                    "data": {
                        "stats": {
                            "searches": 12,
                            "matches": 1,
                        }
                    },
                }
            ),
        ]
    )

    mocker.patch(
        "app.services.explorer.text_search.get_project_root",
        return_value=str(project_root),
    )
    mocker.patch("app.services.explorer.text_search.shutil.which", return_value="/usr/bin/rg")
    run = mocker.patch(
        "app.services.explorer.text_search.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout=rg_stdout,
            stderr="",
        ),
    )

    result = search_text("project-1", "special fallback token", limit=5)

    assert result["count"] == 1
    assert result["files_searched"] == 12
    assert result["strategy"] == "ripgrep"
    assert result["items"][0]["path"] == "backend/app/api/files.py"
    assert result["items"][0]["line"] == 8
    assert "special fallback token" in result["items"][0]["content"]
    assert result["truncated"] is False
    run.assert_called_once()
    called_args = run.call_args.args[0]
    assert called_args[1:4] == ["-C", str(project_root), "/usr/bin/rg"]
    json_index = called_args.index("--json")
    assert called_args[json_index:json_index + 4] == [
        "--json",
        "--line-number",
        "--ignore-case",
        "--fixed-strings",
    ]


def test_search_text_falls_back_to_indexed_reads_when_ripgrep_times_out(
    mocker,
    tmp_path: Path,
) -> None:
    from app.services.explorer.text_search import search_text

    project_root = tmp_path / "project"
    project_root.mkdir()

    mocker.patch(
        "app.services.explorer.text_search.get_project_root",
        return_value=str(project_root),
    )
    mocker.patch("app.services.explorer.text_search.shutil.which", return_value="/usr/bin/rg")
    mocker.patch(
        "app.services.explorer.text_search.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["rg"], timeout=15),
    )
    mocker.patch(
        "app.services.explorer.text_search.explorer_storage.get_entries",
        return_value=[
            {"path": "backend/app/api/files.py"},
            {"path": "backend/app/api/other.py"},
        ],
    )
    mocker.patch(
        "app.services.explorer.text_search.read_file",
        side_effect=[
            {
                "is_binary": False,
                "content": 'marker = "special fallback token"\nsecond line',
                "language": "python",
                "truncated": False,
            },
            {
                "is_binary": False,
                "content": "no match here",
                "language": "python",
                "truncated": False,
            },
        ],
    )

    result = search_text("project-1", "special fallback token", limit=5)

    assert result["count"] == 1
    assert result["files_searched"] == 2
    assert result["strategy"] == "indexed_fallback"
    assert result["items"][0]["path"] == "backend/app/api/files.py"
    assert result["items"][0]["line"] == 1


def test_search_text_path_prefix_limits_ripgrep_scope(mocker, tmp_path: Path) -> None:
    from app.services.explorer.text_search import search_text

    project_root = tmp_path / "project"
    project_root.mkdir()

    rg_stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "packages/notes-ui/src/PromptActions.tsx"},
                        "lines": {"text": "transition-all\n"},
                        "line_number": 68,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "summary",
                    "data": {
                        "stats": {
                            "searches": 15,
                            "matches": 1,
                        }
                    },
                }
            ),
        ]
    )

    mocker.patch("app.services.explorer.text_search.get_project_root", return_value=str(project_root))
    mocker.patch("app.services.explorer.text_search.shutil.which", return_value="/usr/bin/rg")
    run = mocker.patch(
        "app.services.explorer.text_search.subprocess.run",
        return_value=subprocess.CompletedProcess(args=["rg"], returncode=0, stdout=rg_stdout, stderr=""),
    )
    (project_root / "packages/notes-ui").mkdir(parents=True)

    result = search_text("project-1", "transition-all", limit=5, path_prefix="packages/notes-ui")

    assert result["count"] == 1
    assert result["files_searched"] == 15
    assert result["path_prefix"] == "packages/notes-ui"
    called_args = run.call_args.args[0]
    assert called_args[-1] == "packages/notes-ui"


def test_search_text_path_prefix_filters_indexed_fallback(mocker, tmp_path: Path) -> None:
    from app.services.explorer.text_search import search_text

    project_root = tmp_path / "project"
    project_root.mkdir()

    mocker.patch("app.services.explorer.text_search.get_project_root", return_value=str(project_root))
    mocker.patch("app.services.explorer.text_search.shutil.which", return_value=None)
    mocker.patch(
        "app.services.explorer.text_search.explorer_storage.get_entries",
        return_value=[
            {"path": "packages/notes-ui/src/PromptActions.tsx"},
            {"path": "frontend/app/globals.css"},
        ],
    )
    read_file = mocker.patch(
        "app.services.explorer.text_search.read_file",
        return_value={
            "is_binary": False,
            "content": "transition-all\nsecond line",
            "language": "tsx",
            "truncated": False,
        },
    )

    result = search_text("project-1", "transition-all", limit=5, path_prefix="packages/notes-ui")

    assert result["count"] == 1
    assert result["files_searched"] == 1
    assert result["items"][0]["path"] == "packages/notes-ui/src/PromptActions.tsx"
    assert result["path_prefix"] == "packages/notes-ui"
    read_file.assert_called_once_with(str(project_root), "packages/notes-ui/src/PromptActions.tsx")
