'use client'

import { useQuery } from '@tanstack/react-query'
import {
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  Loader2,
  Shield,
} from 'lucide-react'
import { useState } from 'react'
import { fetchProjectDashboard } from '@/lib/api/git-enhanced'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'
import { BranchRow } from './BranchRow'
import { CheckpointCompact } from './CheckpointCompact'
import { CommitEntry } from './CommitEntry'
import { MergeRow } from './MergeRow'
import { SectionLabel } from './SectionLabel'
import { SnapshotEntry } from './SnapshotEntry'

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
      <div className="flex items-center justify-center py-6">
        <Loader2 className="w-4 h-4 animate-spin text-slate-600" />
      </div>
    )
  }

  if (!data) return null

  const hasCheckpoints = data.checkpoints.length > 0
  const hasBranches = data.branches.length > 0
  const hasMerges = data.recent_merges.length > 0
  const hasCommits = data.recent_commits.length > 0
  const hasSnapshots = data.snapshots.length > 0

  if (
    !hasCheckpoints &&
    !hasBranches &&
    !hasMerges &&
    !hasCommits &&
    !hasSnapshots
  ) {
    return (
      <div className="text-center py-4 text-slate-600 text-xs">
        No activity data.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {hasCheckpoints && (
        <div>
          <SectionLabel
            icon={GitBranch}
            label="Checkpoints"
            count={data.checkpoints.length}
            color="text-phosphor-400"
            badgeBg="bg-phosphor-500/10"
            badgeBorder="border-phosphor-500/20"
          />
          <div className="space-y-1">
            {data.checkpoints.map((checkpoint) => (
              <CheckpointCompact
                key={checkpoint.task_id}
                checkpoint={checkpoint}
              />
            ))}
          </div>
        </div>
      )}
      {hasBranches && (
        <div>
          <SectionLabel
            icon={GitBranch}
            label="Branches"
            count={data.branches.length}
            color="text-cyan-300"
            badgeBg="bg-cyan-500/10"
            badgeBorder="border-cyan-500/20"
          />
          <div className="space-y-1">
            {data.branches.map((branch) => (
              <BranchRow key={branch.name} branch={branch} />
            ))}
          </div>
        </div>
      )}
      {hasMerges && (
        <div>
          <SectionLabel
            icon={GitMerge}
            label="Merged Tasks"
            count={data.recent_merges.length}
            color="text-purple-400"
            badgeBg="bg-purple-500/10"
            badgeBorder="border-purple-500/20"
          />
          <div className="space-y-1">
            {data.recent_merges.map((merge) => (
              <MergeRow key={merge.task_id} merge={merge} />
            ))}
          </div>
        </div>
      )}
      {hasCommits && (
        <div>
          <SectionLabel
            icon={GitCommitHorizontal}
            label="Recent Commits"
            count={data.recent_commits.length}
            color="text-phosphor-400"
            badgeBg="bg-phosphor-500/10"
            badgeBorder="border-phosphor-500/20"
          />
          <div className="rounded-lg border border-slate-800/30 bg-slate-900/20 divide-y divide-slate-800/15 overflow-hidden">
            {data.recent_commits.slice(0, 15).map((commit) => (
              <CommitEntry
                key={commit.sha}
                commit={commit}
                projectId={projectId}
              />
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
            <div className="space-y-1">
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
