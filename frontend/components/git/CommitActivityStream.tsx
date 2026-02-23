'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Bot,
  ChevronDown,
  ChevronRight,
  GitCommitHorizontal,
  Minus,
  Plus,
  User,
} from 'lucide-react'
import { useState } from 'react'
import {
  fetchRecentCommits,
  type CommitInfo,
} from '@/lib/api/git-enhanced'
import { DiffPanel } from './DiffPanel'

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
  return (
    commit.author_email.includes('noreply@anthropic') ||
    commit.message.includes('Co-Authored-By: Claude')
  )
}

function CommitEntry({ commit }: { commit: CommitInfo }) {
  const [diffOpen, setDiffOpen] = useState(false)
  const agent = isAgentCommit(commit)

  const { data: diffData } = useQuery({
    queryKey: ['commit-diff', commit.sha],
    queryFn: async () => {
      // Use task diff endpoint with parent..sha
      // For single commits we construct a minimal diff response
      const resp = await fetch(
        `/api/git/commits/${commit.sha}/diff`,
      )
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: false, // Only load on demand — clicking opens diff panel
    staleTime: 600000,
  })

  return (
    <>
      <button
        onClick={() => setDiffOpen(true)}
        className={clsx(
          'w-full flex items-start gap-3 p-3 rounded-lg text-left transition-all group',
          'hover:bg-slate-800/30 hover:border-phosphor-500/10',
        )}
      >
        {/* Timeline dot */}
        <div className="relative shrink-0 mt-0.5">
          <div
            className={clsx(
              'w-6 h-6 rounded-full flex items-center justify-center',
              agent
                ? 'bg-purple-500/15 border border-purple-500/30'
                : 'bg-slate-800 border border-slate-700',
            )}
          >
            {agent ? (
              <Bot className="w-3 h-3 text-purple-400" />
            ) : (
              <User className="w-3 h-3 text-slate-500" />
            )}
          </div>
          {/* Connecting line */}
          <div className="absolute top-7 left-1/2 -translate-x-1/2 w-px h-4 bg-slate-800 group-last:hidden" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-xs font-mono text-phosphor-500 shrink-0">
              {commit.short_sha}
            </span>
            <span className="text-sm text-slate-300 truncate">
              {commit.message}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-500">
            <span>{commit.author_name}</span>
            <span className="text-slate-700">/</span>
            <span className="font-mono px-1 py-0.5 rounded bg-slate-900/60 text-slate-500">
              {commit.repo_name}
            </span>
            <span>{relativeTime(commit.date)}</span>
          </div>
        </div>

        {/* Stats */}
        <div className="shrink-0 flex items-center gap-2 text-[10px] font-mono opacity-60 group-hover:opacity-100 transition-opacity">
          {commit.insertions > 0 && (
            <span className="text-emerald-400 flex items-center gap-0.5">
              <Plus className="w-2.5 h-2.5" />
              {commit.insertions}
            </span>
          )}
          {commit.deletions > 0 && (
            <span className="text-rose-400 flex items-center gap-0.5">
              <Minus className="w-2.5 h-2.5" />
              {commit.deletions}
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

export function CommitActivityStream() {
  const [expanded, setExpanded] = useState(true)

  const { data, isLoading } = useQuery({
    queryKey: ['recent-commits'],
    queryFn: () => fetchRecentCommits(50),
    staleTime: 30000,
    refetchInterval: 60000,
  })

  if (isLoading || !data || data.count === 0) return null

  return (
    <section className="animate-in fade-in slide-in-from-top-4 duration-500">
      {/* Section Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between mb-3 group"
      >
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <GitCommitHorizontal className="w-5 h-5 text-phosphor-500" />
            <div className="absolute inset-0 blur-md bg-phosphor-500/30" />
          </div>
          <h2 className="font-semibold text-white">
            Recent Activity
          </h2>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-phosphor-500/10 text-phosphor-400 border border-phosphor-500/20">
            {data.count}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-500 group-hover:text-slate-300 transition-colors">
          <span className="text-[10px] uppercase tracking-wider">
            {expanded ? 'Collapse' : 'Expand'}
          </span>
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/20 divide-y divide-slate-800/40">
          {data.commits.slice(0, 30).map((commit) => (
            <CommitEntry key={commit.sha} commit={commit} />
          ))}
        </div>
      )}
    </section>
  )
}
