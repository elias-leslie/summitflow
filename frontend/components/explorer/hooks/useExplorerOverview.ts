import { useQuery } from '@tanstack/react-query'
import {
  type ExplorerOverview,
  fetchExplorerOverview,
} from '@/lib/api/explorer'
import { GC_EXPLORER, POLL_SLOW, STALE_GIT } from '@/lib/polling'

export const overviewKeys = {
  all: ['explorer-overview'] as const,
  detail: (projectId: string) => [...overviewKeys.all, projectId] as const,
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
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
    gcTime: GC_EXPLORER,
  })

  return {
    overview: query.data,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  }
}
