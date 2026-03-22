import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Bot,
  ChevronRight,
  FileCode2,
  FileMinus2,
  FilePlus2,
  Loader2,
  Minus,
  Plus,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { fetchCommitDiff, type CommitInfo, type DiffFile } from '@/lib/api/git-enhanced'
import { formatTimeAgo } from '@/lib/format'
import { POLL_RARE } from '@/lib/polling'
import { StatBar } from './StatBar'

function FileStatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'added':
      return <FilePlus2 className="w-3 h-3 text-emerald-400" />
    case 'deleted':
      return <FileMinus2 className="w-3 h-3 text-rose-400" />
    default:
      return <FileCode2 className="w-3 h-3 text-amber-400" />
  }
}

function InlineDiff({ content }: { content: string }) {
  return (
    <div className="overflow-x-auto bg-black/40 border-t border-slate-800/30">
      <pre className="text-[11px] font-mono leading-[1.6] p-0">
        {content.split('\n').map((line, i) => {
          let lineClass = 'text-slate-500 px-3'
          if (line.startsWith('+') && !line.startsWith('+++')) {
            lineClass = 'text-emerald-400 bg-emerald-500/8 px-3'
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            lineClass = 'text-rose-400 bg-rose-500/8 px-3'
          } else if (line.startsWith('@@')) {
            lineClass = 'text-cyan-400/60 bg-cyan-500/5 px-3'
          } else if (line.startsWith('diff ')) {
            lineClass = 'text-slate-600 bg-slate-900/50 px-3 font-semibold'
          }
          return (
            <div key={i} className={clsx(lineClass, 'whitespace-pre')}>
              {line || ' '}
            </div>
          )
        })}
      </pre>
    </div>
  )
}

function FileRow({ file }: { file: DiffFile }) {
  const [showDiff, setShowDiff] = useState(false)
  const hasDiff = Boolean(file.diff_content)

  return (
    <div className="group/file">
      <button
        type="button"
        disabled={!hasDiff}
        onClick={() => setShowDiff(!showDiff)}
        className={clsx(
          'w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors',
          hasDiff
            ? 'hover:bg-slate-800/30 cursor-pointer'
            : 'cursor-default opacity-70',
        )}
      >
        {hasDiff && (
          <ChevronRight
            className={clsx(
              'w-2.5 h-2.5 text-slate-600 transition-transform duration-150 shrink-0',
              showDiff && 'rotate-90',
            )}
          />
        )}
        {!hasDiff && <span className="w-2.5" />}
        <FileStatusIcon status={file.status} />
        <span className="text-[11px] font-mono text-slate-400 truncate flex-1 min-w-0">
          {file.path}
        </span>
        <div className="flex items-center gap-1.5 shrink-0 text-[10px] font-mono opacity-50 group-hover/file:opacity-100 transition-opacity">
          {file.additions > 0 && (
            <span className="text-emerald-400 flex items-center gap-0.5">
              <Plus className="w-2 h-2" />{file.additions}
            </span>
          )}
          {file.deletions > 0 && (
            <span className="text-rose-400 flex items-center gap-0.5">
              <Minus className="w-2 h-2" />{file.deletions}
            </span>
          )}
        </div>
      </button>
      {showDiff && file.diff_content && (
        <div className="ml-[22px] mr-2 mb-1.5 rounded overflow-hidden border border-slate-800/40">
          <InlineDiff content={file.diff_content} />
        </div>
      )}
    </div>
  )
}

export function CommitEntry({ commit, projectId }: { commit: CommitInfo; projectId: string }) {
  const [expanded, setExpanded] = useState(false)
  const agent = commit.author_email.includes('anthropic.com')

  const { data: diffData, refetch, isFetching } = useQuery({
    queryKey: ['commit-diff', commit.sha],
    queryFn: () => fetchCommitDiff(commit.sha, projectId),
    enabled: false,
    staleTime: POLL_RARE * 2,
  })

  const files = diffData?.files ?? []

  function handleToggle() {
    if (!expanded && !diffData) refetch()
    setExpanded(!expanded)
  }

  return (
    <div
      className={clsx(
        'transition-colors duration-150',
        expanded && 'bg-slate-800/10',
      )}
    >
      {/* Commit header row */}
      <button
        type="button"
        onClick={handleToggle}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-slate-800/20 transition-colors group"
      >
        {/* Expand indicator */}
        <ChevronRight
          className={clsx(
            'w-3 h-3 text-slate-600 group-hover:text-slate-400 transition-all duration-200 shrink-0',
            expanded && 'rotate-90 text-phosphor-500/60',
          )}
        />

        {/* Author avatar */}
        <div
          className={clsx(
            'w-5 h-5 rounded-full flex items-center justify-center shrink-0',
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

        {/* Commit info */}
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

        {/* Stats cluster */}
        <div className="shrink-0 flex items-center gap-2 text-[10px] font-mono opacity-50 group-hover:opacity-100 transition-opacity">
          <StatBar additions={commit.insertions} deletions={commit.deletions} />
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

      {/* Inline file expansion */}
      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/20 ml-3 mr-1">
            {/* Left gutter line connecting files */}
            <div className="relative pl-3 border-l border-slate-800/40 ml-[7px]">
              {isFetching && files.length === 0 && (
                <div className="flex items-center gap-2 py-3 px-2 text-slate-500 text-[11px]">
                  <Loader2 className="w-3 h-3 animate-spin text-phosphor-500/60" />
                  Loading files...
                </div>
              )}
              {files.length > 0 && (
                <div className="py-1">
                  {files.map((file) => (
                    <FileRow key={file.path} file={file} />
                  ))}
                </div>
              )}
              {!isFetching && files.length === 0 && expanded && diffData && (
                <div className="py-3 px-2 text-[11px] text-slate-600">
                  No file changes found.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
