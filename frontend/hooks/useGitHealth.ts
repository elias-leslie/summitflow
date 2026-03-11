import { useQuery } from '@tanstack/react-query'
import { fetchGitStatus, type RepoStatus } from '@/lib/api/git'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

export type GitHealthState = 'clean' | 'dirty' | 'behind' | 'loading' | 'error'

export function useGitHealth(): GitHealthState {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['git-status-topbar'],
    queryFn: fetchGitStatus,
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
  })

  if (isLoading) return 'loading'
  if (isError || !data) return 'error'

  const repos = data.repositories
  if (repos.some((r: RepoStatus) => r.state === 'behind')) return 'behind'
  if (repos.some((r: RepoStatus) => r.state === 'dirty' || r.state === 'ahead'))
    return 'dirty'
  return 'clean'
}
