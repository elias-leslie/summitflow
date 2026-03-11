import { useQuery } from '@tanstack/react-query'
import {
  fetchExplorerOverview,
  type ExplorerOverview,
} from '@/lib/api/explorer'

export const overviewKeys = {
  all: ['explorer-overview'] as const,
  detail: (projectId: string) =>
    [...overviewKeys.all, projectId] as const,
}

interface UseExplorerOverviewReturn {
  overview: ExplorerOverview | undefined
  isLoading: boolean
  error: string | null
  refetch: () => Promise<unknown>
}

export function useExplorerOverview(
  projectId: string,
): UseExplorerOverviewReturn {
  const query = useQuery({
    queryKey: overviewKeys.detail(projectId),
    queryFn: () => fetchExplorerOverview(projectId),
    enabled: !!projectId,
    staleTime: 30000,
    refetchInterval: 60000,
    gcTime: 5 * 60 * 1000,
  })

  return {
    overview: query.data,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  }
}
