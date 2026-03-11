import { useQuery } from '@tanstack/react-query'
import { buildQueryString, fetchWithErrorHandling } from '@/lib/api'
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
    refetchInterval: 30000,
    enabled: !!projectId,
  })

  return {
    pipelineData: data,
    pipelineLoading: isLoading,
    pipelineError: error,
  }
}
