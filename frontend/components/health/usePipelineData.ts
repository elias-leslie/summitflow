import { useQuery } from '@tanstack/react-query'
import type { PipelineStatsResponse } from './PipelineTypes'

export function usePipelineData(projectId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['pipeline-stats', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/pipeline/stats?project_id=${projectId}`)
      if (!res.ok) throw new Error('Failed to fetch pipeline stats')
      return res.json() as Promise<PipelineStatsResponse>
    },
    refetchInterval: 30000, // Refetch every 30 seconds
  })

  return {
    pipelineData: data,
    pipelineLoading: isLoading,
    pipelineError: error,
  }
}
