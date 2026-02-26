/**
 * File Browser API Client
 *
 * API client for browsing and reading project files.
 * Follows patterns from lib/api/explorer.ts.
 */

import { buildQueryString, fetchWithErrorHandling } from './utils'
import { getApiBaseUrl } from '../api-config'

// ============================================================================
// Types
// ============================================================================

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

// ============================================================================
// API Functions
// ============================================================================

export function fetchFileTree(
  projectId: string,
  path: string = '',
): Promise<FileTreeResponse> {
  const qs = buildQueryString({ path: path || undefined })
  return fetchWithErrorHandling<FileTreeResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/files/tree${qs}`,
    { errorMessage: 'Failed to load file tree' },
  )
}

export function fetchFileContent(
  projectId: string,
  path: string,
): Promise<FileContentResponse> {
  const qs = buildQueryString({ path })
  return fetchWithErrorHandling<FileContentResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/files/content${qs}`,
    { errorMessage: 'Failed to load file content' },
  )
}
