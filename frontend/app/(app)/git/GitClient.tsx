'use client'

import { useQuery } from '@tanstack/react-query'
import { ProjectRow } from '@/components/git/ProjectRow'
import { fetchDevelopmentStatus } from '@/lib/api/git'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

export function GitClient() {
  const query = useQuery({
    queryKey: ['development-status'],
    queryFn: fetchDevelopmentStatus,
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
  })
  return (
    <div className="mx-auto max-w-[1800px] space-y-4 px-4 py-4 md:px-6">
      <header>
        <h1 className="display text-xl font-semibold text-slate-100">
          Development
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Working source, runtime observations and recovery evidence
        </p>
      </header>
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
      {query.data?.total === 0 && (
        <p className="card p-6 text-sm text-slate-400">
          No managed repositories found
        </p>
      )}
      {query.data?.unavailable_repositories?.map((repo) => (
        <p
          key={repo.path}
          role="alert"
          className="card p-4 text-sm text-amber-300"
        >
          {repo.name}: {repo.reason}
        </p>
      ))}
      <div className="space-y-4">
        {query.data?.repositories.map(({ repo, development }) => (
          <ProjectRow key={repo.path} repo={repo} development={development} />
        ))}
      </div>
    </div>
  )
}
