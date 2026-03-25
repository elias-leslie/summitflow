'use client'

import { clsx } from 'clsx'
import { Play, RotateCcw, ScrollText, Square } from 'lucide-react'
import { useState } from 'react'
import type {
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from '@/lib/api/runtime'
import { LogViewer } from './LogViewer'
import {
  healthAccentClass,
  healthDotClass,
  healthLabel,
  managerLabel,
  resolveHealthTone,
} from './health-utils'
import { useServiceAction } from './useServiceAction'

function MetricStat({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-slate-800/60 bg-slate-950/70 px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500">
        {label}
      </div>
      <div
        className="mt-1 truncate font-mono text-sm tabular-nums text-slate-100"
        title={value}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-[10px] text-slate-500">{hint}</div> : null}
    </div>
  )
}

interface ServiceCardProps {
  container: RuntimeServiceStatus
  metric?: RuntimeServiceMetrics
  metricsLoading?: boolean
}

export function ServiceCard({
  container,
  metric,
  metricsLoading = false,
}: ServiceCardProps) {
  const [showLogs, setShowLogs] = useState(false)
  const tone = resolveHealthTone(container.state, container.health)
  const isRunning = container.state === 'running'
  const statusLabel = healthLabel(container.state, container.health)
  const categoryLabel =
    container.category === 'app'
      ? 'App service'
      : container.category === 'worker'
        ? 'Worker service'
        : 'Shared infra'
  const portsLabel =
    container.ports.length > 0 ? container.ports.map((port) => `:${port}`).join(' • ') : '—'

  const restartMut = useServiceAction(container.service, 'restart')
  const stopMut = useServiceAction(container.service, 'stop')
  const startMut = useServiceAction(container.service, 'start')

  const actionButtonClass =
    'inline-flex items-center justify-center gap-1.5 rounded-2xl border px-3 py-2 text-xs font-medium transition-all disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950'

  return (
    <>
      <div
        className={clsx(
          'card-elevated flex h-full flex-col gap-3 px-3 py-3 transition-colors',
          healthAccentClass(tone),
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-3">
            <div className="flex items-center gap-2">
              <div className={clsx('h-2.5 w-2.5 rounded-full', healthDotClass(tone))} />
              <span className="truncate text-base font-semibold text-slate-50">
                {container.display_name}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <span
                className={clsx(
                  'rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-[0.16em]',
                  tone === 'healthy'
                    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
                    : tone === 'unhealthy'
                      ? 'border-rose-500/20 bg-rose-500/10 text-rose-300'
                      : 'border-amber-500/20 bg-amber-500/10 text-amber-300',
                )}
              >
                {statusLabel}
              </span>
              <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                {managerLabel(container.manager)}
              </span>
              <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                {categoryLabel}
              </span>
            </div>
          </div>

          <button
            onClick={() => setShowLogs(!showLogs)}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-2xl border px-3 py-2 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950',
              showLogs
                ? 'border-phosphor-500/20 bg-phosphor-500/10 text-phosphor-300'
                : 'border-slate-700/70 bg-slate-950/70 text-slate-400 hover:border-slate-600 hover:text-slate-200',
            )}
          >
            <ScrollText className="h-3.5 w-3.5" />
            Logs
          </button>
        </div>

        <div className="rounded-lg border border-slate-800/60 bg-slate-950/45 p-2.5">
          <div className="flex items-center justify-between gap-2 mb-2">
            <code className="truncate font-mono text-[10px] text-slate-400">
              {container.service}
            </code>
          </div>

          <div className="grid gap-1.5 sm:grid-cols-2">
            <MetricStat
              label="CPU"
              value={metric?.cpu_percent ?? (metricsLoading ? '…' : '—')}
              hint={isRunning ? 'Live process load' : 'Inactive'}
            />
            <MetricStat
              label="Memory"
              value={metric?.mem_usage ?? (metricsLoading ? '…' : '—')}
              hint={metric?.mem_percent ? `${metric.mem_percent} used` : 'Memory allocation'}
            />
            <MetricStat
              label="Ports"
              value={portsLabel}
              hint="Advertised listeners"
            />
            <MetricStat
              label="Status"
              value={container.status || statusLabel}
              hint={isRunning ? 'Ready for actions' : 'Stopped or degraded'}
            />
          </div>
        </div>

        <div className="mt-auto flex flex-wrap gap-2">
          {isRunning ? (
            <>
              <button
                onClick={() => restartMut.mutate()}
                disabled={restartMut.isPending}
                className={clsx(
                  actionButtonClass,
                  'flex-1 border-amber-500/20 bg-amber-500/10 text-amber-300 hover:border-amber-500/30 hover:bg-amber-500/20 focus-visible:ring-amber-500/40',
                )}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {restartMut.isPending ? 'Working…' : 'Restart'}
              </button>
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className={clsx(
                  actionButtonClass,
                  'flex-1 border-rose-500/20 bg-rose-500/10 text-rose-300 hover:border-rose-500/30 hover:bg-rose-500/20 focus-visible:ring-rose-500/40',
                )}
              >
                <Square className="h-3.5 w-3.5" />
                {stopMut.isPending ? 'Working…' : 'Stop'}
              </button>
            </>
          ) : (
            <button
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
              className={clsx(
                actionButtonClass,
                'flex-1 border-emerald-500/20 bg-emerald-500/10 text-emerald-300 hover:border-emerald-500/30 hover:bg-emerald-500/20 focus-visible:ring-emerald-500/40',
              )}
            >
              <Play className="h-3.5 w-3.5" />
              {startMut.isPending ? 'Working…' : 'Start'}
            </button>
          )}
        </div>

      </div>

      {showLogs && (
        <LogViewer
          service={container.service}
          onClose={() => setShowLogs(false)}
        />
      )}
    </>
  )
}
