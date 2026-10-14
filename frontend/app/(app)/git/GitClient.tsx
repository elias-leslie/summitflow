'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { RefreshCw, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  deriveSignals,
  type Filter,
  matchesFilter,
  STAGES,
} from '@/components/git/developmentSignals'
import { ProjectRow, ROW_GRID } from '@/components/git/ProjectRow'
import { SyncResults } from '@/components/git/RowDetails'
import { checkGitRemotes, fetchDevelopmentStatus } from '@/lib/api/git'
import { formatTimeAgo } from '@/lib/format'
import { POLL_SLOW, STALE_GIT } from '@/lib/polling'

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'attention', label: 'Needs a look' },
  { key: 'source', label: 'Uncommitted' },
  { key: 'accepted', label: 'Acceptance' },
  { key: 'running', label: 'Runtime' },
  { key: 'published', label: 'Publishing' },
  { key: 'backup', label: 'Backup' },
  { key: 'tasks', label: 'Tasks' },
]

export function GitClient() {
  const [filter, setFilter] = useState<Filter | null>(null)
  const [search, setSearch] = useState('')
  const query = useQuery({
    queryKey: ['development-status'],
    queryFn: fetchDevelopmentStatus,
    staleTime: STALE_GIT,
    refetchInterval: POLL_SLOW,
  })
  const remotes = useMutation({
    mutationFn: checkGitRemotes,
    onSuccess: () => query.refetch(),
  })

  const rows = useMemo(
    () =>
      (query.data?.repositories ?? [])
        .map((row) => ({
          ...row,
          signals: deriveSignals(row.repo, row.development),
        }))
        .sort(
          (a, b) =>
            b.signals.attention - a.signals.attention ||
            a.repo.name.localeCompare(b.repo.name),
        ),
    [query.data],
  )
  const counts = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map(({ key }) => [
          key,
          rows.filter((row) => matchesFilter(row.signals, key)).length,
        ]),
      ) as Record<Filter, number>,
    [rows],
  )
  const needle = search.trim().toLowerCase()
  const visible = rows.filter(
    (row) =>
      matchesFilter(row.signals, filter) &&
      (!needle || row.repo.name.toLowerCase().includes(needle)),
  )
  const firstClear = visible.findIndex((row) => row.signals.attention === 0)
  const remoteFailures = remotes.data && {
    ...remotes.data,
    results: remotes.data.results.filter(
      (row) => row.status === 'failed' || row.status === 'skipped',
    ),
  }

  return (
    <div className="mx-auto max-w-[1800px] space-y-3 px-4 py-4 md:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="display text-xl font-semibold text-slate-100">
            Development
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            {query.data
              ? `${rows.length} repositories · local evidence read ${formatTimeAgo(new Date(query.dataUpdatedAt).toISOString())}`
              : 'Working source, acceptance, runtime, publishing and backups per repository'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <span className="sr-only">Filter repositories by name</span>
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter"
              className="h-7 w-36 rounded border border-slate-800 bg-slate-900/60 pl-6 pr-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-phosphor-500/50 focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => remotes.mutate()}
            disabled={remotes.isPending}
            title="Fetch remote refs for every repository without merging"
            className="inline-flex h-7 items-center gap-1.5 rounded border border-cyan-500/20 bg-cyan-500/10 px-2.5 text-xs text-cyan-200 hover:border-cyan-400/40 hover:bg-cyan-500/15 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
          >
            <RefreshCw
              className={clsx('h-3 w-3', remotes.isPending && 'animate-spin')}
            />
            {remotes.isPending ? 'Checking remotes…' : 'Check remotes'}
          </button>
        </div>
      </header>

      {query.data && (
        <div
          role="group"
          aria-label="Filter by signal"
          className="flex flex-wrap gap-1.5"
        >
          <Chip active={filter === null} onClick={() => setFilter(null)}>
            All <Count>{rows.length}</Count>
          </Chip>
          {FILTERS.map(({ key, label }) => (
            <Chip
              key={key}
              active={filter === key}
              disabled={counts[key] === 0}
              onClick={() => setFilter(filter === key ? null : key)}
              tone={key === 'attention' ? 'warn' : undefined}
            >
              {label} <Count>{counts[key]}</Count>
            </Chip>
          ))}
        </div>
      )}

      <SyncResults result={remoteFailures || undefined} error={remotes.error} />

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
          className="card p-3 text-sm text-amber-300"
        >
          {repo.name}: {repo.reason}
        </p>
      ))}

      {rows.length > 0 && (
        <section aria-label="Repositories" className="space-y-1">
          <div
            aria-hidden="true"
            className={clsx(
              'hidden px-2 pb-1 pl-3 text-2xs font-medium uppercase tracking-[0.12em] text-slate-500',
              ROW_GRID,
            )}
          >
            <span className="pl-5.5">Repository</span>
            {STAGES.map((stage) => (
              <span key={stage.key}>{stage.label}</span>
            ))}
            <span />
          </div>
          {visible.map((row, index) => (
            <div key={row.repo.path}>
              {index === firstClear && index > 0 && (
                <p className="px-3 pb-1 pt-3 text-2xs uppercase tracking-[0.12em] text-slate-600">
                  Nothing pending
                </p>
              )}
              <ProjectRow repo={row.repo} development={row.development} />
            </div>
          ))}
          {visible.length === 0 && (
            <p className="px-3 py-6 text-center text-xs text-slate-500">
              No repositories match this filter
            </p>
          )}
        </section>
      )}
    </div>
  )
}

function Chip({
  active,
  disabled,
  tone,
  onClick,
  children,
}: {
  active: boolean
  disabled?: boolean
  tone?: 'warn'
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs transition-colors disabled:cursor-default disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400',
        active
          ? 'border-phosphor-400/50 bg-phosphor-500/15 text-phosphor-100'
          : tone === 'warn'
            ? 'border-amber-500/25 bg-amber-500/10 text-amber-200 hover:border-amber-400/50'
            : 'border-slate-800 bg-slate-900/50 text-slate-300 hover:border-slate-600',
      )}
    >
      {children}
    </button>
  )
}

function Count({ children }: { children: React.ReactNode }) {
  return <span className="font-mono tabular-nums opacity-70">{children}</span>
}
