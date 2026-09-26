'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  type MonitorEnvelope,
  type MonitorItem,
  monitorApi,
} from '@/lib/api/monitor'
import { HostMonitorDiagnostics } from './HostMonitorDiagnostics'

const METRICS = [
  { value: 'cpu_busy_pct', label: 'CPU', unit: '%' },
  { value: 'memory_available_bytes', label: 'Available memory', unit: 'bytes' },
  { value: 'disk_free_bytes', label: 'Free disk', unit: 'bytes' },
  { value: 'disk_read_bytes', label: 'Disk read counter', unit: 'bytes' },
  { value: 'disk_write_bytes', label: 'Disk write counter', unit: 'bytes' },
  {
    value: 'disk_read_bytes_per_second',
    label: 'Disk read rate',
    unit: 'bytes/s',
  },
  {
    value: 'disk_write_bytes_per_second',
    label: 'Disk write rate',
    unit: 'bytes/s',
  },
  { value: 'net_rx_bytes', label: 'Network received counter', unit: 'bytes' },
  { value: 'net_tx_bytes', label: 'Network sent counter', unit: 'bytes' },
  {
    value: 'net_rx_bytes_per_second',
    label: 'Network receive rate',
    unit: 'bytes/s',
  },
  {
    value: 'net_tx_bytes_per_second',
    label: 'Network send rate',
    unit: 'bytes/s',
  },
  { value: 'cpu_some_avg10_pct', label: 'CPU pressure', unit: '%' },
  { value: 'memory_some_avg10_pct', label: 'Memory pressure', unit: '%' },
  { value: 'io_some_avg10_pct', label: 'I/O pressure', unit: '%' },
] as const
const SERVICE_METRICS = [
  { value: 'cpu_percent', label: 'Service CPU', unit: '%' },
  { value: 'memory_current_bytes', label: 'Service memory', unit: 'bytes' },
  {
    value: 'io_read_bytes_per_second',
    label: 'Service read rate',
    unit: 'bytes/s',
  },
  {
    value: 'io_write_bytes_per_second',
    label: 'Service write rate',
    unit: 'bytes/s',
  },
] as const
const control =
  'rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50'
const panel = 'rounded-lg border border-slate-700/60 bg-slate-900/45 p-4'

type RecordValue = Record<string, unknown>

