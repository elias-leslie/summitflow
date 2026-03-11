'use client'

import { useQuery } from '@tanstack/react-query'
import { GitCommitHorizontal, GitMerge, Layers, Loader2, Shield } from 'lucide-react'
import { useState } from 'react'
import { fetchProjectDashboard } from '@/lib/api/git-enhanced'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'
import { CommitEntry } from './CommitEntry'
import { MergeRow } from './MergeRow'
import { SectionLabel } from './SectionLabel'
import { SnapshotEntry } from './SnapshotEntry'
import { WorktreeCompact } from './WorktreeCompact'

export function DashboardContent({ projectId }: { projectId: string }) {
  const [snapshotsOpen, setSnapshotsOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['project-dashboard', projectId],
    queryFn: () => fetchProjectDashboard(projectId),
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin text-phosphor-500" />
          Loading dashboard...
        </div>
      </div>
    )
  }

  if (!data) return null

  const hasWorktrees = data.worktrees.length > 0
  const hasMerges = data.recent_merges.length > 0
  const hasCommits = data.recent_commits.length > 0
  const hasSnapshots = data.snapshots.length > 0

  if (!hasWorktrees && !hasMerges && !hasCommits && !hasSnapshots) {
    return (
      <div className="text-center py-6 text-slate-600 text-sm">
        No activity data for this project.
      </div>
    )
  }

  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {hasWorktrees && (
        <div>
          <SectionLabel icon={Layers} label="Worktrees" count={data.worktrees.length} color="text-phosphor-400" badgeBg="bg-phosphor-500/10" badgeBorder="border-phosphor-500/20" />
          <div className="space-y-1.5">
            {data.worktrees.map((wt) => (
              <WorktreeCompact key={wt.task_id} worktree={wt} />
            ))}
          </div>
        </div>
      )}
      {hasMerges && (
        <div>
          <SectionLabel icon={GitMerge} label="Merged Tasks" count={data.recent_merges.length} color="text-purple-400" badgeBg="bg-purple-500/10" badgeBorder="border-purple-500/20" />
          <div className="space-y-1.5">
            {data.recent_merges.map((merge) => (
              <MergeRow key={merge.task_id} merge={merge} />
            ))}
          </div>
        </div>
      )}
      {hasCommits && (
        <div>
          <SectionLabel icon={GitCommitHorizontal} label="Recent Commits" count={data.recent_commits.length} color="text-phosphor-400" badgeBg="bg-phosphor-500/10" badgeBorder="border-phosphor-500/20" />
          <div className="rounded-md border border-slate-800/40 bg-slate-900/10 divide-y divide-slate-800/30 overflow-hidden">
            {data.recent_commits.slice(0, 15).map((commit) => (
              <CommitEntry key={commit.sha} commit={commit} projectId={projectId} />
            ))}
          </div>
        </div>
      )}
      {hasSnapshots && (
        <div>
          <SectionLabel
            icon={Shield}
            label="Snapshots"
            count={data.snapshots.length}
            color="text-amber-400"
            badgeBg="bg-amber-500/10"
            badgeBorder="border-amber-500/20"
            expanded={snapshotsOpen}
            onToggle={() => setSnapshotsOpen(!snapshotsOpen)}
          />
          {snapshotsOpen && (
            <div className="space-y-1.5 animate-in fade-in duration-200">
              {data.snapshots.map((snap) => (
                <SnapshotEntry key={snap.task_id} snapshot={snap} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
