'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { useState } from 'react'
import {
  type DisruptionHandshake,
  type HostDisruption,
  runtimeApi,
} from '@/lib/api/runtime'
import { formatTimeAgo } from '@/lib/format'
import { POLL_NOTIFICATIONS } from '@/lib/polling'

type Verdict = 'clear' | 'blocked' | 'unknown'

function verdict(data: HostDisruption): Verdict {
  if (data.blocking.length > 0) return 'blocked'
  if (data.unknown.length > 0) return 'unknown'
  return 'clear'
}

function agentsLabel(count: number): string {
  if (count === 0) return 'no agents working'
  return `${count} ${count === 1 ? 'agent' : 'agents'} working`
}

function summary(data: HostDisruption): string {
  const agents = agentsLabel(data.agents.length)
  const kind = verdict(data)
  if (kind === 'clear') return `Nothing in the way · ${agents}`
  const reasons = kind === 'blocked' ? data.blocking : data.unknown
  const more = reasons.length > 1 ? ` (+${reasons.length - 1} more)` : ''
  const lead = kind === 'blocked' ? 'Not now' : "Can't tell"
  return `${lead}: ${reasons[0]}${more}`
}

function replyLabel(row: DisruptionHandshake): string {
  const who = row.acked_by ?? row.to
  if (row.reply === 'no')
    return `${who} said no${row.note ? `: ${row.note}` : ''}`
  if (row.reply === 'yes') return `${who} said yes`
  if (row.reply === 'eta' && row.eta_running && row.eta_until) {
    const until = new Date(row.eta_until).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
    return `${who} asked to wait until ${until}`
  }
  return `${who} hasn't answered yet`
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  )
}

export function HostDisruptionCard() {
  const [expanded, setExpanded] = useState(false)
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'disruption'],
    queryFn: runtimeApi.getHostDisruption,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  if (isLoading) {
    return <div className="h-12 animate-pulse rounded-lg bg-slate-800/40" />
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-4 py-3">
        <span className="text-sm font-medium text-slate-100">
          Restart or reboot
        </span>
        <span className="ml-3 text-sm text-red-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </span>
      </div>
    )
  }

  const kind = verdict(data)
  const backups = [
    ...data.backups.summitflow.map(
      (row) => `Backup ${row.source_id ?? row.id}`,
    ),
    ...data.backups.units,
    ...data.backups.processes,
  ]
  const editing = data.leases.reduce((total, row) => total + row.paths, 0)

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
      >
        <div
          className={clsx(
            'h-2 w-2 shrink-0 rounded-full',
            kind === 'blocked'
              ? 'bg-rose-500'
              : kind === 'unknown'
                ? 'bg-amber-400'
                : 'bg-emerald-500',
          )}
        />
        <span className="shrink-0 text-sm font-medium text-slate-100">
          Restart or reboot
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
          {summary(data)}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
          className={clsx(
            'shrink-0 text-slate-500 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        >
          <path
            d="M3 4.5L6 7.5L9 4.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {expanded && (
        <div className="grid gap-4 border-t border-slate-800/60 px-4 py-4 text-xs text-slate-300 md:grid-cols-2">
          {(data.blocking.length > 0 || data.unknown.length > 0) && (
            <Section title="In the way">
              <ul className="space-y-1">
                {data.blocking.map((line) => (
                  <li key={line} className="text-rose-200">
                    {line}
                  </li>
                ))}
                {data.unknown.map((line) => (
                  <li key={line} className="text-amber-200">
                    Couldn't check: {line}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Agents working">
            {data.agents.length === 0 ? (
              <p className="text-slate-500">None on {data.host}</p>
            ) : (
              <ul className="space-y-1">
                {data.agents.map((row) => (
                  <li key={row.agent} className="font-mono">
                    {row.agent}
                    {row.project && (
                      <span className="ml-2 font-sans text-slate-500">
                        {row.project}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Requests to agents">
            {data.handshakes.length === 0 ? (
              <p className="text-slate-500">No open requests</p>
            ) : (
              <ul className="space-y-1">
                {data.handshakes.map((row) => (
                  <li
                    key={row.id}
                    className={clsx(row.reply === 'no' && 'text-rose-200')}
                  >
                    {replyLabel(row)}
                    <span className="ml-2 text-slate-500">
                      asked {formatTimeAgo(row.created)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Repo holds and deploys">
            {data.holds.length === 0 ? (
              <p className="text-slate-500">None</p>
            ) : (
              <ul className="space-y-1">
                {data.holds.map((row) => (
                  <li key={`${row.project}-${row.holder}-${row.since}`}>
                    {row.project}:{' '}
                    {row.kind === 'op'
                      ? 'deploy running'
                      : `held for ${row.purpose ?? 'work'}`}{' '}
                    by <span className="font-mono">{row.holder}</span>
                  </li>
                ))}
              </ul>
            )}
            {editing > 0 && (
              <p className="text-slate-500">
                {editing} {editing === 1 ? 'file' : 'files'} being edited
              </p>
            )}
          </Section>

          <Section title="Backups running">
            {backups.length === 0 ? (
              <p className="text-slate-500">None</p>
            ) : (
              <ul className="space-y-1 break-all">
                {backups.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </Section>

          <p className="text-slate-500 md:col-span-2">
            Checked {formatTimeAgo(data.generated_at)}. Agents can also run{' '}
            <code className="font-mono text-slate-400">
              st sessions may-disrupt
            </code>
            .
          </p>
        </div>
      )}
    </div>
  )
}
