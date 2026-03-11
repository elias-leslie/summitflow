/**
 * useFileExplorer - Data fetching hooks for the file browser
 *
 * Provides:
 * - File tree listing with lazy loading
 * - File content fetching with language detection
 * - React Query caching with appropriate stale times
 */

import { useQuery } from '@tanstack/react-query'
import {
  fetchFileTree,
  fetchFileContent,
  type FileTreeResponse,
  type FileContentResponse,
} from '@/lib/api/files'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

// Query key factories for consistent cache management
export const fileQueryKeys = {
  all: ['files'] as const,
  tree: (projectId: string, path: string) =>
    [...fileQueryKeys.all, 'tree', projectId, path] as const,
  content: (projectId: string, path: string) =>
    [...fileQueryKeys.all, 'content', projectId, path] as const,
}

export function useFileTree(projectId: string, path: string = '') {
  return useQuery<FileTreeResponse>({
    queryKey: fileQueryKeys.tree(projectId, path),
    queryFn: () => fetchFileTree(projectId, path),
    enabled: !!projectId,
    staleTime: STALE_GIT,
  })
}

export function useFileContent(projectId: string, path: string | null) {
  return useQuery<FileContentResponse>({
    queryKey: fileQueryKeys.content(projectId, path ?? ''),
    queryFn: () => fetchFileContent(projectId, path!),
    enabled: !!projectId && !!path,
    staleTime: POLL_SLOW,
  })
}
