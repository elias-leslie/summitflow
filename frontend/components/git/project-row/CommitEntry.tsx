import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bot, Minus, Plus, User } from 'lucide-react'
import { useState } from 'react'
import { fetchCommitDiff, type CommitInfo } from '@/lib/api/git-enhanced'
import { DiffPanel } from '../DiffPanel'
import { formatTimeAgo } from '@/lib/format'
import { isAgentCommit } from './helpers'

export function CommitEntry({ commit, projectId }: { commit: CommitInfo; projectId: string }) {
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
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[11px] font-mono text-phosphor-500 shrink-0">{commit.short_sha}</span>
            <span className="text-sm text-slate-300 truncate">{commit.message}</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span>{commit.author_name}</span>
            <span>{formatTimeAgo(commit.date)}</span>
          </div>
        </div>
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
