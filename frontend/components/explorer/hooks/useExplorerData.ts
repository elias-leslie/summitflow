/**
 * useExplorerData - Data fetching hook for explorer
 *
 * Responsibilities:
 * - Fetch entries with react-query
 * - Cache management
 * - Refetch/invalidation
 *
 * Does NOT handle: UI state (expanded, selected), filters
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type ExplorerEntry,
  type ExplorerEntryType,
  type ExplorerFilters,
  type ExplorerResponse,
  fetchExplorerChildren,
  fetchExplorerEntries,
  fetchExplorerStats,
  type StatsResponse,
} from '@/lib/api/explorer'
import { triggerExplorerScan } from '@/lib/api/explorer-scan'

// Query key factories for consistent cache management
export const explorerKeys = {
  all: ['explorer'] as const,
  entries: (projectId: string) =>
    [...explorerKeys.all, 'entries', projectId] as const,
  entriesFiltered: (projectId: string, filters: ExplorerFilters) =>
    [...explorerKeys.entries(projectId), filters] as const,
  stats: (projectId: string) =>
    [...explorerKeys.all, 'stats', projectId] as const,
  children: (projectId: string, type: ExplorerEntryType, path: string) =>
    [...explorerKeys.all, 'children', projectId, type, path] as const,
}

interface UseExplorerDataOptions {
  projectId: string
  filters?: ExplorerFilters
  enabled?: boolean
}

interface UseExplorerDataReturn {
  // Entries query
  entries: ExplorerEntry[]
  total: number
  stats: ExplorerResponse['stats'] | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void

  // Stats query (separate for header display)
  statsData: StatsResponse | undefined
  isLoadingStats: boolean

  // Scan mutation
  scan: (type?: ExplorerEntryType) => void
  isScanning: boolean
}

/**
 * Hook for fetching explorer entries with filtering.
 */
export function useExplorerData({
  projectId,
  filters = {},
  enabled = true,
}: UseExplorerDataOptions): UseExplorerDataReturn {
  const queryClient = useQueryClient()

  // Main entries query
  const entriesQuery = useQuery({
    queryKey: explorerKeys.entriesFiltered(projectId, filters),
    queryFn: () => fetchExplorerEntries(projectId, filters),
    enabled: enabled && !!projectId,
    staleTime: 30000, // 30 seconds
    gcTime: 5 * 60 * 1000, // 5 minutes (formerly cacheTime)
  })

  // Separate stats query for header (can be shared across filter changes)
  const statsQuery = useQuery({
    queryKey: explorerKeys.stats(projectId),
    queryFn: () => fetchExplorerStats(projectId),
    enabled: enabled && !!projectId,
    staleTime: 60000, // 1 minute
    gcTime: 5 * 60 * 1000,
  })

  // Scan mutation
  const scanMutation = useMutation({
    mutationFn: (type?: ExplorerEntryType) =>
      triggerExplorerScan(projectId, type),
    onSuccess: () => {
      // Invalidate after scan completes
      // Small delay to let backend process
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: explorerKeys.entries(projectId),
        })
        queryClient.invalidateQueries({
          queryKey: explorerKeys.stats(projectId),
        })
      }, 2000)
    },
  })

  return {
    // Entries
    entries: entriesQuery.data?.entries ?? [],
    total: entriesQuery.data?.total ?? 0,
    stats: entriesQuery.data?.stats,
    isLoading: entriesQuery.isLoading,
    isError: entriesQuery.isError,
    error: entriesQuery.error,
    refetch: () => entriesQuery.refetch(),

    // Stats
    statsData: statsQuery.data,
    isLoadingStats: statsQuery.isLoading,

    // Scan
    scan: (type) => scanMutation.mutate(type),
    isScanning: scanMutation.isPending,
  }
}

interface UseExplorerChildrenOptions {
  projectId: string
  type: ExplorerEntryType
  parentPath: string
  enabled?: boolean
}

/**
 * Hook for fetching children of a path (tree navigation).
 */
export function useExplorerChildren({
  projectId,
  type,
  parentPath,
  enabled = true,
}: UseExplorerChildrenOptions) {
  return useQuery({
    queryKey: explorerKeys.children(projectId, type, parentPath),
    queryFn: () => fetchExplorerChildren(projectId, type, parentPath),
    enabled: enabled && !!projectId,
    staleTime: 30000,
    gcTime: 5 * 60 * 1000,
  })
}
