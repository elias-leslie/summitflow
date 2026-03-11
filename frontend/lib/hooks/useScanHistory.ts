/**
 * useScanHistory - Data fetching hooks for scan history
 *
 * Provides:
 * - Scan history with sparkline data and summary
 * - Scan comparison between two scans
 * - React Query caching with staleTime/refetchInterval
 */

import { useQuery } from '@tanstack/react-query'
import {
  fetchScanHistory,
  type ScanHistoryResponse,
} from '@/lib/api/explorer-scan'
import { POLL_RARE, STALE_SCAN } from '@/lib/polling'

// Query key factories for consistent cache management
export const scanHistoryKeys = {
  all: ['scan-history'] as const,
  history: (projectId: string, days: number, scanType?: string) =>
    [...scanHistoryKeys.all, projectId, days, scanType ?? 'all'] as const,
  comparison: (projectId: string, before: number, after: number) =>
    [...scanHistoryKeys.all, 'comparison', projectId, before, after] as const,
}

interface UseScanHistoryOptions {
  projectId: string
  days?: number
  scanType?: string
  enabled?: boolean
}

interface UseScanHistoryReturn {
  data: ScanHistoryResponse | undefined
  scans: ScanHistoryResponse['scans']
  sparklineData: ScanHistoryResponse['sparkline_data'] | undefined
  summary: ScanHistoryResponse['summary'] | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

/**
 * Hook for fetching scan history with sparkline data and summary.
 *
 * @param projectId - Project to fetch history for
 * @param days - Number of days to look back (default: 30)
 * @param scanType - Optional filter by scan type
 * @param enabled - Whether to enable the query
 */
export function useScanHistory({
  projectId,
  days = 30,
  scanType,
  enabled = true,
}: UseScanHistoryOptions): UseScanHistoryReturn {
  const query = useQuery({
    queryKey: scanHistoryKeys.history(projectId, days, scanType),
    queryFn: () => fetchScanHistory(projectId, days, scanType),
    enabled: enabled && !!projectId,
    staleTime: STALE_SCAN,
    refetchInterval: POLL_RARE,
    gcTime: POLL_RARE * 2,
  })

  return {
    data: query.data,
    scans: query.data?.scans ?? [],
    sparklineData: query.data?.sparkline_data,
    summary: query.data?.summary,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: () => query.refetch(),
  }
}

