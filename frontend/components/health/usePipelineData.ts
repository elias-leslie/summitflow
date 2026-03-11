import { useQuery } from '@tanstack/react-query'
import { buildQueryString, fetchWithErrorHandling } from '@/lib/api'
import { POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'
import type { PipelineStatsResponse } from './PipelineTypes'

export function usePipelineData(projectId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['pipeline-stats', projectId],
    queryFn: () =>
      fetchWithErrorHandling<PipelineStatsResponse>(
        `/api/pipeline/stats${buildQueryString({ project_id: projectId })}`,
        {
          errorMessage: 'Failed to fetch pipeline stats',
        },
      ),
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
    enabled: !!projectId,
  })

  return {
    pipelineData: data,
    pipelineLoading: isLoading,
    pipelineError: error,
  }
}
