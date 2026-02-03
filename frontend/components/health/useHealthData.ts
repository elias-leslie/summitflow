import { useQuery } from '@tanstack/react-query'
import type {
  CheckResultsResponse,
  HealthSummary,
} from './HealthTypes'

export function useHealthData(projectId: string) {
  // Fetch health summary
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['quality-health', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/quality/health`)
      if (!res.ok) throw new Error('Failed to fetch health')
      return res.json() as Promise<HealthSummary>
    },
    refetchInterval: 30000,
  })

  // Fetch recent results (activity feed)
  const { data: recentResults } = useQuery({
    queryKey: ['quality-results', projectId, 'recent'],
    queryFn: async () => {
      const res = await fetch(
        `/api/projects/${projectId}/quality/results?limit=50`,
      )
      if (!res.ok) throw new Error('Failed to fetch results')
      return res.json() as Promise<CheckResultsResponse>
    },
    refetchInterval: 30000,
  })

  // Fetch unfixed (needs attention)
  const { data: unfixedResults } = useQuery({
    queryKey: ['quality-results', projectId, 'unfixed'],
    queryFn: async () => {
      const res = await fetch(
        `/api/projects/${projectId}/quality/results?unfixed_only=true&limit=10`,
      )
      if (!res.ok) throw new Error('Failed to fetch unfixed')
      return res.json() as Promise<CheckResultsResponse>
    },
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
    recentResults,
    unfixedResults,
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
