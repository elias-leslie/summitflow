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
    <div className="flex flex-wrap gap-1.5">
      {isRunning ? (
        <>
          <button
            onClick={() => restartMut.mutate()}
            disabled={restartMut.isPending}
            className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-amber-300 transition-all hover:border-amber-500/30 hover:bg-amber-500/20 disabled:opacity-40"
          >
            {restartMut.isPending ? '…' : 'Restart'}
          </button>
          <button
            onClick={() => stopMut.mutate()}
            disabled={stopMut.isPending}
            className="rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-rose-300 transition-all hover:border-rose-500/30 hover:bg-rose-500/20 disabled:opacity-40"
          >
            {stopMut.isPending ? '…' : 'Stop'}
          </button>
        </>
      ) : (
        <button
          onClick={() => startMut.mutate()}
          disabled={startMut.isPending}
          className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-emerald-300 transition-all hover:border-emerald-500/30 hover:bg-emerald-500/20 disabled:opacity-40"
        >
          {startMut.isPending ? '…' : 'Start'}
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
      <div className="overflow-hidden rounded-[1.8rem] border border-slate-700/60 bg-slate-950/40 shadow-[0_24px_80px_rgba(4,6,16,0.35)]">
        <Table>
          <TableHeader>
            <TableRow className="border-slate-700/60 bg-slate-950/70">
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
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="truncate text-sm font-medium text-slate-100">
                          {s.display_name}
                        </span>
                        <span
                          className={clsx(
                            'shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em]',
                            tone === 'healthy'
                              ? 'border-emerald-500/18 bg-emerald-500/10 text-emerald-300'
                              : tone === 'unhealthy'
                                ? 'border-rose-500/18 bg-rose-500/10 text-rose-300'
                                : 'border-amber-500/18 bg-amber-500/10 text-amber-300',
                          )}
                        >
                          {healthLabel(s.state, s.health)}
                        </span>
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
                        {s.service}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                        {managerLabel(s.manager)}
                      </span>
                      <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                        {s.category}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <span className="text-xs text-slate-400">
                      {s.ports.length > 0 ? s.ports.map((port) => `:${port}`).join(', ') : '—'}
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
                    <div className="flex flex-wrap items-center gap-1.5">
                      <ActionCell service={s.service} isRunning={isRunning} />
                      <button
                        onClick={() => setLogService(s.service)}
                        className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-200"
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
