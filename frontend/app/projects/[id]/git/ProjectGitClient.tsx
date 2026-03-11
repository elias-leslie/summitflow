'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import {
  fetchProjectGitStatus,
  type SyncResult,
  syncRepositories,
} from '@/lib/api'
import { GitPageHeader } from './GitPageHeader'
import { GitRepoCard } from './GitRepoCard'
import { POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'
import { GitSyncToast } from './GitSyncToast'

export function ProjectGitClient() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()
  const [syncResults, setSyncResults] = useState<SyncResult[] | null>(null)

  const {
    data: gitStatus,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['git-status', projectId],
    queryFn: () => fetchProjectGitStatus(projectId),
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
  })

  const syncMutation = useMutation({
    mutationFn: syncRepositories,
    onSuccess: (data) => {
      setSyncResults(data.results)
      queryClient.invalidateQueries({ queryKey: ['git-status', projectId] })
      setTimeout(() => setSyncResults(null), 5000)
    },
  })

  const handleSync = () => {
    setSyncResults(null)
    syncMutation.mutate()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="card p-8 text-center max-w-md">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
          <h2 className="display text-lg font-semibold text-white mb-2">
            Failed to Load
          </h2>
          <p className="text-slate-400 mb-6">
            Could not connect to git status service.
          </p>
          <button onClick={() => refetch()} className="btn-primary">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const repos = gitStatus?.repositories ?? []
  const cleanCount = repos.filter((r) => r.state === 'clean').length
  const dirtyCount = repos.filter((r) => r.state === 'dirty').length

  return (
    <div className="p-6 space-y-8">
      <GitPageHeader
        cleanCount={cleanCount}
        dirtyCount={dirtyCount}
        isSyncing={syncMutation.isPending}
        onSync={handleSync}
      />

      {syncResults && <GitSyncToast results={syncResults} />}

      <section>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {repos.map((repo) => (
            <GitRepoCard key={repo.path} repo={repo} />
          ))}
        </div>
      </section>
    </div>
  )
}
