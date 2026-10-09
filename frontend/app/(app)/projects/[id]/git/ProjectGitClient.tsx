'use client'

import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { ProjectRow } from '@/components/git/ProjectRow'
import {
  fetchProjectDevelopmentStatus,
  fetchProjectGitStatus,
} from '@/lib/api/git'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

export function ProjectGitClient() {
  const projectId = useParams().id as string
  const query = useQuery({
    queryKey: ['development-status', projectId],
    queryFn: async () => {
      const [development, git] = await Promise.all([
        fetchProjectDevelopmentStatus(projectId),
        fetchProjectGitStatus(projectId),
      ])
      return { development, repo: git.repositories[0] }
    },
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
  })
  return (
    <div className="mx-auto max-w-[1800px] space-y-4 px-4 py-4 md:px-6">
      <h1 className="display text-xl font-semibold text-slate-100">
        Project Development
      </h1>
      {query.isLoading && (
        <p role="status" className="card p-6 text-sm text-slate-300">
          Loading development evidence…
        </p>
      )}
      {query.isError && (
        <div role="alert" className="card space-y-2 p-4 text-sm text-rose-300">
          <p>
            {query.data
              ? 'Showing retained data. Latest refresh failed.'
              : 'Could not load development evidence.'}
          </p>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => query.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      {query.data && !query.data.repo && (
        <p className="card p-6 text-sm text-slate-400">
          Repository status unavailable for this project
        </p>
      )}
      {query.data?.repo && (
        <ProjectRow
          repo={query.data.repo}
          development={query.data.development}
        />
      )}
    </div>
  )
}
