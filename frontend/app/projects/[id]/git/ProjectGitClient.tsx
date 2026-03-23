'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { ConflictAlerts } from '@/components/git/ConflictAlerts'
import { DashboardContent } from '@/components/git/project-row/DashboardContent'
import {
  fetchProjectGitStatus,
  pullRepository,
  type SyncResult,
} from '@/lib/api'
import { POLL_STANDARD, STALE_STANDARD, TOAST_DISMISS_MS } from '@/lib/polling'
import { GitPageHeader } from './GitPageHeader'
import { GitRepoCard } from './GitRepoCard'
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
    mutationFn: () => pullRepository(projectId),
    onSuccess: (data) => {
      setSyncResults(data.results)
      queryClient.invalidateQueries({ queryKey: ['git-status', projectId] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', projectId],
      })
      queryClient.invalidateQueries({ queryKey: ['git-conflicts'] })
      setTimeout(() => setSyncResults(null), TOAST_DISMISS_MS)
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
          <h2 className="display text-lg font-semibold text-slate-100 mb-2">
            Failed to Load
          </h2>
          <p className="text-slate-400 mb-6">
            Could not connect to git status service.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="btn-primary"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const repos = gitStatus?.repositories ?? []
  const cleanCount = repos.filter((r) => r.state === 'clean').length
  const attentionCount = repos.filter((r) => r.state !== 'clean').length

  return (
    <div className="p-6 space-y-8">
      <GitPageHeader
        cleanCount={cleanCount}
        dirtyCount={attentionCount}
        isSyncing={syncMutation.isPending}
        onSync={handleSync}
        cleanLabel="Synced"
        dirtyLabel="Attention"
        actionLabel="Pull Latest"
        busyLabel="Pulling..."
        title="Project Git Operations"
        description="Inspect repository health, worktrees, branches, and recent git activity for this project."
      />

      {syncResults && <GitSyncToast results={syncResults} />}

      <ConflictAlerts projectId={projectId} />

      <section>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {repos.map((repo) => (
            <GitRepoCard key={repo.path} repo={repo} />
          ))}
        </div>
      </section>

      {repos.length > 0 && (
        <section className="card p-5">
          <DashboardContent projectId={projectId} />
        </section>
      )}
    </div>
  )
}
