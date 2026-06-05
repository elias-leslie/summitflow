'use client'

import { clsx } from 'clsx'
import { useState } from 'react'
import type {
  RuntimeMetricSeries,
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from '@/lib/api/runtime'
import { AutostartToggle } from './AutostartToggle'
import {
  healthAccentClass,
  healthDotClass,
  healthLabel,
  managerLabel,
  resolveHealthTone,
} from './health-utils'
import { LogViewer } from './LogViewer'
import { ServiceMetricTimeline } from './ServiceMetricTimeline'
import { useServiceAction } from './useServiceAction'

function MetricStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-slate-950/60 px-2.5 py-1.5 border border-slate-800/50">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400 font-medium">
        {label}
      </div>
      <div
        className="truncate text-xs text-slate-200 font-mono tabular-nums mt-0.5"
        title={value}
      >
        {value}
      </div>
    </div>
  )
}

interface ServiceCardProps {
  container: RuntimeServiceStatus
  metric?: RuntimeServiceMetrics
  metricSeries?: RuntimeMetricSeries
  metricsLoading?: boolean
}

export function ServiceCard({
  container,
  metric,
  metricSeries,
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
          'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 p-4 transition-all duration-200 hover:bg-slate-800/60 hover:shadow-lg hover:shadow-black/20',
          healthAccentClass(tone),
        )}
      >
        {/* Identity */}
        <div className="mb-2.5 flex items-center gap-2">
          <div className={clsx('w-2 h-2 rounded-full', healthDotClass(tone))} />
          <span className="font-medium text-slate-100 text-sm truncate flex-1">
            {container.display_name}
          </span>
          <span
            className={clsx(
              'text-2xs capitalize',
              tone === 'healthy'
                ? 'text-emerald-400'
                : tone === 'unhealthy'
                  ? 'text-red-400'
                  : 'text-slate-500',
            )}
          >
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
              <p className="text-2xs text-slate-600">
                {metricsLoading ? 'Loading metrics...' : 'Metrics unavailable'}
              </p>
            )}
          </div>
        )}

        <div className="mb-3">
          <ServiceMetricTimeline
            service={container}
            latestMetric={metric}
            series={metricSeries}
          />
        </div>

        {/* Auto-start (boot) toggle — only for togglable systemd units */}
        {container.auto_start !== null && (
          <div className="mb-2.5 flex items-center justify-between rounded-md bg-slate-950/40 px-2.5 py-1.5 border border-slate-800/50">
            <AutostartToggle
              service={container.service}
              autoStart={container.auto_start}
            />
            <span className="text-[10px] text-slate-600">on reboot</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-1.5">
          {isRunning ? (
            <>
              <button
                onClick={() => restartMut.mutate()}
                disabled={restartMut.isPending}
                className="text-2xs px-2.5 py-1.5 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 hover:border-amber-500/30 disabled:opacity-40 transition-all font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-900"
              >
                {restartMut.isPending ? '...' : 'Restart'}
              </button>
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className="text-2xs px-2.5 py-1.5 rounded-md bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:border-red-500/30 disabled:opacity-40 transition-all font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-900"
              >
                {stopMut.isPending ? '...' : 'Stop'}
              </button>
            </>
          ) : (
            <button
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
              className="text-2xs px-2.5 py-1.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 hover:border-emerald-500/30 disabled:opacity-40 transition-all font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-900"
            >
              {startMut.isPending ? '...' : 'Start'}
            </button>
          )}
          <button
            onClick={() => setShowLogs(!showLogs)}
            className={clsx(
              'text-2xs px-2.5 py-1.5 rounded-md border transition-all font-medium ml-auto',
              showLogs
                ? 'bg-phosphor-500/10 text-phosphor-400 border-phosphor-500/20'
                : 'bg-slate-700/40 text-slate-400 border-slate-700/60 hover:bg-slate-700/60 hover:text-slate-300',
            )}
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
