'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  Bot,
  ChevronDown,
  ChevronRight,
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  Layers,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  Shield,
  Sparkles,
  CheckCircle2,
  XCircle,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { smartSyncProject, type RepoStatus } from '@/lib/api'
import {
  fetchCommitDiff,
  fetchProjectDashboard,
  fetchTaskDiff,
  revertToSnapshot,
  type CommitInfo,
  type MergedTaskSummary,
  type SnapshotInfo,
  type WorktreeInfo,
} from '@/lib/api/git-enhanced'
import { getStateInfo } from '@/app/git/utils'
import { DiffPanel } from './DiffPanel'

// --- Shared Helpers ---

function relativeTime(iso: string): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function isAgentCommit(commit: CommitInfo): boolean {
  return commit.author_email.includes('anthropic.com')
}

function StatBar({ additions, deletions }: { additions: number; deletions: number }) {
  const total = additions + deletions
  if (total === 0) return null
  const addPct = Math.max(2, (additions / total) * 100)
  const delPct = Math.max(2, (deletions / total) * 100)

  return (
    <div className="flex items-center h-1.5 w-14 rounded-full overflow-hidden bg-slate-800">
      <div className="h-full bg-emerald-500 rounded-l-full" style={{ width: `${addPct}%` }} />
      <div className="h-full bg-rose-500 rounded-r-full" style={{ width: `${delPct}%` }} />
    </div>
  )
}

// --- Sub-section: Worktrees ---

function WorktreeCompact({ worktree }: { worktree: WorktreeInfo }) {
  const displayPath = worktree.path.replace(/^\/home\/[^/]+/, '~')

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-md bg-slate-900/40 border border-slate-800/50 hover:border-phosphor-500/20 transition-colors">
      <div className="relative shrink-0">
        <Layers className="w-4 h-4 text-phosphor-500" />
        {worktree.is_active && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.6)]" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-sm font-semibold text-white">{worktree.task_id}</span>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <GitBranch className="w-2.5 h-2.5" />
          <span className="font-mono text-violet-300">{worktree.branch}</span>
          <span className="text-slate-700">/</span>
          <span className="font-mono truncate">{displayPath}</span>
        </div>
      </div>
      <span
        className={clsx(
          'text-[9px] font-mono px-1.5 py-0.5 rounded border shrink-0',
          worktree.is_active
            ? 'bg-phosphor-500/10 text-phosphor-400 border-phosphor-500/20'
            : 'bg-slate-800/50 text-slate-500 border-slate-700/50',
        )}
      >
        {worktree.is_active ? 'ACTIVE' : 'IDLE'}
      </span>
    </div>
  )
}

// --- Sub-section: Merged Tasks ---

function MergeRow({ merge }: { merge: MergedTaskSummary }) {
  const [diffOpen, setDiffOpen] = useState(false)

  const { data: diffData } = useQuery({
    queryKey: ['task-diff', merge.task_id],
    queryFn: () => fetchTaskDiff(merge.task_id),
    enabled: diffOpen,
    staleTime: 300000,
  })

  return (
    <>
      <button
        onClick={() => setDiffOpen(true)}
        className={clsx(
          'w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left transition-all',
          'bg-slate-900/30 border border-slate-800/50',
          'hover:bg-slate-800/40 hover:border-purple-500/20',
        )}
      >
        <GitMerge className="w-3.5 h-3.5 text-purple-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-sm text-white truncate block">{merge.task_title}</span>
          <span className="text-[10px] text-slate-500">{relativeTime(merge.merged_at)}</span>
        </div>
        <div className="shrink-0 flex items-center gap-2.5">
          <StatBar additions={merge.additions} deletions={merge.deletions} />
          <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-0.5">
            <Plus className="w-2.5 h-2.5" />{merge.additions}
          </span>
          <span className="text-[10px] font-mono text-rose-400 flex items-center gap-0.5">
            <Minus className="w-2.5 h-2.5" />{merge.deletions}
          </span>
        </div>
      </button>
      {diffData && (
        <DiffPanel
          open={diffOpen}
          onClose={() => setDiffOpen(false)}
          title={merge.task_title}
          subtitle={`${merge.task_id} | ${merge.project_id}`}
          files={diffData.files}
          stats={diffData.stats}
        />
      )}
    </>
  )
}

