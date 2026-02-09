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
  fetchScanComparison,
  fetchScanHistory,
  type ScanComparison,
  type ScanHistoryResponse,
} from '@/lib/api/explorer-scan'

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
    staleTime: 2 * 60 * 1000, // 2 minutes
    refetchInterval: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
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

interface UseScanComparisonOptions {
  projectId: string
  before: number
  after: number
  enabled?: boolean
}

interface UseScanComparisonReturn {
  data: ScanComparison | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
}

/**
 * Hook for fetching comparison between two scans.
 *
 * @param projectId - Project ID
 * @param before - Scan ID of the baseline scan
 * @param after - Scan ID of the comparison scan
 * @param enabled - Whether to enable the query
 */
export function useScanComparison({
  projectId,
  before,
  after,
  enabled = true,
}: UseScanComparisonOptions): UseScanComparisonReturn {
  const query = useQuery({
    queryKey: scanHistoryKeys.comparison(projectId, before, after),
    queryFn: () => fetchScanComparison(projectId, before, after),
    enabled: enabled && !!projectId && before > 0 && after > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes - comparisons don't change
    gcTime: 30 * 60 * 1000, // 30 minutes
  })

  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
  }
}
