'use client'

import { clsx } from 'clsx'
import { useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type {
  RuntimeActionResult,
  RuntimeMetricSeries,
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from '@/lib/api/runtime'
import { AutostartToggle } from './AutostartToggle'
import {
  healthDotClass,
  healthLabel,
  managerLabel,
  resolveHealthTone,
} from './health-utils'
import { LogViewer } from './LogViewer'
import { ServiceMetricTimeline } from './ServiceMetricTimeline'
import { useServiceAction } from './useServiceAction'

function ActionCell({
  service,
  isRunning,
  controllable,
  status,
}: {
  service: string
  isRunning: boolean
  controllable: boolean
  status: string
}) {
  const [note, setNote] = useState<RuntimeActionResult | null>(null)
  const restartMut = useServiceAction(service, 'restart', setNote)
  const stopMut = useServiceAction(service, 'stop', setNote)
  const startMut = useServiceAction(service, 'start', setNote)

  if (!controllable) {
    return <span className="text-2xs text-slate-500">{status}</span>
  }

  return (
    <div className="flex gap-1">
      {isRunning ? (
        <>
          <button
            onClick={() => restartMut.mutate()}
            disabled={restartMut.isPending}
            className="text-2xs px-2 py-1 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 hover:border-amber-500/30 disabled:opacity-40 transition-all font-medium"
          >
            {restartMut.isPending ? '...' : 'Restart'}
          </button>
          <button
            onClick={() => stopMut.mutate()}
            disabled={stopMut.isPending}
            className="text-2xs px-2 py-1 rounded-md bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:border-red-500/30 disabled:opacity-40 transition-all font-medium"
          >
            {stopMut.isPending ? '...' : 'Stop'}
          </button>
        </>
      ) : (
        <button
          onClick={() => startMut.mutate()}
          disabled={startMut.isPending}
          className="text-2xs px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 hover:border-emerald-500/30 disabled:opacity-40 transition-all font-medium"
        >
          {startMut.isPending ? '...' : 'Start'}
        </button>
      )}
      {note && (note.pending || !note.success) && (
        <span
          className={clsx(
            'text-2xs self-center',
            note.success ? 'text-amber-400' : 'text-red-400',
          )}
        >
          {note.message}
          {note.approve_url && (
            <>
              {' '}
              <a
                href={note.approve_url}
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                Approve
              </a>
            </>
          )}
        </span>
      )}
    </div>
  )
}

interface ServiceListViewProps {
  services: RuntimeServiceStatus[]
  metricsByService: Map<string, RuntimeServiceMetrics>
  metricSeriesByService: Map<string, RuntimeMetricSeries>
}

export function ServiceListView({
  services,
  metricsByService,
  metricSeriesByService,
}: ServiceListViewProps) {
  const [logService, setLogService] = useState<string | null>(null)

  return (
    <>
      <div className="rounded-lg border border-slate-700/60 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-slate-700/60 bg-slate-900/50">
              <TableHead className="w-8" />
              <TableHead>Service</TableHead>
              <TableHead className="hidden sm:table-cell">Type</TableHead>
              <TableHead className="hidden md:table-cell">Port</TableHead>
              <TableHead className="hidden lg:table-cell">CPU</TableHead>
              <TableHead className="hidden lg:table-cell">Memory</TableHead>
              <TableHead className="hidden xl:table-cell">Trend</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {services.map((s) => {
              const tone = resolveHealthTone(s.state, s.health)
              const metric = metricsByService.get(s.service)
              const isRunning = s.state === 'running'

              return (
                <TableRow
                  key={s.service}
                  className="border-slate-800/60 hover:bg-slate-800/30"
                >
                  <TableCell className="pr-0">
                    <div
                      className={clsx(
                        'w-2 h-2 rounded-full',
                        healthDotClass(tone),
                      )}
                      title={healthLabel(s.state, s.health)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm font-medium text-slate-100 truncate">
                        {s.display_name}
                      </span>
                      <span
                        className={clsx(
                          'text-[10px] capitalize shrink-0',
                          tone === 'healthy'
                            ? 'text-emerald-400'
                            : tone === 'unhealthy'
                              ? 'text-red-400'
                              : 'text-slate-500',
                        )}
                      >
                        {healthLabel(s.state, s.health)}
                      </span>
                    </div>
                    {s.location && (
                      <p className="text-xs text-slate-400">{s.location}</p>
                    )}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-xs text-slate-400">
                      {managerLabel(s.manager)}
                    </span>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <span className="text-xs text-slate-400">
                      {s.ports.join(', ') || '-'}
                    </span>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <span className="text-xs text-slate-300 font-mono">
                      {metric?.cpu_percent ?? '-'}
                    </span>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <span className="text-xs text-slate-300 font-mono">
                      {metric?.mem_usage ?? '-'}
                    </span>
                  </TableCell>
                  <TableCell className="hidden xl:table-cell w-48">
                    <ServiceMetricTimeline
                      service={s}
                      latestMetric={metric}
                      series={metricSeriesByService.get(s.service)}
                      compact
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <ActionCell
                        status={s.status}
                        service={s.service}
                        isRunning={isRunning}
                        controllable={s.controllable !== false}
                      />
                      <AutostartToggle
                        service={s.service}
                        autoStart={s.auto_start}
                        variant="chip"
                      />
                      <button
                        onClick={() => setLogService(s.service)}
                        className="text-2xs px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-400 hover:bg-slate-700 hover:text-slate-300 transition-colors"
                      >
                        Logs
                      </button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {logService && (
        <LogViewer
          service={logService}
          canStream={
            services.find((s) => s.service === logService)?.log_streaming !==
            false
          }
          onClose={() => setLogService(null)}
        />
      )}
    </>
  )
}
