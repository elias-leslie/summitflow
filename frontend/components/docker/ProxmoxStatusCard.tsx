'use client'

import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { runtimeApi } from '@/lib/api/runtime'

function formatBytes(value: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return 'n/a'
  }
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let current = value
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return unitIndex === 0
    ? `${Math.round(current)}${units[unitIndex]}`
    : `${current.toFixed(1)}${units[unitIndex]}`
}

function formatUptime(seconds: number | null): string {
  if (seconds == null || seconds < 0) {
    return 'n/a'
  }
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  if (days > 0) {
    return `${days}d ${hours}h`
  }
  const minutes = Math.floor((seconds % 3_600) / 60)
  return `${hours}h ${minutes}m`
}

function statusTone(status: string): string {
  if (status === 'running' || status === 'online') {
    return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100'
  }
  if (status === 'stopped' || status === 'offline') {
    return 'border-slate-500/20 bg-slate-500/10 text-slate-200'
  }
  return 'border-amber-500/20 bg-amber-500/10 text-amber-100'
}

export function ProxmoxStatusCard() {
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'proxmox'],
    queryFn: runtimeApi.getProxmoxStatus,
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return <div className="h-48 animate-pulse rounded-lg bg-neutral-800/40" />
  }

  if (error || !data) {
    return (
      <Card className="border-red-500/30 bg-red-950/20">
        <CardHeader>
          <CardTitle className="text-base">Proxmox</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-200">
            {error instanceof Error
              ? error.message
              : 'Proxmox status is unavailable.'}
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-slate-700 bg-slate-900/70">
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle className="text-base">Proxmox</CardTitle>
          <p className="mt-1 text-sm text-slate-400">
            Read-only node and guest status from the Proxmox API.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.16em]">
          <span
            className={`rounded-full border px-3 py-1 ${
              data.configured
                ? 'border-sky-500/30 bg-sky-500/10 text-sky-100'
                : 'border-slate-500/30 bg-slate-500/10 text-slate-300'
            }`}
          >
            {data.configured ? 'configured' : 'not configured'}
          </span>
          <span
            className={`rounded-full border px-3 py-1 ${
              data.reachable
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                : 'border-amber-500/30 bg-amber-500/10 text-amber-100'
            }`}
          >
            {data.reachable ? 'reachable' : 'not reachable'}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-300">
          <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
            API Endpoint
          </div>
          <div className="mt-1 break-all">{data.api_url ?? 'Not configured'}</div>
          {data.error && (
            <div className="mt-2 text-sm text-amber-200">{data.error}</div>
          )}
        </div>

        {data.reachable && (
          <>
            <section className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
                  Nodes
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Cluster-level host status reported by Proxmox.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {data.nodes.map((node) => (
                  <div
                    key={node.node}
                    className={`rounded-lg border p-3 ${statusTone(node.status)}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{node.node}</div>
                      <span className="text-[11px] uppercase tracking-[0.16em]">
                        {node.status}
                      </span>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-200">
                      <div>CPU: {node.cpu_percent?.toFixed(1) ?? 'n/a'}%</div>
                      <div>
                        Memory: {formatBytes(node.memory_used_bytes)} /{' '}
                        {formatBytes(node.memory_total_bytes)}
                      </div>
                      <div>Uptime: {formatUptime(node.uptime_seconds)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
                  Guests
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  QEMU VMs and LXCs visible to the configured API token.
                </p>
              </div>
              {data.guests.length === 0 ? (
                <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-400">
                  No guests were reported by Proxmox.
                </div>
              ) : (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {data.guests.map((guest) => (
                    <div
                      key={`${guest.type}-${guest.vmid}`}
                      className={`rounded-lg border p-3 ${statusTone(guest.status)}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="font-medium">{guest.name}</div>
                          <div className="mt-1 text-xs text-slate-300">
                            {guest.node} • {guest.type} • VMID {guest.vmid}
                          </div>
                        </div>
                        <span className="text-[11px] uppercase tracking-[0.16em]">
                          {guest.status}
                        </span>
                      </div>
                      <div className="mt-3 grid gap-2 text-xs text-slate-200">
                        <div>CPU: {guest.cpu_percent?.toFixed(1) ?? 'n/a'}%</div>
                        <div>
                          Memory: {formatBytes(guest.memory_used_bytes)} /{' '}
                          {formatBytes(guest.memory_total_bytes)}
                        </div>
                        <div>Uptime: {formatUptime(guest.uptime_seconds)}</div>
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
      </CardContent>
    </Card>
  )
}
