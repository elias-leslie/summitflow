"""File browser API for project and workspace scopes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..services import file_browser
from .dependencies import ValidProject

project_router = APIRouter()
global_router = APIRouter()
UPLOAD_FILE_FIELD = File(..., description='File to upload')


def _get_global_files_root() -> Path:
    return Path('/')


def _require_project_root(project: dict[str, Any]) -> str:
    root_path = project.get('root_path')
    if not root_path:
        raise HTTPException(status_code=400, detail='Project has no root_path configured')
    return str(root_path)


def _handle_browser_error(exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, FileExistsError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _list_directory(root_path: str | Path, path: str) -> dict[str, object]:
    try:
        return file_browser.list_directory(root_path, path)
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _read_file(root_path: str | Path, path: str) -> dict[str, object]:
    try:
        return file_browser.read_file(root_path, path)
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _download_file(root_path: str | Path, path: str) -> FileResponse:
    try:
        target = file_browser.get_download_target(root_path, path)
    except Exception as exc:
        _handle_browser_error(exc)
        raise
    return FileResponse(path=target, filename=target.name, media_type='application/octet-stream')


async def _upload_file(root_path: str | Path, path: str, upload: UploadFile) -> dict[str, object]:
    try:
        return file_browser.write_uploaded_file(root_path, path, upload.filename, upload.file)
    except Exception as exc:
        _handle_browser_error(exc)
        raise
    finally:
        await upload.close()


@project_router.get('/{project_id}/files/tree')
def get_project_file_tree(
    project: ValidProject,
    path: str = Query('', description='Relative directory path (empty = root)'),
) -> dict[str, object]:
    return _list_directory(_require_project_root(project), path)


@project_router.get('/{project_id}/files/content')
def get_project_file_content(
    project: ValidProject,
    path: str = Query(..., description='Relative file path'),
) -> dict[str, object]:
    return _read_file(_require_project_root(project), path)


@project_router.get('/{project_id}/files/download')
def download_project_file(
    project: ValidProject,
    path: str = Query(..., description='Relative file path'),
) -> FileResponse:
    return _download_file(_require_project_root(project), path)


@project_router.post('/{project_id}/files/upload')
async def upload_project_file(
    project: ValidProject,
    upload: UploadFile = UPLOAD_FILE_FIELD,
    path: str = Query('', description='Relative target directory path'),
) -> dict[str, object]:
    return await _upload_file(_require_project_root(project), path, upload)


@global_router.get('/files/tree')
def get_workspace_file_tree(
    path: str = Query('', description='Relative directory path (empty = root)'),
) -> dict[str, object]:
    return _list_directory(_get_global_files_root(), path)


@global_router.get('/files/content')
def get_workspace_file_content(
    path: str = Query(..., description='Relative file path'),
) -> dict[str, object]:
    return _read_file(_get_global_files_root(), path)


@global_router.get('/files/download')
def download_workspace_file(
    path: str = Query(..., description='Relative file path'),
) -> FileResponse:
    return _download_file(_get_global_files_root(), path)


@global_router.post('/files/upload')
async def upload_workspace_file(
    upload: UploadFile = UPLOAD_FILE_FIELD,
    path: str = Query('', description='Relative target directory path'),
) -> dict[str, object]:
    return await _upload_file(_get_global_files_root(), path, upload)
