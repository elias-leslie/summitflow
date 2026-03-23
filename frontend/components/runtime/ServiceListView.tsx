'use client'

import { clsx } from 'clsx'
import { useState } from 'react'
import type {
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from '@/lib/api/runtime'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LogViewer } from './LogViewer'
import {
  healthDotClass,
  healthLabel,
  managerLabel,
  resolveHealthTone,
} from './health-utils'
import { useServiceAction } from './useServiceAction'

function ActionCell({
  service,
  isRunning,
}: {
  service: string
  isRunning: boolean
}) {
  const restartMut = useServiceAction(service, 'restart')
  const stopMut = useServiceAction(service, 'stop')
  const startMut = useServiceAction(service, 'start')

  return (
    <div className="flex gap-1">
      {isRunning ? (
        <>
          <button
            onClick={() => restartMut.mutate()}
            disabled={restartMut.isPending}
            className="text-2xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
          >
            {restartMut.isPending ? '...' : 'Restart'}
          </button>
          <button
            onClick={() => stopMut.mutate()}
            disabled={stopMut.isPending}
            className="text-2xs px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
          >
            {stopMut.isPending ? '...' : 'Stop'}
          </button>
        </>
      ) : (
        <button
          onClick={() => startMut.mutate()}
          disabled={startMut.isPending}
          className="text-2xs px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors"
        >
          {startMut.isPending ? '...' : 'Start'}
        </button>
      )}
    </div>
  )
}

interface ServiceListViewProps {
  services: RuntimeServiceStatus[]
  metricsByService: Map<string, RuntimeServiceMetrics>
}

export function ServiceListView({
  services,
  metricsByService,
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
                      className={clsx('w-2 h-2 rounded-full', healthDotClass(tone))}
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
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <ActionCell service={s.service} isRunning={isRunning} />
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
          onClose={() => setLogService(null)}
        />
      )}
    </>
  )
}
