'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { useState } from 'react'
import { runtimeApi } from '@/lib/api/runtime'
import { POLL_NOTIFICATIONS } from '@/lib/polling'
import { formatBytes, formatUptime } from './health-utils'

function statusTone(status: string): string {
  if (status === 'running' || status === 'online')
    return 'border-emerald-500/20 bg-emerald-500/5 text-emerald-100'
  if (status === 'stopped' || status === 'offline')
    return 'border-slate-600/40 bg-slate-800/30 text-slate-300'
  return 'border-amber-500/20 bg-amber-500/5 text-amber-100'
}

export function ProxmoxStatusCard() {
  const [expanded, setExpanded] = useState(false)
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'proxmox'],
    queryFn: runtimeApi.getProxmoxStatus,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  if (isLoading) {
    return <div className="h-12 animate-pulse rounded-lg bg-slate-800/40" />
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-4 py-3">
        <span className="text-sm font-medium text-slate-100">Proxmox</span>
        <span className="ml-3 text-sm text-red-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </span>
      </div>
    )
  }

  // Summary line
  const onlineNodes = data.nodes.filter((n) => n.status === 'online').length
  const runningGuests = data.guests.filter((g) => g.status === 'running').length
  const summaryParts: string[] = []
  if (data.nodes.length > 0)
    summaryParts.push(`${onlineNodes}/${data.nodes.length} nodes online`)
  if (data.guests.length > 0)
    summaryParts.push(`${runningGuests}/${data.guests.length} guests running`)
  const summary = summaryParts.join(', ') || (data.configured ? 'No nodes' : 'Not configured')

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50">
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30"
      >
        <div className={clsx(
          'w-2 h-2 rounded-full',
          data.reachable ? 'bg-emerald-500' : data.configured ? 'bg-amber-500' : 'bg-slate-600',
        )} />
        <span className="text-sm font-medium text-slate-100">Proxmox</span>
        <span className="text-xs text-slate-500 flex-1">{summary}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          className={clsx(
            'text-slate-500 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        >
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-slate-800/60 px-4 py-4 space-y-4">
          {/* API Endpoint */}
          <div className="text-xs text-slate-500">
            <span className="uppercase tracking-[0.14em]">Endpoint: </span>
            <span className="text-slate-400 break-all">{data.api_url ?? 'Not configured'}</span>
            {data.error && (
              <span className="ml-2 text-amber-300">{data.error}</span>
            )}
          </div>

          {data.reachable && (
            <>
              {/* Nodes */}
              {data.nodes.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Nodes
                  </h3>
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {data.nodes.map((node) => (
                      <div
                        key={node.node}
                        className={clsx('rounded-lg border p-3 text-sm', statusTone(node.status))}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{node.node}</span>
                          <span className="text-[10px] uppercase tracking-[0.14em]">
                            {node.status}
                          </span>
                        </div>
                        <div className="mt-2 grid gap-1 text-xs text-slate-300">
                          <div>CPU: {node.cpu_percent?.toFixed(1) ?? 'n/a'}%</div>
                          <div>
                            Mem: {formatBytes(node.memory_used_bytes)} /{' '}
                            {formatBytes(node.memory_total_bytes)}
                          </div>
                          <div>Up: {formatUptime(node.uptime_seconds)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Guests */}
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                  Guests
                </h3>
                {data.guests.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    No guests reported by Proxmox.
                  </p>
                ) : (
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {data.guests.map((guest) => (
                      <div
                        key={`${guest.type}-${guest.vmid}`}
                        className={clsx('rounded-lg border p-3 text-sm', statusTone(guest.status))}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <div className="font-medium">{guest.name}</div>
                            <div className="mt-0.5 text-2xs text-slate-400">
                              {guest.node} &middot; {guest.type} &middot; VMID{' '}
                              {guest.vmid}
                            </div>
                          </div>
                          <span className="text-[10px] uppercase tracking-[0.14em] shrink-0">
                            {guest.status}
                          </span>
                        </div>
                        <div className="mt-2 grid gap-1 text-xs text-slate-300">
                          <div>CPU: {guest.cpu_percent?.toFixed(1) ?? 'n/a'}%</div>
                          <div>
                            Mem: {formatBytes(guest.memory_used_bytes)} /{' '}
                            {formatBytes(guest.memory_total_bytes)}
                          </div>
                          <div>Up: {formatUptime(guest.uptime_seconds)}</div>
                          {guest.tags.length > 0 && (
                            <div>Tags: {guest.tags.join(', ')}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </div>
  )
}
