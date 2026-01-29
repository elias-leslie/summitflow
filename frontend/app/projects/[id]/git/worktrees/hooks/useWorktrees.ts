import { useQuery } from '@tanstack/react-query'
import { fetchWorktrees } from '@/lib/api'

export function useWorktrees(projectId: string) {
  return useQuery({
    queryKey: ['worktrees', projectId],
    queryFn: () => fetchWorktrees(projectId),
    refetchInterval: 30000,
  })
}
