'use client'

import { Activity, Cpu, Maximize2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type {
  RuntimeMetricSample,
  RuntimeMetricSeries,
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from '@/lib/api/runtime'

interface ServiceMetricTimelineProps {
  service: RuntimeServiceStatus
  latestMetric?: RuntimeServiceMetrics
  series?: RuntimeMetricSeries
  compact?: boolean
}

function percent(value: number | null | undefined): string {
  return value == null ? '-' : `${value.toFixed(1)}%`
}

function bytes(value: number | null | undefined): string {
  if (value == null) return '-'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return unit === 0
    ? `${Math.round(size)}${units[unit]}`
    : `${size.toFixed(1)}${units[unit]}`
}

function timeLabel(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function numeric(values: Array<number | null | undefined>): number[] {
  return values.filter((value): value is number => typeof value === 'number')
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function maxValue(values: number[]): number | null {
  if (values.length === 0) return null
  return Math.max(...values)
}

function memoryPercent(
  sample: RuntimeMetricSample,
  maxBytes: number,
): number | null {
  if (sample.memory_percent != null) return sample.memory_percent
  if (sample.memory_used_bytes == null || maxBytes <= 0) return null
  return (sample.memory_used_bytes / maxBytes) * 100
}

function pathFor(
  values: Array<number | null>,
  max: number,
  width: number,
  height: number,
): string {
  const pad = 4
  const usableWidth = width - pad * 2
  const usableHeight = height - pad * 2
  const points = values
    .map((value, index) => {
      if (value == null) return null
      const x = pad + (index / Math.max(values.length - 1, 1)) * usableWidth
      const y = pad + (1 - Math.min(value, max) / max) * usableHeight
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .filter((point): point is string => point !== null)
  if (points.length < 2) return ''
  return `M ${points.join(' L ')}`
}

function MetricSvg({
  samples,
  detail = false,
}: {
  samples: RuntimeMetricSample[]
  detail?: boolean
}) {
  const width = detail ? 520 : 160
  const height = detail ? 180 : 54
  const memBytes = numeric(
    samples.map(
      (sample) => sample.memory_used_bytes_max ?? sample.memory_used_bytes,
    ),
  )
  const memMax = Math.max(...memBytes, 1)
  const cpuValues = samples.map((sample) => sample.cpu_percent)
  const memValues = samples.map((sample) => memoryPercent(sample, memMax))
  const maxScale = Math.max(100, ...numeric(cpuValues), ...numeric(memValues))
  const cpuPath = pathFor(cpuValues, maxScale, width, height)
  const memPath = pathFor(memValues, maxScale, width, height)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-full w-full overflow-visible"
      role="img"
      aria-label="CPU and memory timeline"
    >
      <line
        x1="4"
        y1={height - 4}
        x2={width - 4}
        y2={height - 4}
        stroke="rgb(51 65 85)"
        strokeWidth="1"
      />
      <line
        x1="4"
        y1="4"
        x2={width - 4}
        y2="4"
        stroke="rgb(30 41 59)"
        strokeWidth="1"
        strokeDasharray="3 4"
      />
      {memPath && (
        <path
          d={memPath}
          fill="none"
          stroke="rgb(34 211 238)"
          strokeWidth={detail ? 2.5 : 2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      {cpuPath && (
        <path
          d={cpuPath}
          fill="none"
          stroke="rgb(245 158 11)"
          strokeWidth={detail ? 2.5 : 2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  )
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-800 bg-slate-950/55 px-2.5 py-1.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div
        className="mt-0.5 truncate font-mono text-xs text-slate-200"
        title={value}
      >
        {value}
      </div>
    </div>
  )
}

function MetricModal({
  service,
  series,
  latestMetric,
  open,
  onOpenChange,
}: ServiceMetricTimelineProps & {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const samples = series?.samples ?? []
  const stats = useMemo(() => {
    const cpu = numeric(samples.map((sample) => sample.cpu_percent))
    const memPct = numeric(samples.map((sample) => sample.memory_percent))
    const memBytes = numeric(samples.map((sample) => sample.memory_used_bytes))
    return {
      cpuAvg: average(cpu),
      cpuMax: maxValue(
        numeric(
          samples.map((sample) => sample.cpu_percent_max ?? sample.cpu_percent),
        ),
      ),
      memPctAvg: average(memPct),
      memPctMax: maxValue(
        numeric(
          samples.map(
            (sample) => sample.memory_percent_max ?? sample.memory_percent,
          ),
        ),
      ),
      memAvg: average(memBytes),
      memMax: maxValue(
        numeric(
          samples.map(
            (sample) =>
              sample.memory_used_bytes_max ?? sample.memory_used_bytes,
          ),
        ),
      ),
    }
  }, [samples])
  const latest = samples.at(-1)
  const recent = samples.slice(-10).reverse()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(92vw,760px)] max-h-[86vh] overflow-hidden rounded-lg">
        <DialogHeader className="relative pr-12">
          <DialogTitle>{service.display_name}</DialogTitle>
          <DialogDescription>
            {service.manager} {service.category} resource history
          </DialogDescription>
          <DialogClose />
        </DialogHeader>
        <div className="space-y-4 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <MetricPill label="CPU avg" value={percent(stats.cpuAvg)} />
            <MetricPill label="CPU max" value={percent(stats.cpuMax)} />
            <MetricPill
              label="Mem avg"
              value={
                stats.memAvg == null
                  ? percent(stats.memPctAvg)
                  : bytes(stats.memAvg)
              }
            />
            <MetricPill
              label="Mem max"
              value={
                stats.memMax == null
                  ? percent(stats.memPctMax)
                  : bytes(stats.memMax)
              }
            />
          </div>

          <div className="h-48 rounded-md border border-slate-800 bg-slate-950/50 p-3">
            {samples.length > 1 ? (
              <MetricSvg samples={samples} detail />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                No history yet
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-sm bg-amber-500" />
              CPU
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-sm bg-cyan-400" />
              Memory
            </span>
            {latest && <span>Last sample {timeLabel(latest.sampled_at)}</span>}
            {latestMetric && <span>Live memory {latestMetric.mem_usage}</span>}
          </div>

          <div className="overflow-hidden rounded-md border border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/70 text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Time</th>
                  <th className="px-3 py-2 font-medium">State</th>
                  <th className="px-3 py-2 font-medium">CPU</th>
                  <th className="px-3 py-2 font-medium">Memory</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((sample) => (
                  <tr
                    key={sample.sampled_at}
                    className="border-t border-slate-800/70"
                  >
                    <td className="px-3 py-2 font-mono text-slate-300">
                      {timeLabel(sample.sampled_at)}
                    </td>
                    <td className="px-3 py-2 text-slate-400">
                      {sample.state ?? '-'}
                    </td>
                    <td className="px-3 py-2 font-mono text-amber-300">
                      {percent(sample.cpu_percent)}
                    </td>
                    <td className="px-3 py-2 font-mono text-cyan-200">
                      {sample.memory_used_bytes == null
                        ? percent(sample.memory_percent)
                        : bytes(sample.memory_used_bytes)}
                    </td>
                  </tr>
                ))}
                {recent.length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-6 text-center text-slate-500"
                    >
                      No samples
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function ServiceMetricTimeline({
  service,
  latestMetric,
  series,
  compact = false,
}: ServiceMetricTimelineProps) {
  const [open, setOpen] = useState(false)
  const samples = series?.samples ?? []
  const latest = samples.at(-1)
  const latestCpu = latest?.cpu_percent ?? null
  const latestMem =
    latest?.memory_used_bytes != null
      ? bytes(latest.memory_used_bytes)
      : percent(latest?.memory_percent)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group w-full rounded-md border border-slate-800/70 bg-slate-950/45 p-2 text-left transition-colors hover:border-slate-700 hover:bg-slate-900/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/40"
        aria-label={`Open ${service.display_name} resource timeline`}
        title="Open resource timeline"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            {compact ? (
              <Activity className="h-3.5 w-3.5 shrink-0 text-slate-500" />
            ) : (
              <Cpu className="h-3.5 w-3.5 shrink-0 text-amber-400" />
            )}
            <span className="truncate text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
              Trend
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-[11px] font-mono text-slate-300">
            <span className="text-amber-300">{percent(latestCpu)}</span>
            <span className="text-cyan-200">{latestMem}</span>
            <Maximize2 className="h-3 w-3 text-slate-600 transition-colors group-hover:text-slate-300" />
          </div>
        </div>
        <div className={compact ? 'mt-1 h-8' : 'mt-2 h-12'}>
          {samples.length > 1 ? (
            <MetricSvg samples={samples.slice(-90)} />
          ) : (
            <div className="flex h-full items-center text-xs text-slate-600">
              No history yet
            </div>
          )}
        </div>
      </button>

      <MetricModal
        service={service}
        latestMetric={latestMetric}
        series={series}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  )
}
