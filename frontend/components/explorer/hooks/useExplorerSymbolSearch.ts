'use client'

import { useQuery } from '@tanstack/react-query'
import {
  type ExplorerSymbolDetailResponse,
  type ExplorerSymbolSearchResponse,
  fetchExplorerSymbolDetail,
  searchExplorerSymbols,
} from '@/lib/api/explorer'
import { GC_EXPLORER, STALE_GIT } from '@/lib/polling'
import { explorerKeys } from './useExplorerData'

export const explorerSymbolKeys = {
  search: (
    projectId: string,
    query: string,
    language?: string,
    kind?: string,
    limit: number = 12,
  ) =>
    [
      ...explorerKeys.all,
      'symbol-search',
      projectId,
      query,
      language ?? '',
      kind ?? '',
      limit,
    ] as const,
  detail: (projectId: string, symbolId: string, contextLines: number = 4) =>
    [
      ...explorerKeys.all,
      'symbol-detail',
      projectId,
      symbolId,
      contextLines,
    ] as const,
}

export function useExplorerSymbolSearch(
  projectId: string,
  query: string,
  options: {
    language?: string
    kind?: string
    limit?: number
    enabled?: boolean
  } = {},
) {
  const trimmedQuery = query.trim()
  return useQuery<ExplorerSymbolSearchResponse>({
    queryKey: explorerSymbolKeys.search(
      projectId,
      trimmedQuery,
      options.language,
      options.kind,
      options.limit ?? 12,
    ),
    queryFn: () =>
      searchExplorerSymbols(projectId, {
        q: trimmedQuery,
        language: options.language,
        kind: options.kind,
        limit: options.limit,
      }),
    enabled:
      Boolean(projectId) &&
      (options.enabled ?? true) &&
      trimmedQuery.length >= 2,
    staleTime: STALE_GIT,
    gcTime: GC_EXPLORER,
  })
}

export function useExplorerSymbolDetail(
  projectId: string,
  symbolId: string | null,
  options: {
    contextLines?: number
    enabled?: boolean
  } = {},
) {
  const contextLines = options.contextLines ?? 4
  return useQuery<ExplorerSymbolDetailResponse>({
    queryKey: explorerSymbolKeys.detail(
      projectId,
      symbolId ?? '',
      contextLines,
    ),
    queryFn: () =>
      fetchExplorerSymbolDetail(projectId, {
        symbolId: symbolId ?? '',
        contextLines,
      }),
    enabled: Boolean(projectId && symbolId) && (options.enabled ?? true),
    staleTime: STALE_GIT,
    gcTime: GC_EXPLORER,
  })
}
