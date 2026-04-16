/**
 * File browser API client.
 */

import { getApiBaseUrl } from '../api-config'
import { buildQueryString, fetchWithErrorHandling, throwFromResponse } from './utils'

export type FileBrowserScope =
  | { kind: 'project'; projectId: string }
  | { kind: 'workspace' }

export interface FileTreeEntry {
  name: string
  path: string
  is_directory: boolean
  size?: number
  extension?: string | null
  children_count?: number
}

export interface FileTreeResponse {
  entries: FileTreeEntry[]
  path: string
  total: number
}

export interface FileContentResponse {
  path: string
  name: string
  content: string | null
  size: number
  lines: number
  extension: string | null
  is_binary: boolean
  language: string | null
  truncated: boolean
}

export interface FileUploadResponse {
  path: string
  directory: string
  name: string
  size: number
}

function getFilesApiBase(scope: FileBrowserScope): string {
  const apiBase = getApiBaseUrl()
  if (scope.kind === 'project') {
    return `${apiBase}/api/projects/${scope.projectId}/files`
  }
  return `${apiBase}/api/files`
}

export function getFileScopeKey(scope: FileBrowserScope): string {
  return scope.kind === 'project' ? `project:${scope.projectId}` : 'workspace'
}

export function fetchFileTree(
  scope: FileBrowserScope,
  path: string = '',
): Promise<FileTreeResponse> {
  const qs = buildQueryString({ path: path || undefined })
  return fetchWithErrorHandling<FileTreeResponse>(
    `${getFilesApiBase(scope)}/tree${qs}`,
    { errorMessage: 'Failed to load file tree' },
  )
}

export function fetchFileContent(
  scope: FileBrowserScope,
  path: string,
): Promise<FileContentResponse> {
  const qs = buildQueryString({ path })
  return fetchWithErrorHandling<FileContentResponse>(
    `${getFilesApiBase(scope)}/content${qs}`,
    { errorMessage: 'Failed to load file content' },
  )
}

export function getFileDownloadUrl(scope: FileBrowserScope, path: string): string {
  const qs = buildQueryString({ path })
  return `${getFilesApiBase(scope)}/download${qs}`
}

export async function uploadFile(
  scope: FileBrowserScope,
  directoryPath: string,
  file: File,
): Promise<FileUploadResponse> {
  const formData = new FormData()
  formData.append('upload', file)

  const qs = buildQueryString({ path: directoryPath || undefined })
  const response = await fetch(`${getFilesApiBase(scope)}/upload${qs}`, {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) {
    await throwFromResponse(response, 'Failed to upload file')
  }
  return response.json() as Promise<FileUploadResponse>
}
