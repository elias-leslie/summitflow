/**
 * useFileExplorer - Data fetching hooks for the file browser.
 */

import { useQuery } from '@tanstack/react-query'
import {
  type FileBrowserScope,
  type FileContentResponse,
  type FileTreeResponse,
  fetchFileContent,
  fetchFileTree,
  getFileScopeKey,
} from '@/lib/api/files'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

export const fileQueryKeys = {
  all: ['files'] as const,
  scope: (scope: FileBrowserScope) =>
    [...fileQueryKeys.all, getFileScopeKey(scope)] as const,
  tree: (scope: FileBrowserScope, path: string) =>
    [...fileQueryKeys.scope(scope), 'tree', path] as const,
  content: (scope: FileBrowserScope, path: string) =>
    [...fileQueryKeys.scope(scope), 'content', path] as const,
}

export function useFileTree(scope: FileBrowserScope, path: string = '') {
  return useQuery<FileTreeResponse>({
    queryKey: fileQueryKeys.tree(scope, path),
    queryFn: () => fetchFileTree(scope, path),
    enabled: scope.kind === 'workspace' || !!scope.projectId,
    staleTime: STALE_GIT,
  })
}

export function useFileContent(scope: FileBrowserScope, path: string | null) {
  return useQuery<FileContentResponse>({
    queryKey: fileQueryKeys.content(scope, path ?? ''),
    queryFn: () => fetchFileContent(scope, path!),
    enabled: (scope.kind === 'workspace' || !!scope.projectId) && !!path,
    staleTime: POLL_SLOW,
  })
}
