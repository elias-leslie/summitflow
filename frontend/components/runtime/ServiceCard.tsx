'use client'

import { clsx } from 'clsx'
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

function MetricStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className="truncate text-xs text-slate-200" title={value}>
        {value}
      </div>
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

  const restartMut = useServiceAction(container.service, 'restart')
  const stopMut = useServiceAction(container.service, 'stop')
  const startMut = useServiceAction(container.service, 'start')

  return (
    <>
      <div
        className={clsx(
          'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 p-4 transition-colors hover:bg-slate-800/60',
          healthAccentClass(tone),
        )}
      >
        {/* Identity */}
        <div className="mb-2.5 flex items-center gap-2">
          <div className={clsx('w-2 h-2 rounded-full', healthDotClass(tone))} />
          <span className="font-medium text-white text-sm truncate flex-1">
            {container.display_name}
          </span>
          <span className={clsx('text-[11px] capitalize', tone === 'healthy' ? 'text-emerald-400' : tone === 'unhealthy' ? 'text-red-400' : 'text-slate-500')}>
            {healthLabel(container.state, container.health)}
          </span>
        </div>

        {/* Tags row */}
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          <span className="rounded bg-slate-700/70 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-300">
            {managerLabel(container.manager)}
          </span>
          {container.ports.map((p) => (
            <span
              key={p}
              className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-400"
            >
              :{p}
            </span>
          ))}
        </div>

        {/* Metrics */}
        {isRunning && (
          <div className="mb-3">
            {metric ? (
              <div className="grid grid-cols-3 gap-1.5">
                <MetricStat label="CPU" value={metric.cpu_percent} />
                <MetricStat label="Mem" value={metric.mem_usage} />
                <MetricStat label="Mem%" value={metric.mem_percent} />
              </div>
            ) : (
              <p className="text-[11px] text-slate-600">
                {metricsLoading ? 'Loading metrics...' : 'Metrics unavailable'}
              </p>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-1.5">
          {isRunning ? (
            <>
              <button
                onClick={() => restartMut.mutate()}
                disabled={restartMut.isPending}
                className="text-[11px] px-2 py-1 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
              >
                {restartMut.isPending ? '...' : 'Restart'}
              </button>
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className="text-[11px] px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                {stopMut.isPending ? '...' : 'Stop'}
              </button>
            </>
          ) : (
            <button
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
              className="text-[11px] px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors"
            >
              {startMut.isPending ? '...' : 'Start'}
            </button>
          )}
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="text-[11px] px-2 py-1 rounded bg-slate-700/60 text-slate-400 hover:bg-slate-700 hover:text-slate-300 transition-colors ml-auto"
          >
            Logs
          </button>
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
