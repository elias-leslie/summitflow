import { useQuery } from '@tanstack/react-query'
import { fetchGitStatus } from '@/lib/api'

export function useGitStatus() {
  return useQuery({
    queryKey: ['git-status'],
    queryFn: fetchGitStatus,
    staleTime: 30000,
    refetchInterval: 60000,
  })
}
