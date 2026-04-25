"""File browser API for project and workspace scopes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services import file_browser
from .dependencies import ValidProject

project_router = APIRouter()
global_router = APIRouter()
UPLOAD_FILE_FIELD = File(..., description='File to upload')


class CreateDirectoryRequest(BaseModel):
    directory: str = ''
    name: str


class CreateFileRequest(BaseModel):
    directory: str = ''
    name: str
    content: str = ''


class WriteFileRequest(BaseModel):
    path: str
    content: str


class RenamePathRequest(BaseModel):
    path: str
    name: str


def _get_global_files_root() -> Path:
    return Path('/')


def _require_project_root(project: dict[str, Any]) -> str:
    root_path = project.get('root_path')
    if not root_path:
        raise HTTPException(status_code=400, detail='Project has no root_path configured')
    return str(root_path)


def _project_scope(project: dict[str, Any], path: str) -> tuple[str | Path, str, bool]:
    """Resolve project file paths.

    Empty and relative paths stay project-relative for compatibility. Absolute
    paths opt into server-root browsing and mutation.
    """
    if path.startswith('/'):
        return _get_global_files_root(), path, True
    return _require_project_root(project), path, False


def _handle_browser_error(exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, FileExistsError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, IsADirectoryError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _list_directory(
    root_path: str | Path,
    path: str,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.list_directory(root_path, path, absolute_paths=absolute_paths)
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


async def _upload_file(
    root_path: str | Path,
    path: str,
    upload: UploadFile,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.write_uploaded_file(
            root_path,
            path,
            upload.filename,
            upload.file,
            absolute_paths=absolute_paths,
        )
    except Exception as exc:
        _handle_browser_error(exc)
        raise
    finally:
        await upload.close()


def _create_directory(
    root_path: str | Path,
    request: CreateDirectoryRequest,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.create_directory(
            root_path,
            request.directory,
            request.name,
            absolute_paths=absolute_paths,
        )
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _create_file(
    root_path: str | Path,
    request: CreateFileRequest,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.create_text_file(
            root_path,
            request.directory,
            request.name,
            request.content,
            absolute_paths=absolute_paths,
        )
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _write_file(
    root_path: str | Path,
    request: WriteFileRequest,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.write_text_file(
            root_path,
            request.path,
            request.content,
            absolute_paths=absolute_paths,
        )
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _delete_path(root_path: str | Path, path: str) -> dict[str, object]:
    try:
        return file_browser.delete_path(root_path, path)
    except Exception as exc:
        _handle_browser_error(exc)
        raise


def _rename_path(
    root_path: str | Path,
    request: RenamePathRequest,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    try:
        return file_browser.rename_path(
            root_path,
            request.path,
            request.name,
            absolute_paths=absolute_paths,
        )
    except Exception as exc:
        _handle_browser_error(exc)
        raise


@project_router.get('/{project_id}/files/tree')
def get_project_file_tree(
    project: ValidProject,
    path: str = Query('', description='Relative directory path (empty = root)'),
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, path)
    return _list_directory(root_path, target_path, absolute_paths=absolute_paths)


@project_router.get('/{project_id}/files/content')
def get_project_file_content(
    project: ValidProject,
    path: str = Query(..., description='Relative file path'),
) -> dict[str, object]:
    root_path, target_path, _ = _project_scope(project, path)
    return _read_file(root_path, target_path)


@project_router.get('/{project_id}/files/download')
def download_project_file(
    project: ValidProject,
    path: str = Query(..., description='Relative file path'),
) -> FileResponse:
    root_path, target_path, _ = _project_scope(project, path)
    return _download_file(root_path, target_path)


@project_router.post('/{project_id}/files/upload')
async def upload_project_file(
    project: ValidProject,
    upload: UploadFile = UPLOAD_FILE_FIELD,
    path: str = Query('', description='Relative target directory path'),
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, path)
    return await _upload_file(root_path, target_path, upload, absolute_paths=absolute_paths)


@project_router.post('/{project_id}/files/directory')
def create_project_directory(
    project: ValidProject,
    request: CreateDirectoryRequest,
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, request.directory)
    return _create_directory(
        root_path,
        CreateDirectoryRequest(directory=target_path, name=request.name),
        absolute_paths=absolute_paths,
    )


@project_router.post('/{project_id}/files/file')
def create_project_file(
    project: ValidProject,
    request: CreateFileRequest,
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, request.directory)
    return _create_file(
        root_path,
        CreateFileRequest(directory=target_path, name=request.name, content=request.content),
        absolute_paths=absolute_paths,
    )


@project_router.put('/{project_id}/files/file')
def write_project_file(
    project: ValidProject,
    request: WriteFileRequest,
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, request.path)
    return _write_file(
        root_path,
        WriteFileRequest(path=target_path, content=request.content),
        absolute_paths=absolute_paths,
    )


@project_router.delete('/{project_id}/files/path')
def delete_project_path(
    project: ValidProject,
    path: str = Query(..., description='Relative or absolute path to delete'),
) -> dict[str, object]:
    root_path, target_path, _ = _project_scope(project, path)
    return _delete_path(root_path, target_path)


@project_router.patch('/{project_id}/files/path/rename')
def rename_project_path(
    project: ValidProject,
    request: RenamePathRequest,
) -> dict[str, object]:
    root_path, target_path, absolute_paths = _project_scope(project, request.path)
    return _rename_path(
        root_path,
        RenamePathRequest(path=target_path, name=request.name),
        absolute_paths=absolute_paths,
    )


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


@global_router.post('/files/directory')
def create_workspace_directory(request: CreateDirectoryRequest) -> dict[str, object]:
    return _create_directory(_get_global_files_root(), request)


@global_router.post('/files/file')
def create_workspace_file(request: CreateFileRequest) -> dict[str, object]:
    return _create_file(_get_global_files_root(), request)


@global_router.put('/files/file')
def write_workspace_file(request: WriteFileRequest) -> dict[str, object]:
    return _write_file(_get_global_files_root(), request)


@global_router.delete('/files/path')
def delete_workspace_path(
    path: str = Query(..., description='Relative path to delete'),
) -> dict[str, object]:
    return _delete_path(_get_global_files_root(), path)


@global_router.patch('/files/path/rename')
def rename_workspace_path(request: RenamePathRequest) -> dict[str, object]:
    return _rename_path(_get_global_files_root(), request)
