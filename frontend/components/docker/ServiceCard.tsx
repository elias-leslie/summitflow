'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { ContainerMetrics, ContainerStatus } from '@/lib/api/docker'
import { dockerApi } from '@/lib/api/docker'
import { LogViewer } from './LogViewer'

function statusColor(state: string, health: string): string {
  if (health === 'healthy') return 'bg-emerald-500'
  if (health === 'unhealthy') return 'bg-red-500'
  if (state === 'running') return 'bg-amber-500'
  if (state === 'exited') return 'bg-neutral-500'
  return 'bg-neutral-600'
}

function statusLabel(state: string, health: string): string {
  if (health) return health
  return state
}

function managerLabel(manager: ContainerStatus['manager']): string {
  return manager === 'systemd' ? 'native' : 'docker'
}

interface ServiceCardProps {
  container: ContainerStatus
  metric?: ContainerMetrics
  metricsLoading?: boolean
}

function MetricStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-neutral-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-neutral-500">
        {label}
      </div>
      <div className="truncate text-xs text-neutral-200" title={value}>
        {value}
      </div>
    </div>
  )
}

export function ServiceCard({
  container,
  metric,
  metricsLoading = false,
}: ServiceCardProps) {
  const [showLogs, setShowLogs] = useState(false)
  const queryClient = useQueryClient()

  const restartMut = useMutation({
    mutationFn: () => dockerApi.restart(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const stopMut = useMutation({
    mutationFn: () => dockerApi.stop(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const startMut = useMutation({
    mutationFn: () => dockerApi.start(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const isRunning = container.state === 'running'

  return (
    <>
      <div className="rounded-lg border border-neutral-700 bg-neutral-800/50 p-4 hover:border-neutral-600 transition-colors">
        {/* Header */}
        <div className="mb-3 flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${statusColor(container.state, container.health)}`}
          />
          <span className="font-medium text-white text-sm truncate">
            {container.display_name}
          </span>
          <span className="ml-auto text-xs text-neutral-500">
            {statusLabel(container.state, container.health)}
          </span>
        </div>

        <div className="mb-3 flex flex-wrap gap-1.5">
          <span className="rounded bg-slate-700/70 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-200">
            {managerLabel(container.manager)}
          </span>
          <span className="rounded bg-neutral-700 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-neutral-300">
            {container.category}
          </span>
          <span className="rounded bg-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-400">
            {container.service}
          </span>
        </div>

        {/* Ports */}
        {container.ports.length > 0 && (
          <div className="flex gap-1 mb-3 flex-wrap">
            {container.ports.map((p) => (
              <span
                key={p}
                className="text-xs px-1.5 py-0.5 rounded bg-neutral-700 text-neutral-300"
              >
                {p}
              </span>
            ))}
          </div>
        )}

        {/* Status line */}
        <p className="text-xs text-neutral-500 mb-3 truncate">
          {container.status}
        </p>

        {isRunning && (
          <div className="mb-3 rounded-lg border border-neutral-700/80 bg-neutral-900/60 p-2">
            {metric ? (
              <div className="grid grid-cols-3 gap-2">
                <MetricStat label="CPU" value={metric.cpu_percent} />
                <MetricStat label="Memory" value={metric.mem_usage} />
                <MetricStat label="Mem %" value={metric.mem_percent} />
              </div>
            ) : (
              <p className="text-xs text-neutral-500">
                {metricsLoading ? 'Loading metrics...' : 'Metrics unavailable'}
              </p>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          {isRunning ? (
            <>
              <button
                onClick={() => restartMut.mutate()}
                disabled={restartMut.isPending}
                className="text-xs px-2 py-1 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-50 transition-colors"
              >
                {restartMut.isPending ? '...' : 'Restart'}
              </button>
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-50 transition-colors"
              >
                {stopMut.isPending ? '...' : 'Stop'}
              </button>
            </>
          ) : (
            <button
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
              className="text-xs px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50 transition-colors"
            >
              {startMut.isPending ? '...' : 'Start'}
            </button>
          )}
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="text-xs px-2 py-1 rounded bg-neutral-700 text-neutral-300 hover:bg-neutral-600 transition-colors ml-auto"
          >
            Logs
          </button>
        </div>
      </div>

      {/* Log viewer modal */}
      {showLogs && (
        <LogViewer
          service={container.service}
          onClose={() => setShowLogs(false)}
        />
      )}
    </>
  )
}
