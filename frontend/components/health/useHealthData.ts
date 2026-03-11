import { useQuery } from '@tanstack/react-query'
import { buildQueryString, fetchWithErrorHandling } from '@/lib/api'
import type {
  CheckResultsResponse,
  HealthSummary,
} from './HealthTypes'

export function useHealthData(projectId: string) {
  const { data: health, isLoading: healthLoading, error: healthError } = useQuery({
    queryKey: ['quality-health', projectId],
    queryFn: () =>
      fetchWithErrorHandling<HealthSummary>(
        `/api/projects/${projectId}/quality/health`,
        {
          errorMessage: 'Failed to fetch quality health',
        },
      ),
    refetchInterval: 30000,
  })

  const recentQuery = buildQueryString({ limit: 50 })
  const unfixedQuery = buildQueryString({ unfixed_only: true, limit: 10 })

  const { data: recentResults, error: recentResultsError } = useQuery({
    queryKey: ['quality-results', projectId, 'recent'],
    queryFn: () =>
      fetchWithErrorHandling<CheckResultsResponse>(
        `/api/projects/${projectId}/quality/results${recentQuery}`,
        {
          errorMessage: 'Failed to fetch recent quality results',
        },
      ),
    refetchInterval: 30000,
  })

  const { data: unfixedResults, error: unfixedResultsError } = useQuery({
    queryKey: ['quality-results', projectId, 'unfixed'],
    queryFn: () =>
      fetchWithErrorHandling<CheckResultsResponse>(
        `/api/projects/${projectId}/quality/results${unfixedQuery}`,
        {
          errorMessage: 'Failed to fetch unfixed quality issues',
        },
      ),
    refetchInterval: 30000,
  })

  // Compute metrics
  const fixedToday =
    recentResults?.items.filter((r) => {
      if (!r.fixed_at) return false
      const fixedDate = new Date(r.fixed_at)
      const today = new Date()
      return fixedDate.toDateString() === today.toDateString()
    }).length ?? 0

  const inProgress =
    unfixedResults?.items.filter((r) => r.fix_attempted && !r.fixed_at)
      .length ?? 0
  const escalated =
    unfixedResults?.items.filter((r) => r.escalation_task_id).length ?? 0

  // Calculate fix pipeline stats (last 7 days)
  const sevenDaysAgo = new Date()
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
  const last7Days =
    recentResults?.items.filter(
      (r) => new Date(r.created_at) >= sevenDaysAgo,
    ) ?? []
  const detected = last7Days.length
  const flashFixed = last7Days.filter(
    (r) => r.fixed_by?.includes('flash') || r.fixed_by?.includes('gemini'),
  ).length
  const sonnetFixed = last7Days.filter(
    (r) => r.fixed_by?.includes('sonnet') || r.fixed_by?.includes('claude'),
  ).length
  const escalatedCount = last7Days.filter((r) => r.escalation_task_id).length
  const autoFixRate =
    detected > 0 ? Math.round(((flashFixed + sonnetFixed) / detected) * 100) : 0

  return {
    health,
    healthLoading,
    healthError,
    recentResults,
    recentResultsError,
    unfixedResults,
    unfixedResultsError,
    metrics: {
      fixedToday,
      inProgress,
      escalated,
      detected,
      flashFixed,
      sonnetFixed,
      escalatedCount,
      autoFixRate,
    },
  }
}