// --- Sub-section: Commits ---

function CommitEntry({ commit, projectId }: { commit: CommitInfo; projectId: string }) {
  const [diffOpen, setDiffOpen] = useState(false)
  const agent = isAgentCommit(commit)

  const { data: diffData, refetch } = useQuery({
    queryKey: ['commit-diff', commit.sha],
    queryFn: () => fetchCommitDiff(commit.sha, projectId),
    enabled: false,
    staleTime: 600000,
  })

  return (
    <>
      <button
        onClick={() => {
          if (!diffData) refetch()
          setDiffOpen(true)
        }}
        className="w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-slate-800/20 transition-colors group"
      >
        {/* Agent/Human dot */}
        <div
          className={clsx(
            'w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5',
            agent
              ? 'bg-purple-500/15 border border-purple-500/30'
              : 'bg-slate-800 border border-slate-700',
          )}
        >
          {agent ? (
            <Bot className="w-2.5 h-2.5 text-purple-400" />
          ) : (
            <User className="w-2.5 h-2.5 text-slate-500" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[11px] font-mono text-phosphor-500 shrink-0">{commit.short_sha}</span>
            <span className="text-sm text-slate-300 truncate">{commit.message}</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span>{commit.author_name}</span>
            <span>{relativeTime(commit.date)}</span>
          </div>
        </div>

        {/* Stats */}
        <div className="shrink-0 flex items-center gap-1.5 text-[10px] font-mono opacity-50 group-hover:opacity-100 transition-opacity">
          {commit.insertions > 0 && (
            <span className="text-emerald-400 flex items-center gap-0.5">
              <Plus className="w-2.5 h-2.5" />{commit.insertions}
            </span>
          )}
          {commit.deletions > 0 && (
            <span className="text-rose-400 flex items-center gap-0.5">
              <Minus className="w-2.5 h-2.5" />{commit.deletions}
            </span>
          )}
        </div>
      </button>

      {diffData && (
        <DiffPanel
          open={diffOpen}
          onClose={() => setDiffOpen(false)}
          title={commit.message}
          subtitle={`${commit.short_sha} by ${commit.author_name}`}
          files={diffData.files ?? []}
          stats={diffData.stats ?? { files_changed: 0, additions: 0, deletions: 0 }}
        />
      )}
    </>
  )
}

// --- Sub-section: Snapshots ---

function SnapshotEntry({ snapshot }: { snapshot: SnapshotInfo }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const revertMut = useMutation({
    mutationFn: () => revertToSnapshot(snapshot.task_id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['project-dashboard', snapshot.project_id] })
      setConfirming(false)
    },
  })

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-3 py-2 rounded-md transition-all',
        snapshot.is_current
          ? 'bg-phosphor-500/5 border border-phosphor-500/20'
          : 'bg-slate-900/20 border border-slate-800/40',
      )}
    >
      <div
        className={clsx(
          'w-2.5 h-2.5 rounded-full border-2 shrink-0',
          snapshot.is_current
            ? 'bg-phosphor-500 border-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.5)]'
            : 'bg-slate-900 border-slate-600',
        )}
      />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-white truncate block">{snapshot.task_title || snapshot.task_id}</span>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="font-mono">{snapshot.short_sha}</span>
          <span>{relativeTime(snapshot.created_at)}</span>
          {snapshot.commits_ahead > 0 && (
            <span className="text-amber-500/70">
              {snapshot.commits_ahead} behind
            </span>
          )}
        </div>
      </div>
      {snapshot.commits_ahead > 0 && (
        <div className="shrink-0">
          {confirming ? (
            <div className="flex items-center gap-1.5">
              <button
                disabled={revertMut.isPending}
                onClick={() => revertMut.mutate()}
                className={clsx(
                  'px-2 py-1 rounded text-[10px] font-medium transition-all',
                  revertMut.isPending
                    ? 'bg-slate-800 text-slate-500'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30',
                )}
              >
                {revertMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Confirm'}
              </button>
              <button
                disabled={revertMut.isPending}
                onClick={() => setConfirming(false)}
                className="px-2 py-1 rounded text-[10px] text-slate-500 hover:text-slate-300"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 transition-all"
            >
              <RotateCcw className="w-3 h-3" />
              Revert
            </button>
          )}
        </div>
      )}
      {revertMut.isSuccess && <span className="text-[9px] font-mono text-emerald-400 shrink-0">Reverted</span>}
      {revertMut.isError && <span className="text-[9px] font-mono text-rose-400 shrink-0">Failed</span>}
    </div>
  )
}