function record(value: unknown): RecordValue | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as RecordValue)
    : null
}
function string(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}
function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
function when(value: unknown): string {
  const source = string(value)
  if (!source) return 'Time unavailable'
  const date = new Date(source)
  return Number.isNaN(date.getTime()) ? source : date.toLocaleString()
}
function bytes(value: number): string {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let amount = value
  let index = 0
  while (Math.abs(amount) >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(index ? 1 : 0)} ${units[index]}`
}
function format(value: unknown, unit?: string): string {
  const measured = number(value)
  if (measured === null) return 'Unavailable'
  if (unit === 'bytes') return bytes(measured)
  if (unit === 'bytes/s') return `${bytes(measured)}/s`
  if (unit === 'nanoseconds')
    return `${(measured / 1_000_000_000).toFixed(1)} s`
  return `${measured.toFixed(1)}${unit || ''}`
}
function errorText(errors: unknown[]): string | null {
  if (errors.length === 0) return null
  return errors
    .map((error) => {
      const data = record(error)
      return (
        string(data?.message) ||
        [string(data?.source), string(data?.code)].filter(Boolean).join(': ') ||
        'Source error'
      )
    })
    .slice(0, 3)
    .join(' · ')
}
function latestItem(data?: MonitorEnvelope<MonitorItem>): MonitorItem | null {
  return data?.items.at(-1) || null
}
function measuredAt(item: MonitorItem): string | null {
  return (
    string(item.measured_at) ||
    string(item.sampled_at) ||
    string(item.timestamp)
  )
}
function freshness(item: MonitorItem | null, generatedAt?: string): string {
  if (!item) return 'No samples'
  if (item.availability && item.availability !== 'ok')
    return item.availability.replaceAll('_', ' ')
  const measured = measuredAt(item)
  if (!measured) return 'Sample time unavailable'
  const age = Date.now() - new Date(measured).getTime()
  if (!Number.isFinite(age)) return `Measured ${when(measured)}`
  if (age > 30_000) return `Stale · measured ${when(measured)}`
  return `Measured ${when(measured)}${generatedAt ? ` · response ${when(generatedAt)}` : ''}`
}
function host(item: MonitorItem | null): RecordValue {
  return record(item?.host) || record(item?.value) || item || {}
}
function services(
  item: MonitorItem | null,
): Array<{ id: string; data: RecordValue }> {
  const source = item?.services
  if (Array.isArray(source))
    return source.flatMap((value, index) => {
      const data = record(value)
      return data
        ? [
            {
              id:
                string(data.name) ||
                string(data.service) ||
                `Service ${index + 1}`,
              data,
            },
          ]
        : []
    })
  const keyed = record(source)
  return keyed
    ? Object.entries(keyed).flatMap(([id, value]) => {
        if (id === 'backend_health') return []
        const data = record(value)
        return data ? [{ id, data }] : []
      })
    : []
}
function processSortValue(item: MonitorItem, sort: string): string {
  if (item.sort_availability !== 'ok') return 'Unavailable'
  const value = number(item.sort_value)
  if (value === null) return 'Unavailable'
  if (sort === 'cpu') return format(value, '%')
  if (sort === 'io') return `${bytes(value)}/s`
  return bytes(value)
}
function sampleValue(item: MonitorItem, metric: string): number | null {
  return (
    number(item.value) ??
    number(record(item.value)?.last) ??
    number(item[metric]) ??
    number(record(item.host)?.[metric])
  )
}
function Timeline({
  items,
  metric,
  unit,
  onSelect,
  selectedAt,
}: {
  items: MonitorItem[]
  metric: string
  unit: string
  onSelect: (value: string) => void
  selectedAt: string | null
}) {
  const points = items.map((item) => ({
    item,
    at: measuredAt(item),
    value: sampleValue(item, metric),
  }))
  const numeric = points.filter((point) => point.value !== null)
  const max = Math.max(1, ...numeric.map((point) => point.value || 0))
  const segments: string[][] = []
  let current: string[] = []
  points.forEach((point, index) => {
    if (point.value === null) {
      if (current.length) segments.push(current)
      current = []
      return
    }
    const x = 8 + (index / Math.max(points.length - 1, 1)) * 684
    const y = 112 - ((point.value || 0) / max) * 100
    current.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  })
  if (current.length) segments.push(current)
  return (
    <div className="space-y-2">
      <div className="h-32 rounded-md border border-slate-800 bg-slate-950/50 p-2">
        {numeric.length ? (
          <svg
            role="img"
            aria-label={`${metric} history; gaps are not connected`}
            viewBox="0 0 700 120"
            className="h-full w-full"
            preserveAspectRatio="none"
          >
            <line x1="8" y1="112" x2="692" y2="112" stroke="#334155" />
            {segments.map((segment, index) =>
              segment.length > 1 ? (
                <polyline
                  key={index}
                  points={segment.join(' ')}
                  fill="none"
                  stroke="#22d3ee"
                  strokeWidth="2"
                  vectorEffect="non-scaling-stroke"
                />
              ) : (
                <circle
                  key={index}
                  cx={segment[0].split(',')[0]}
                  cy={segment[0].split(',')[1]}
                  r="2"
                  fill="#22d3ee"
                />
              ),
            )}
          </svg>
        ) : (
          <p className="p-4 text-sm text-slate-400">
            No measured values in this window.
          </p>
        )}
      </div>
      <div
        className="flex gap-1 overflow-x-auto pb-1"
        aria-label="Timeline samples"
      >
        {points.map(
          (point, index) =>
            point.at && (
              <button
                key={`${point.at}-${index}`}
                type="button"
                onClick={() => onSelect(point.at!)}
                aria-pressed={selectedAt === point.at}
                title={`${when(point.at)}: ${format(point.value, unit)} · ${point.item.availability || 'availability unavailable'}`}
                className={`h-5 min-w-2 flex-1 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${selectedAt === point.at ? 'bg-cyan-300' : point.value === null ? 'bg-slate-700' : number(record(point.item.coverage)?.missing) ? 'bg-amber-600 hover:bg-amber-500' : 'bg-cyan-700 hover:bg-cyan-500'}`}
              >
                <span className="sr-only">
                  Inspect {when(point.at)}, {format(point.value, unit)},{' '}
                  {point.item.availability || 'availability unavailable'}
                </span>
              </button>
            ),
        )}
      </div>
      <div className="flex justify-between gap-3 text-xs text-slate-500">
        <span>{when(points[0]?.at)}</span>
        <span>{when(points.at(-1)?.at)}</span>
      </div>
    </div>
  )
}

export function HostMonitor() {
  const queryClient = useQueryClient()
  const [metric, setMetric] = useState<string>('cpu_busy_pct')
  const [minutes, setMinutes] = useState(15)
  const [sort, setSort] = useState('cpu')
  const [selectedAt, setSelectedAt] = useState<string | null>(null)
  const [selectedService, setSelectedService] = useState<string | null>(null)
  const [selectedProcess, setSelectedProcess] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null)
  const [processPage, setProcessPage] = useState<{
    key: string
    cursor: string | null
    history: Array<string | null>
  }>({ key: '', cursor: null, history: [] })
  const nowBucket = Math.floor(Date.now() / 30_000)
  const until = new Date((nowBucket + 1) * 30_000).toISOString()
  const since = new Date(
    new Date(until).getTime() - minutes * 60_000,
  ).toISOString()
  const status = useQuery({
    queryKey: ['monitor', 'status'],
    queryFn: monitorApi.status,
    refetchInterval: 15_000,
  })
  const series = useQuery({
    queryKey: [
      'monitor',
      'series',
      metric,
      selectedService,
      minutes,
      nowBucket,
    ],
    queryFn: () =>
      monitorApi.series({
        metric,
        entity: selectedService || 'host',
        since,
        until,
        step: minutes === 15 ? 15 : 60,
        limit: 80,
      }),
    staleTime: 20_000,
  })
  const selectedSampleAt = selectedAt
    ? string(
        series.data?.items.find((item) => measuredAt(item) === selectedAt)
          ?.last_sampled_at,
      ) || (selectedEvent ? selectedAt : null)
    : null
  const processPageKey = `${selectedSampleAt || 'latest'}:${sort}:${selectedService || 'host'}`
  const activeProcessPage =
    processPage.key === processPageKey
      ? processPage
      : { key: processPageKey, cursor: null, history: [] }
  useEffect(() => {
    setProcessPage({ key: processPageKey, cursor: null, history: [] })
  }, [processPageKey])
  const processes = useQuery({
    queryKey: [
      'monitor',
      'processes',
      selectedSampleAt,
      sort,
      selectedService,
      activeProcessPage.cursor,
    ],
    queryFn: () =>
      monitorApi.processes({
        at: selectedSampleAt || undefined,
        sort,
        service: selectedService || undefined,
        limit: 50,
        cursor: activeProcessPage.cursor || undefined,
      }),
    enabled: !selectedAt || Boolean(selectedSampleAt),
    refetchInterval: selectedAt ? false : 15_000,
  })
  const events = useQuery({
    queryKey: ['monitor', 'events', minutes, nowBucket],
    queryFn: () => monitorApi.events({ since, limit: 50 }),
    staleTime: 20_000,
  })
  const capture = useMutation({
    mutationFn: monitorApi.capture,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monitor'] })
    },
  })
  const latest = latestItem(status.data)
  const hostData = host(latest)
  const memoryTotal = number(hostData.memory_total_bytes)
  const memoryAvailable = number(hostData.memory_available_bytes)
  const memoryUsed =
    memoryTotal !== null && memoryAvailable !== null
      ? Math.max(0, memoryTotal - memoryAvailable)
      : null
  const metricOptions: ReadonlyArray<{
    value: string
    label: string
    unit: string
  }> = selectedService ? SERVICE_METRICS : METRICS
  const metricInfo =
    metricOptions.find((option) => option.value === metric) || metricOptions[0]
  const selectedBucket = series.data?.items.find(
    (item) => measuredAt(item) === selectedAt,
  )
  const serviceList = useMemo(() => services(latest), [latest])
  const service = serviceList.find((entry) => entry.id === selectedService)
  const processItems = processes.data?.items || []
  const eventItems = events.data?.items || []
  const filteredProcesses = processItems
  const filteredEvents = selectedService
    ? eventItems.filter(
        (item) =>
          string(item.entity) === selectedService ||
          string(item.service) === selectedService,
      )
    : eventItems
  const process = filteredProcesses.find(
    (item) =>
      `${record(item.identity)?.pid}:${record(item.identity)?.start_ticks}` ===
      selectedProcess,
  )
  const event = filteredEvents.find(
    (item, index) => `${item.id ?? index}` === selectedEvent,
  )
  return (
    <section aria-label="Host monitor" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="display text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
            Host monitor
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Host history, managed services, process leaders and source events.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={control}
            onClick={() =>
              queryClient.invalidateQueries({ queryKey: ['monitor'] })
            }
          >
            <RefreshCw className="mr-1 inline h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            type="button"
            className={`${control} border-cyan-700 text-cyan-300`}
            disabled={capture.isPending}
            onClick={() => capture.mutate()}
          >
            {capture.isPending ? 'Starting capture…' : 'Start detail capture'}
          </button>
        </div>
      </div>
      {capture.isSuccess && (
        <p role="status" className="text-sm text-emerald-300">
          Detail capture requested. The 30-second lease ends automatically.
        </p>
      )}
      {capture.error && (
        <p role="alert" className="text-sm text-rose-300">
          {capture.error.message}
        </p>
      )}
      {status.isLoading ? (
        <p className={panel}>Loading host status…</p>
      ) : status.error ? (
        <p role="alert" className={`${panel} text-rose-300`}>
          {status.error.message}
        </p>
      ) : (
        <div className={panel}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold text-slate-100">Host now</h3>
            <span className="text-xs text-slate-400">
              {freshness(latest, status.data?.generated_at)}
            </span>
          </div>
          {latest ? (
            <>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                {(
                  [
                    ['CPU', 'cpu_pct', '%'],
                    ['Memory used', 'memory_used_bytes', 'bytes'],
                    ['Memory total', 'memory_total_bytes', 'bytes'],
                    ['CPU pressure', 'cpu_some_avg10_pct', '%'],
                    ['Memory pressure', 'memory_some_avg10_pct', '%'],
                    ['I/O pressure', 'io_some_avg10_pct', '%'],
                  ] as const
                ).map(([label, key, unit]) => (
                  <div
                    key={key}
                    className="rounded-md border border-slate-800 bg-slate-950/50 p-2"
                  >
                    <div className="text-xs text-slate-400">{label}</div>
                    <div className="mt-1 font-mono text-sm text-slate-100">
                      {format(
                        key === 'memory_used_bytes'
                          ? memoryUsed
                          : (hostData[key] ??
                              (key === 'cpu_pct'
                                ? hostData.cpu_busy_pct
                                : null)),
                        unit,
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {latest.mode || 'Mode unavailable'} ·{' '}
                {latest.source || latest.provider || 'Source unavailable'} ·{' '}
                {latest.availability || 'Availability unavailable'}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {number(status.data?.coverage.processes_seen) ?? 'Unknown'}{' '}
                processes seen ·{' '}
                {number(status.data?.coverage.processes_permission_denied) ??
                  'Unknown'}{' '}
                process stat reads denied ·{' '}
                {number(status.data?.coverage.process_io_permission_denied) ??
                  'Unknown'}{' '}
                process I/O reads denied
              </p>
            </>
          ) : (
            <p className="mt-3 text-sm text-slate-400">
              No host sample is available.
            </p>
          )}
          {status.data &&
            (status.data.truncated || status.data.errors.length > 0) && (
              <p className="mt-2 text-xs text-amber-300">
                Partial status
                {status.data.truncated ? ' · response truncated' : ''}
                {errorText(status.data.errors)
                  ? ` · ${errorText(status.data.errors)}`
                  : ''}
              </p>
            )}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <div className={`${panel} min-w-0 space-y-3`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold text-slate-100">
              {selectedService ? `${selectedService} history` : 'Host history'}
            </h3>
            <div className="flex flex-wrap gap-2">
              <label className="text-xs text-slate-400">
                Metric{' '}
                <select
                  className={`${control} ml-1`}
                  value={metric}
                  onChange={(e) => {
                    setMetric(e.target.value)
                    setSelectedAt(null)
                  }}
                >
                  {metricOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-slate-400">
                Window{' '}
                <select
                  className={`${control} ml-1`}
                  value={minutes}
                  onChange={(e) => {
                    setMinutes(Number(e.target.value))
                    setSelectedAt(null)
                  }}
                >
                  <option value={15}>15 minutes</option>
                  <option value={60}>1 hour</option>
                </select>
              </label>
            </div>
          </div>
          {series.isLoading ? (
            <p className="text-sm text-slate-400">Loading history…</p>
          ) : series.error ? (
            <p role="alert" className="text-sm text-rose-300">
              {series.error.message}
            </p>
          ) : series.data?.items.length ? (
            <Timeline
              items={series.data.items}
              metric={metric}
              unit={metricInfo.unit}
              selectedAt={selectedAt}
              onSelect={(at) => {
                setSelectedAt(at)
                setSelectedEvent(null)
              }}
            />
          ) : (
            <p className="text-sm text-slate-400">No history in this window.</p>
          )}
          {selectedBucket && (
            <div className="rounded-md border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-400">
              <h4 className="font-medium text-slate-200">
                {metricInfo.label} · {when(measuredAt(selectedBucket))}
              </h4>
              <p className="mt-1">
                Last{' '}
                {format(record(selectedBucket.value)?.last, metricInfo.unit)} ·
                Mean{' '}
                {format(record(selectedBucket.value)?.mean, metricInfo.unit)} ·
                Min {format(record(selectedBucket.value)?.min, metricInfo.unit)}{' '}
                · Max{' '}
                {format(record(selectedBucket.value)?.max, metricInfo.unit)}
              </p>
              <p className="mt-1">
                {string(selectedBucket.availability) ||
                  'Availability unavailable'}{' '}
                · {number(record(selectedBucket.coverage)?.valid) ?? 'Unknown'}{' '}
                valid /{' '}
                {number(record(selectedBucket.coverage)?.expected) ?? 'unknown'}{' '}
                expected ·{' '}
                {number(record(selectedBucket.coverage)?.missing) ?? 'Unknown'}{' '}
                missing
              </p>
              <p className="mt-1">
                {string(selectedBucket.source) || 'Source unavailable'} ·{' '}
                {string(selectedBucket.mode) || 'Mode unavailable'}
              </p>
            </div>
          )}
          {series.data && (
            <p className="text-xs text-slate-500">
              {series.data.items.length} samples ·{' '}
              {series.data.truncated ? 'Result truncated · ' : ''}
              {errorText(series.data.errors) ||
                'Gaps and unavailable readings are not interpolated.'}
            </p>
          )}
          {selectedAt && (
            <button
              type="button"
              className="text-sm text-cyan-300 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              onClick={() => setSelectedAt(null)}
            >
              Return to latest processes
            </button>
          )}
        </div>
        <div className={`${panel} min-w-0`}>
          <h3 className="font-semibold text-slate-100">Managed services</h3>
          {serviceList.length ? (
            <div className="mt-3 max-h-72 space-y-1 overflow-y-auto">
              {serviceList.map(({ id, data }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    const next = selectedService === id ? null : id
                    setSelectedService(next)
                    setMetric(next ? 'cpu_percent' : 'cpu_busy_pct')
                    setSelectedAt(null)
                    setSelectedProcess(null)
                    setSelectedEvent(null)
                  }}
                  aria-pressed={selectedService === id}
                  className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${selectedService === id ? 'bg-cyan-900/40 text-cyan-200' : 'text-slate-300 hover:bg-slate-800'}`}
                >
                  <span className="truncate">{id}</span>
                  <span className="text-xs text-slate-400">
                    {string(data.active_state) ||
                      string(data.state) ||
                      string(data.status) ||
                      'Unknown'}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">
              Service observations are unavailable.
            </p>
          )}
          {service && (
            <div className="mt-3 border-t border-slate-800 pt-3 text-xs text-slate-400">
              <strong className="text-slate-200">{service.id}</strong>
              <p className="mt-1">
                CPU counter{' '}
                {format(record(service.data.metrics)?.cpu_usage_usec, ' µs')} ·
                Memory{' '}
                {format(
                  record(service.data.metrics)?.memory_current_bytes ??
                    service.data.memory_bytes ??
                    service.data.memory_current_bytes,
                  'bytes',
                )}
              </p>
              <p className="mt-1">
                {string(record(service.data.metrics)?.source) ||
                  string(service.data.source) ||
                  'Source unavailable'}{' '}
                ·{' '}
                {string(service.data.availability) ||
                  'Availability unavailable'}
              </p>
            </div>
          )}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className={`${panel} min-w-0`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold text-slate-100">
              Processes{' '}
              {selectedAt
                ? `at ${when(selectedSampleAt || selectedAt)}`
                : 'latest'}
            </h3>
            <label className="text-xs text-slate-400">
              Sort{' '}
              <select
                className={`${control} ml-1`}
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                <option value="cpu">CPU</option>
                <option value="rss">Memory</option>
                <option value="io">I/O</option>
              </select>
            </label>
          </div>
          {processes.isLoading ? (
            <p className="mt-3 text-sm text-slate-400">Loading processes…</p>
          ) : processes.error ? (
            <p role="alert" className="mt-3 text-sm text-rose-300">
              {processes.error.message}
            </p>
          ) : (
            <>
              <p className="mt-2 text-xs text-slate-500">
                {processes.data?.coverage.availability === 'leaders_only' ||
                processItems[0]?.mode === 'baseline' ||
                processItems[0]?.availability === 'leaders_only'
                  ? 'Baseline includes metric leaders only. Start detail capture for all visible processes.'
                  : 'Visible processes in the selected sample.'}
              </p>
              <div className="mt-2 max-h-72 overflow-auto">
                <table className="w-full min-w-[420px] text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1">Process</th>
                      <th>PID</th>
                      <th>State</th>
                      <th>
                        {sort === 'cpu' ? 'CPU' : sort === 'io' ? 'I/O' : 'RSS'}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredProcesses.map((item, index) => (
                      <tr
                        key={`${record(item.identity)?.boot_id}-${record(item.identity)?.pid}-${record(item.identity)?.start_ticks}-${index}`}
                      >
                        <td className="border-t border-slate-800 py-1.5 pr-2">
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedProcess(
                                `${record(item.identity)?.pid}:${record(item.identity)?.start_ticks}`,
                              )
                            }
                            className="block max-w-[15rem] truncate text-left text-cyan-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                          >
                            {string(record(item.process)?.name) || 'Unknown'}
                          </button>
                        </td>
                        <td className="border-t border-slate-800 py-1.5 text-slate-300">
                          {number(record(item.identity)?.pid) ?? '—'}
                        </td>
                        <td className="border-t border-slate-800 py-1.5 text-slate-300">
                          {string(record(item.process)?.state) || 'Unknown'}
                        </td>
                        <td className="border-t border-slate-800 py-1.5 text-slate-300">
                          {processSortValue(item, sort)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredProcesses.length === 0 && (
                <p className="mt-3 text-sm text-slate-400">
                  {processes.data?.coverage.availability === 'unsupported'
                    ? 'Service attribution is unavailable in this process sample.'
                    : processes.data?.coverage.availability === 'not_collected'
                      ? 'No process observation is available at this time.'
                      : processes.data?.coverage.availability ===
                          'retention_expired'
                        ? 'This process sample is outside retained history.'
                        : selectedService
                          ? 'No processes linked to this service in the sample.'
                          : 'No process rows in this sample.'}
                </p>
              )}
              {processes.data && (
                <p className="mt-2 text-xs text-slate-500">
                  {processes.data.truncated ? 'Result truncated · ' : ''}
                  {errorText(processes.data.errors) ||
                    `${processItems.length} returned`}
                </p>
              )}
              {(activeProcessPage.history.length > 0 ||
                processes.data?.next_cursor) && (
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    className={control}
                    disabled={activeProcessPage.history.length === 0}
                    onClick={() =>
                      setProcessPage((current) => ({
                        key: processPageKey,
                        cursor: current.history.at(-1) || null,
                        history: current.history.slice(0, -1),
                      }))
                    }
                  >
                    Previous processes
                  </button>
                  <button
                    type="button"
                    className={control}
                    disabled={!processes.data?.next_cursor}
                    onClick={() => {
                      const next = processes.data?.next_cursor
                      if (next)
                        setProcessPage({
                          key: processPageKey,
                          cursor: next,
                          history: [
                            ...activeProcessPage.history,
                            activeProcessPage.cursor,
                          ],
                        })
                    }}
                  >
                    Next processes
                  </button>
                </div>
              )}
            </>
          )}
          {process && (
            <div className="mt-3 border-t border-slate-800 pt-2 text-xs text-slate-400">
              <strong className="text-slate-200">
                {string(record(process.process)?.name) || 'Process'} · PID{' '}
                {number(record(process.identity)?.pid)}
              </strong>
              <p>
                Start ticks{' '}
                {number(record(process.identity)?.start_ticks) ?? 'unavailable'}{' '}
                ·{' '}
                {string(record(process.process)?.service) || 'Service unknown'}
              </p>
              <p>
                Parent PID {number(record(process.process)?.ppid) ?? 'unknown'}{' '}
                · {string(record(process.process)?.state) || 'State unknown'}
              </p>
              <p>
                Read {format(record(process.process)?.read_bytes, 'bytes')} ·
                Written {format(record(process.process)?.write_bytes, 'bytes')}
              </p>
              <p>
                {string(process.availability) || 'Availability unavailable'} ·{' '}
                {string(process.source) ||
                  string(process.provider) ||
                  'Source unavailable'}
              </p>
            </div>
          )}
        </div>
        <div className={`${panel} min-w-0`}>
          <h3 className="font-semibold text-slate-100">Events</h3>
          {events.isLoading ? (
            <p className="mt-3 text-sm text-slate-400">Loading events…</p>
          ) : events.error ? (
            <p role="alert" className="mt-3 text-sm text-rose-300">
              {events.error.message}
            </p>
          ) : filteredEvents.length ? (
            <div className="mt-2 max-h-72 overflow-y-auto">
              {filteredEvents.map((item, index) => (
                <button
                  key={`${item.id ?? index}`}
                  type="button"
                  onClick={() => {
                    setSelectedEvent(`${item.id ?? index}`)
                    const at = measuredAt(item)
                    if (at) setSelectedAt(at)
                  }}
                  className="block w-full border-b border-slate-800 py-2 text-left text-xs hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                >
                  <span className="text-slate-200">
                    {string(item.kind) || 'Event'}
                  </span>
                  <span className="ml-2 text-slate-500">
                    {string(item.entity) || 'Host'} · {when(measuredAt(item))}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">
              {selectedService
                ? 'No events for this service in the window.'
                : 'No events in this window.'}
            </p>
          )}
          {event && (
            <div className="mt-3 border-t border-slate-800 pt-2 text-xs text-slate-400">
              <strong className="text-slate-200">
                {string(event.kind) || 'Event'}
              </strong>
              <p>
                {string(event.severity) || 'Severity unavailable'} ·{' '}
                {string(event.entity) || 'Host'}
              </p>
              <p>
                {string(event.message) ||
                  string(record(event.details)?.message) ||
                  string(record(event.details)?.reason) ||
                  'No further event details.'}
              </p>
            </div>
          )}
          {events.data && (
            <p className="mt-2 text-xs text-slate-500">
              {events.data.truncated ? 'Result truncated · ' : ''}
              {errorText(events.data.errors) || `${eventItems.length} returned`}
            </p>
          )}
        </div>
      </div>
      <HostMonitorDiagnostics
        serviceNames={serviceList.map((entry) => entry.id)}
        selectedService={selectedService}
      />
      <p className="flex items-center gap-1 text-xs text-slate-500">
        <Activity className="h-3 w-3" /> Values reflect the collector’s coverage
        and permissions. Missing readings are unavailable, not zero.
      </p>
    </section>
  )
}
