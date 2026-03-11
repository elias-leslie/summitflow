import { useQuery } from '@tanstack/react-query'
import { fetchGitStatus } from '@/lib/api'
import { POLL_STANDARD, STALE_GIT } from '@/lib/polling'

export function useGitStatus() {
  return useQuery({
    queryKey: ['git-status'],
    queryFn: fetchGitStatus,
    staleTime: STALE_GIT,
    refetchInterval: POLL_STANDARD,
    refetchIntervalInBackground: true,
  })
}