// --- Section Header ---

function SectionLabel({
  icon: Icon,
  label,
  count,
  color,
  badgeBg,
  badgeBorder,
  expanded,
  onToggle,
}: {
  icon: typeof GitMerge
  label: string
  count: number
  color: string
  badgeBg: string
  badgeBorder: string
  expanded?: boolean
  onToggle?: () => void
}) {
  const Wrapper = onToggle ? 'button' : 'div'
  return (
    <Wrapper
      onClick={onToggle}
      className={clsx(
        'flex items-center gap-2 mb-2',
        onToggle && 'group cursor-pointer',
      )}
    >
      {onToggle && (
        expanded
          ? <ChevronDown className="w-3 h-3 text-slate-600" />
          : <ChevronRight className="w-3 h-3 text-slate-600" />
      )}
      <Icon className={clsx('w-3.5 h-3.5', color)} />
      <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
        {label}
      </span>
      <span className={clsx('text-[9px] font-mono px-1.5 py-0.5 rounded-full border', badgeBg, color, badgeBorder)}>
        {count}
      </span>
    </Wrapper>
  )
}

// --- Expanded Dashboard Content ---

function DashboardContent({ projectId }: { projectId: string }) {
  const [snapshotsOpen, setSnapshotsOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['project-dashboard', projectId],
    queryFn: () => fetchProjectDashboard(projectId),
    staleTime: 30000,
    refetchInterval: 60000,
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
      {/* Worktrees */}
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

      {/* Merged Tasks */}
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

      {/* Recent Commits */}
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

      {/* Snapshots — collapsed sub-toggle */}
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

// --- Sync Result Display ---

function SyncResultBlock({ result }: { result: ReturnType<typeof smartSyncProject> extends Promise<infer T> ? T : never }) {
  const [showLog, setShowLog] = useState(false)

  return (
    <div className={clsx(
      'mt-3 rounded-md border p-3',
      result.success ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-pink-500/5 border-pink-500/20',
    )}>
      <div className="flex items-center gap-2 mb-1.5">
        {result.success ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <XCircle className="w-3.5 h-3.5 text-pink-500" />
        )}
        <span className={clsx('text-xs font-medium', result.success ? 'text-emerald-400' : 'text-pink-400')}>
          {result.reason === 'pushed_existing' ? 'PUSHED' : result.reason === 'no_changes' ? 'SKIP' : result.status}
        </span>
        {result.pushed && (
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            PUSHED
          </span>
        )}
      </div>

      {/* Quality Gates */}
      {result.gates && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {result.gates.split('|').filter(Boolean).map((gate) => {
            const [name, status] = gate.split(':')
            const passed = status === 'PASS' || status === 'SKIP'
            const isWarn = status?.startsWith('WARN')
            return (
              <span
                key={gate}
                className={clsx(
                  'text-[9px] font-mono px-1 py-0.5 rounded border inline-flex items-center gap-0.5',
                  passed
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : isWarn
                      ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      : 'bg-pink-500/10 text-pink-400 border-pink-500/20',
                )}
              >
                <span className={clsx('w-1 h-1 rounded-full', passed ? 'bg-emerald-400' : isWarn ? 'bg-amber-400' : 'bg-pink-400')} />
                {name}
              </span>
            )
          })}
        </div>
      )}

      {/* Errors */}
      {result.errors.length > 0 && (
        <div className="space-y-0.5 mb-1.5">
          {result.errors.map((error, i) => (
            <div key={i} className="text-[10px] font-mono text-pink-400 bg-pink-500/5 px-2 py-0.5 rounded">
              {error}
            </div>
          ))}
        </div>
      )}

      {/* AI Message */}
      {result.message && (
        <div className="text-[10px] font-mono text-slate-400 bg-slate-950/50 px-2 py-1 rounded border border-slate-800 mb-1.5">
          <span className="text-purple-400">$</span> {result.message}
        </div>
      )}

      {/* Log toggle */}
      <button
        onClick={() => setShowLog(!showLog)}
        className="flex items-center gap-1 text-[9px] text-slate-500 hover:text-slate-300 uppercase tracking-wider"
      >
        {showLog ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
        Log
      </button>
      {showLog && (
        <pre className="mt-1.5 text-[9px] font-mono leading-relaxed text-slate-400 bg-black/60 p-2 rounded border border-slate-800 overflow-x-auto max-h-40">
          {result.raw_output}
        </pre>
      )}
    </div>
  )
}

// --- Main Component ---

interface ProjectRowProps {
  repo: RepoStatus
  isConfigRepo?: boolean
}

export function ProjectRow({ repo, isConfigRepo = false }: ProjectRowProps) {
  const [expanded, setExpanded] = useState(!isConfigRepo)
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()

  const syncMutation = useMutation({
    mutationFn: () => smartSyncProject(repo.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
      queryClient.invalidateQueries({ queryKey: ['project-dashboard', repo.name] })
    },
  })

  return (
    <div
      className={clsx(
        'rounded-xl border overflow-hidden transition-all duration-300',
        'bg-gradient-to-br from-slate-900 to-[#0f0a18]',
        'border-slate-800',
        expanded && !isConfigRepo && 'shadow-[0_0_30px_rgba(0,0,0,0.4)]',
      )}
    >
      {/* Header Row */}
      <div className="flex items-center gap-3 px-5 py-3.5">
        {/* Expand toggle */}
        {!isConfigRepo ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="shrink-0 text-slate-500 hover:text-white transition-colors"
          >
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        ) : (
          <div className="w-4 shrink-0" />
        )}

        {/* Repo name */}
        <span className="font-semibold text-white tracking-tight text-[15px]">{repo.name}</span>

        {/* Branch badge */}
        <span className="text-xs font-mono text-cyan-400 px-2 py-0.5 rounded bg-cyan-500/8 border border-cyan-500/15 shrink-0">
          {repo.branch}
        </span>

        {/* State indicator */}
        <span className={clsx('flex items-center gap-1 text-xs shrink-0', stateInfo.color)}>
          <StateIcon className="w-3 h-3" />
          {stateInfo.label}
        </span>

        {/* Dirty pulse */}
        {repo.state === 'dirty' && (
          <span className="w-2 h-2 rounded-full bg-pink-500 animate-pulse shadow-[0_0_8px_#ff0066] shrink-0" />
        )}

        {/* Mini stats */}
        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500 ml-auto shrink-0">
          <span className={clsx(repo.uncommitted > 0 && 'text-pink-400')}>
            {repo.uncommitted} change{repo.uncommitted !== 1 ? 's' : ''}
          </span>
          {repo.ahead > 0 && (
            <span className="text-cyan-400 flex items-center gap-0.5">
              <ArrowUp className="w-3 h-3" />{repo.ahead}
            </span>
          )}
          {repo.behind > 0 && (
            <span className="text-amber-400 flex items-center gap-0.5">
              <ArrowDown className="w-3 h-3" />{repo.behind}
            </span>
          )}
          {repo.ahead === 0 && repo.behind === 0 && (
            <span className="text-slate-600">in sync</span>
          )}
        </div>

        {/* Smart Sync button */}
        <button
            disabled={syncMutation.isPending}
            onClick={(e) => {
              e.stopPropagation()
              syncMutation.mutate()
            }}
            className={clsx(
              'shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              syncMutation.isPending
                ? 'bg-slate-800 text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-pink-600/80 to-purple-600/80 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/10 hover:shadow-pink-500/25',
            )}
          >
            {syncMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {syncMutation.isPending ? 'Syncing...' : 'Smart Sync'}
          </button>
      </div>

      {/* Sync result — always visible when present */}
      {syncMutation.data && (
        <div className="px-5 pb-3">
          <SyncResultBlock result={syncMutation.data} />
        </div>
      )}

      {/* Expanded Content */}
      {expanded && !isConfigRepo && (
        <div className="border-t border-slate-800/60 px-5 py-4">
          <DashboardContent projectId={repo.name} />
        </div>
      )}
    </div>
  )
}
