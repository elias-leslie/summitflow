'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { type MonitorItem, monitorApi } from '@/lib/api/monitor'

type Diagnostic =
  | 'logs'
  | 'sensors'
  | 'connections'
  | 'system-info'
  | 'startup'
  | 'users'
  | 'apps'
  | 'drivers'
  | 'disk-space'
  | 'benchmark'
  | 'export'
const views: Array<{ key: Diagnostic; label: string; description: string }> = [
  {
    key: 'logs',
    label: 'Logs',
    description: 'Managed service journal entries from the last 15 minutes',
  },
  {
    key: 'sensors',
    label: 'Sensors, power & frequency',
    description: 'Available sysfs readings',
  },
  {
    key: 'connections',
    label: 'Connections',
    description: 'Current socket inventory',
  },
  {
    key: 'system-info',
    label: 'System info',
    description: 'OS and hardware identity',
  },
  {
    key: 'startup',
    label: 'Startup',
    description: 'Desktop autostart entries and enabled user service units',
  },
  {
    key: 'users',
    label: 'Users',
    description: 'Local accounts and active login sessions',
  },
  { key: 'apps', label: 'Apps', description: 'Installed Debian packages' },
  { key: 'drivers', label: 'Drivers', description: 'Loaded kernel modules' },
  {
    key: 'disk-space',
    label: 'Disk space',
    description: 'Explicit, bounded file-size attribution',
  },
  {
    key: 'benchmark',
    label: 'Benchmarks',
    description: 'Explicit CPU or cached-file probe',
  },
  {
    key: 'export',
    label: 'Flight recorder',
    description: 'Paged, redacted sample and event replay',
  },
]
const control =
  'rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400'

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}
function display(value: unknown): string {
  if (value === null || value === undefined || value === '')
    return 'Unavailable'
  if (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  )
    return String(value)
  return 'Unavailable'
}
function time(value: unknown): string {
  if (typeof value !== 'string') return 'Time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
function fields(item: MonitorItem, kind: Diagnostic): Array<[string, unknown]> {
  const value = record(item.value) || {}
  switch (kind) {
    case 'logs':
      return [
        ['Time', item.sampled_at],
        ['Priority', value.priority],
        ['Message', value.message],
      ]
    case 'sensors':
      return [
        ['Device', value.device],
        ['Sensor', value.label || value.sensor || value.metric],
        ['Reading', value.reading],
        ['Unit', item.unit],
      ]
    case 'connections':
      return [
        ['Protocol', value.protocol],
        ['Family', value.family],
        ['State', value.state],
        ['Local', value.local],
        ['Remote', value.remote],
        ['PID', value.pid],
        ['Process availability', value.process_availability],
      ]
    case 'system-info':
      return [
        ['System', value.system],
        ['Release', value.release],
        ['Machine', value.machine],
        ['Processor', value.processor],
        ['Logical CPUs', value.logical_cpus],
        [
          'OS name',
          record(value.os_release)?.pretty_name ||
            record(value.os_release)?.name,
        ],
        ['OS version', record(value.os_release)?.version_id],
      ]
    case 'startup':
      return value.kind === 'desktop_autostart'
        ? [
            ['Type', 'Desktop autostart'],
            ['Name', value.name],
            ['Hidden', value.hidden],
            ['Only show in', value.only_show_in],
          ]
        : [
            ['Type', 'Systemd user unit'],
            ['Unit', value.unit],
            ['State', value.state],
          ]
    case 'users':
      return value.kind === 'active_session'
        ? [
            ['Type', 'Active session'],
            ['UID', value.uid],
            ['State', value.state],
          ]
        : [
            ['Type', 'Local account'],
            ['Name', value.name],
            ['UID', value.uid],
            ['Shell', value.shell],
          ]
    case 'apps':
      return [
        ['Package', value.name],
        ['Version', value.version],
      ]
    case 'disk-space':
    case 'benchmark':
    case 'export':
      return []
    case 'drivers':
      return [
        ['Module', value.module],
        ['Size (bytes)', value.size_bytes],
        ['Use count', value.use_count],
      ]
  }
}
function summary(item: MonitorItem, kind: Diagnostic): string {
  const value = record(item.value) || {}
  switch (kind) {
    case 'logs':
      return `${time(item.sampled_at)} · ${display(value.message)}`
    case 'sensors':
      return `${display(value.label || value.sensor || value.metric)} · ${display(value.reading)}${typeof item.unit === 'string' ? ` ${item.unit}` : ''}`
    case 'connections':
      return `${display(value.protocol)} ${display(value.state)} · ${display(value.local)} → ${display(value.remote)}`
    case 'system-info':
      return `${display(value.system)} ${display(value.release)} · ${display(value.machine)}`
    case 'startup':
      return value.kind === 'desktop_autostart'
        ? `${display(value.name)} · desktop autostart${value.hidden === true ? ' · hidden' : ''}`
        : `${display(value.unit)} · ${display(value.state)} · systemd unit`
    case 'users':
      return value.kind === 'active_session'
        ? `Active session · UID ${display(value.uid)}`
        : `${display(value.name)} · UID ${display(value.uid)} · local account`
    case 'apps':
      return `${display(value.name)} · ${display(value.version)}`
    case 'drivers':
      return `${display(value.module)} · ${display(value.use_count)} uses`
    case 'disk-space':
    case 'benchmark':
    case 'export':
      return ''
  }
}
function errors(values: unknown[]): string | null {
  if (!values.length) return null
  return values
    .slice(0, 4)
    .map((value) => {
      const issue = record(value)
      return (
        [issue?.source, issue?.code, issue?.message]
          .filter((part) => typeof part === 'string' && part)
          .join(': ') || 'Source error'
      )
    })
    .join(' · ')
}

export function HostMonitorDiagnostics({
  serviceNames,
  selectedService,
}: {
  serviceNames: string[]
  selectedService: string | null
}) {
  const [active, setActive] = useState<Diagnostic | null>(null)
  const [logService, setLogService] = useState('')
  const [priority, setPriority] = useState('')
  const [showAddresses, setShowAddresses] = useState(false)
  const [includeProcess, setIncludeProcess] = useState(false)
  const [revision, setRevision] = useState(0)
  const chosenService = logService || selectedService || ''
  const query = useQuery({
    queryKey: [
      'monitor',
      'diagnostic',
      active,
      chosenService,
      priority,
      showAddresses,
      includeProcess,
      revision,
    ],
    enabled:
      active !== null &&
      !['disk-space', 'benchmark', 'export'].includes(active) &&
      (active !== 'logs' || chosenService !== ''),
    queryFn: () => {
      if (active === 'logs')
        return monitorApi.logs({
          service: chosenService,
          priority: priority ? Number(priority) : undefined,
          limit: 40,
        })
      if (active === 'connections')
        return monitorApi.connections({
          show_addresses: showAddresses,
          include_process: includeProcess,
          limit: 50,
        })
      if (
        active === 'sensors' ||
        active === 'system-info' ||
        active === 'startup' ||
        active === 'users' ||
        active === 'apps' ||
        active === 'drivers'
      )
        return monitorApi.diagnostics(
          active,
          active === 'users' || active === 'startup' ? 100 : 50,
        )
      throw new Error('Choose a diagnostic view')
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const current = views.find((view) => view.key === active)
  return (
    <section
      className="rounded-lg border border-slate-700/60 bg-slate-900/45 p-4"
      aria-label="On-demand diagnostics"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold text-slate-100">On-demand diagnostics</h3>
        <p className="text-xs text-slate-500">Read-only, bounded host checks</p>
      </div>
      <div className="mt-3 flex flex-wrap gap-2" aria-label="Diagnostic views">
        {views.map((view) => (
          <button
            key={view.key}
            type="button"
            aria-pressed={active === view.key}
            onClick={() => setActive(active === view.key ? null : view.key)}
            className={`${control} ${active === view.key ? 'border-cyan-500 text-cyan-300' : 'hover:bg-slate-800'}`}
          >
            {view.label}
          </button>
        ))}
      </div>
      {active && (
        <div className="mt-4 border-t border-slate-800 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 className="font-medium text-slate-100">{current?.label}</h4>
              <p className="text-xs text-slate-500">{current?.description}</p>
            </div>
            {!['disk-space', 'benchmark', 'export'].includes(active) && (
              <button
                type="button"
                className={control}
                onClick={() => setRevision((value) => value + 1)}
              >
                Run again
              </button>
            )}
          </div>
          {active === 'logs' && (
            <div className="mt-3 flex flex-wrap gap-3">
              <label className="text-xs text-slate-400">
                Managed service{' '}
                <select
                  className={`${control} ml-1`}
                  value={chosenService}
                  onChange={(event) => setLogService(event.target.value)}
                >
                  <option value="">Choose service</option>
                  {serviceNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-slate-400">
                Priority{' '}
                <select
                  className={`${control} ml-1`}
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                >
                  <option value="">All</option>
                  {Array.from({ length: 8 }, (_, value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {active === 'connections' && (
            <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-300">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={showAddresses}
                  onChange={(event) => setShowAddresses(event.target.checked)}
                  className="accent-cyan-400"
                />
                Show socket addresses
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={includeProcess}
                  onChange={(event) => setIncludeProcess(event.target.checked)}
                  className="accent-cyan-400"
                />
                Look up owning PIDs
              </label>
              <p className="basis-full text-xs text-slate-500">
                Addresses are redacted by default. Process ownership depends on
                procfs access.
              </p>
            </div>
          )}
          {active === 'disk-space' ? (
            <DiskSpacePanel />
          ) : active === 'benchmark' ? (
            <BenchmarkPanel />
          ) : active === 'export' ? (
            <FlightRecorderPanel />
          ) : active === 'logs' && !chosenService ? (
            <p className="mt-3 text-sm text-slate-400">
              Choose a managed service to read its logs.
            </p>
          ) : query.isLoading ? (
            <p role="status" className="mt-3 text-sm text-slate-400">
              Loading {current?.label.toLowerCase()}…
            </p>
          ) : query.error ? (
            <p role="alert" className="mt-3 text-sm text-rose-300">
              {query.error.message}
            </p>
          ) : (
            query.data && (
              <>
                <p className="mt-3 text-xs text-slate-400">
                  {query.data.items.length} returned ·{' '}
                  {display(query.data.coverage.availability)} · response{' '}
                  {time(query.data.generated_at)}
                  {query.data.truncated ? ' · truncated' : ''}
                </p>
                {errors(query.data.errors) && (
                  <p className="mt-2 text-xs text-amber-300">
                    {errors(query.data.errors)}
                  </p>
                )}
                {active === 'users' && (
                  <p className="mt-2 text-xs text-slate-400">
                    {display(query.data.coverage.accounts_seen)} local accounts
                    · {display(query.data.coverage.active_sessions_seen)} active
                    sessions · session source{' '}
                    {display(query.data.coverage.sessions)}
                  </p>
                )}
                {active === 'startup' && (
                  <p className="mt-2 text-xs text-slate-400">
                    Desktop scan{' '}
                    {display(
                      query.data.coverage.providers &&
                        record(query.data.coverage.providers)
                          ?.desktop_autostart,
                    )}{' '}
                    · {display(query.data.coverage.desktop_files_scanned)} files
                    scanned
                  </p>
                )}
                {active === 'connections' && (
                  <p className="mt-2 text-xs text-slate-400">
                    {display(query.data.coverage.socket_count_scanned)} sockets
                    scanned · addresses{' '}
                    {query.data.coverage.addresses_redacted === true
                      ? 'redacted'
                      : 'shown'}
                  </p>
                )}
                {query.data.items.length ? (
                  <div className="mt-3 max-h-96 space-y-1 overflow-y-auto">
                    {query.data.items.map((item, index) => (
                      <details
                        key={`${item.sampled_at}-${index}`}
                        className="group rounded-md border border-slate-800 bg-slate-950/40 text-sm"
                      >
                        <summary
                          className="cursor-pointer truncate px-3 py-2 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                          title={summary(item, active)}
                        >
                          {summary(item, active)}
                        </summary>
                        <div className="border-t border-slate-800 px-3 py-2">
                          <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[max-content_minmax(0,1fr)]">
                            {fields(item, active).map(([label, value]) => (
                              <div key={label} className="contents">
                                <dt className="text-slate-500">{label}</dt>
                                <dd className="break-all text-slate-300">
                                  {label === 'Time'
                                    ? time(value)
                                    : display(value)}
                                </dd>
                              </div>
                            ))}
                          </dl>
                          <p className="mt-2 text-xs text-slate-500">
                            {display(item.availability)} ·{' '}
                            {display(item.source)} · {display(item.provider)}
                          </p>
                        </div>
                      </details>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-slate-400">
                    {query.data.coverage.availability === 'ok'
                      ? 'No results in this check.'
                      : `No results: ${display(query.data.coverage.availability)}.`}
                  </p>
                )}
              </>
            )
          )}
        </div>
      )}
    </section>
  )
}

function Bytes({ value }: { value: unknown }) {
  if (typeof value !== 'number' || !Number.isFinite(value))
    return <>Unavailable</>
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let amount = value
  let index = 0
  while (Math.abs(amount) >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return (
    <>
      {amount.toFixed(index ? 1 : 0)} {units[index]}
    </>
  )
}

function DiskSpacePanel() {
  const [path, setPath] = useState('')
  const scan = useMutation({
    mutationFn: (value: string) =>
      monitorApi.diskSpace({
        path: value,
        max_entries: 1024,
        max_depth: 6,
        timeout_seconds: 2,
        limit: 50,
      }),
  })
  const coverage = scan.data?.coverage
  return (
    <div className="mt-3 space-y-3">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (path.trim()) scan.mutate(path.trim())
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="min-w-[min(100%,22rem)] flex-1 text-xs text-slate-400">
          Path beneath owner home or registered project root
          <input
            required
            type="text"
            value={path}
            onChange={(event) => {
              setPath(event.target.value)
              scan.reset()
            }}
            placeholder="Enter an allowed absolute path"
            className={`${control} mt-1 w-full`}
          />
        </label>
        <button
          type="submit"
          disabled={scan.isPending || !path.trim()}
          className={control}
        >
          {scan.isPending ? 'Scanning…' : 'Scan disk space'}
        </button>
      </form>
      <p className="text-xs text-slate-500">
        Scans at most 1,024 entries, six levels and two seconds. Sizes are
        apparent regular-file bytes.
      </p>
      {scan.error && (
        <p role="alert" className="text-sm text-rose-300">
          {scan.error.message}
        </p>
      )}
      {scan.data && (
        <>
          <p role="status" className="text-xs text-slate-400">
            {display(coverage?.availability)} · {display(coverage?.scope)} scope
            · {display(coverage?.entries_scanned)} entries scanned ·{' '}
            <Bytes value={coverage?.bytes_observed} /> observed
            {scan.data.truncated ? ' · response truncated' : ''}
          </p>
          {(coverage?.complete === false || coverage?.stop_reason) && (
            <p className="text-xs text-amber-300">
              Partial scan: {display(coverage?.stop_reason)} ·{' '}
              {display(coverage?.entries_hidden_or_skipped)} hidden or skipped ·{' '}
              {display(coverage?.entries_permission_denied)} permission denied.
            </p>
          )}
          {errors(scan.data.errors) && (
            <p className="text-xs text-amber-300">{errors(scan.data.errors)}</p>
          )}
          {scan.data.items.length ? (
            <div className="max-h-80 overflow-y-auto rounded-md border border-slate-800">
              {scan.data.items.map((item, index) => {
                const value = record(item.value) || {}
                return (
                  <div
                    key={`${value.name}-${index}`}
                    className="flex items-center justify-between gap-3 border-b border-slate-800 px-3 py-2 text-xs"
                  >
                    <span
                      className="min-w-0 truncate text-slate-200"
                      title={display(value.name)}
                    >
                      {display(value.name)}{' '}
                      <span className="text-slate-500">
                        {display(value.kind)}
                      </span>
                    </span>
                    <span className="shrink-0 font-mono text-slate-300">
                      <Bytes value={value.apparent_bytes} />
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-sm text-slate-400">
              No entries returned for this scan.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function BenchmarkPanel() {
  const [kind, setKind] = useState<'cpu' | 'disk'>('cpu')
  const [duration, setDuration] = useState(1)
  const run = useMutation({
    mutationFn: () =>
      monitorApi.benchmark({ kind, duration_seconds: duration }),
  })
  const item = run.data?.items[0]
  const value = record(item?.value) || {}
  return (
    <div className="mt-3 space-y-3">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          run.mutate()
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="text-xs text-slate-400">
          Probe{' '}
          <select
            className={`${control} ml-1`}
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as 'cpu' | 'disk')
              run.reset()
            }}
          >
            <option value="cpu">CPU hash</option>
            <option value="disk">Cached file read</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Maximum duration{' '}
          <select
            className={`${control} ml-1`}
            value={duration}
            onChange={(event) => {
              setDuration(Number(event.target.value))
              run.reset()
            }}
          >
            <option value={1}>1 second</option>
            <option value={2}>2 seconds</option>
            <option value={3}>3 seconds</option>
          </select>
        </label>
        <button type="submit" disabled={run.isPending} className={control}>
          {run.isPending ? 'Running…' : 'Run benchmark'}
        </button>
      </form>
      <p className="text-xs text-slate-500">
        The file probe rereads a fixed project file and may be served from
        cache. It does not measure physical disk throughput.
      </p>
      {run.error && (
        <p role="alert" className="text-sm text-rose-300">
          {run.error.message}
        </p>
      )}
      {run.data && (
        <>
          <p role="status" className="text-xs text-slate-400">
            {display(run.data.coverage.availability)} ·{' '}
            {display(run.data.coverage.measurement)} ·{' '}
            {run.data.coverage.cache_affected === true
              ? 'cache affected'
              : 'in memory'}
            {run.data.truncated ? ' · truncated' : ''}
          </p>
          {errors(run.data.errors) && (
            <p className="text-xs text-amber-300">{errors(run.data.errors)}</p>
          )}
          {item ? (
            <dl className="grid gap-x-4 gap-y-1 rounded-md border border-slate-800 bg-slate-950/40 p-3 text-xs sm:grid-cols-[max-content_minmax(0,1fr)]">
              {(
                [
                  ['Workload', value.workload],
                  ['Source', value.source],
                  ['Bytes processed', value.bytes_processed],
                  ['Iterations', value.iterations],
                  ['Elapsed seconds', value.elapsed_seconds],
                  ['Process CPU seconds', value.process_cpu_seconds],
                  ['Bytes per second', value.bytes_per_second],
                  ['CPU cost, one core %', value.cpu_cost_pct_one_core],
                ] as Array<[string, unknown]>
              ).map(([label, field]) => (
                <div key={label} className="contents">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="text-slate-200">{display(field)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-slate-400">No measurement returned.</p>
          )}
        </>
      )}
    </div>
  )
}

function FlightRecorderPanel() {
  const [range, setRange] = useState(() => {
    const until = new Date()
    return {
      since: new Date(until.getTime() - 15 * 60_000).toISOString(),
      until: until.toISOString(),
    }
  })
  const [windowMinutes, setWindowMinutes] = useState(15)
  const [cursors, setCursors] = useState<Array<string | undefined>>([undefined])
  const cursor = cursors.at(-1)
  const page = useQuery({
    queryKey: ['monitor', 'export', range.since, range.until, cursor],
    queryFn: () => monitorApi.exportPage({ ...range, cursor, limit: 20 }),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const reset = (minutes: number) => {
    const until = new Date()
    setRange({
      since: new Date(until.getTime() - minutes * 60_000).toISOString(),
      until: until.toISOString(),
    })
    setCursors([undefined])
  }
  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-slate-400">
          Window{' '}
          <select
            className={`${control} ml-1`}
            value={windowMinutes}
            onChange={(event) => {
              const minutes = Number(event.target.value)
              setWindowMinutes(minutes)
              reset(minutes)
            }}
          >
            <option value={15}>15 minutes</option>
            <option value={60}>1 hour</option>
            <option value={1440}>24 hours</option>
          </select>
        </label>
        <button
          type="button"
          className={control}
          onClick={() => reset(windowMinutes)}
        >
          Load recent
        </button>
      </div>
      <p className="text-xs text-slate-500">
        {time(range.since)} to {time(range.until)} · redacted samples and events
        · up to 20 rows per page
      </p>
      {page.isLoading ? (
        <p role="status" className="text-sm text-slate-400">
          Loading replay…
        </p>
      ) : page.error ? (
        <p role="alert" className="text-sm text-rose-300">
          {page.error.message}
        </p>
      ) : (
        page.data && (
          <>
            <p className="text-xs text-slate-400">
              {display(page.data.coverage.availability)} ·{' '}
              {display(page.data.coverage.samples_in_page)} samples ·{' '}
              {display(page.data.coverage.events_in_page)} events ·{' '}
              {display(page.data.coverage.gaps_in_page)} gaps
              {page.data.truncated ? ' · more pages' : ''}
            </p>
            {errors(page.data.errors) && (
              <p className="text-xs text-amber-300">
                {errors(page.data.errors)}
              </p>
            )}
            {page.data.items.length ? (
              <div className="max-h-96 space-y-1 overflow-y-auto">
                {page.data.items.map((item, index) => (
                  <details
                    key={`${item.sampled_at}-${index}`}
                    className="rounded-md border border-slate-800 bg-slate-950/40 text-xs"
                  >
                    <summary className="cursor-pointer px-3 py-2 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                      {time(item.sampled_at)} ·{' '}
                      {item.type === 'event'
                        ? `${display(item.kind)} event`
                        : `${display(item.mode)} sample`}
                      {typeof item.gap_to_next_seconds === 'number'
                        ? ` · ${item.gap_to_next_seconds}s gap`
                        : ''}
                    </summary>
                    <div className="space-y-1 border-t border-slate-800 p-3 text-slate-400">
                      {item.type === 'event' ? (
                        <p>
                          {display(item.severity)} · entity and details redacted
                        </p>
                      ) : (
                        <>
                          <p>
                            Host CPU {display(record(item.host)?.cpu_busy_pct)}%
                            · available memory{' '}
                            <Bytes
                              value={record(item.host)?.memory_available_bytes}
                            />{' '}
                            · free disk{' '}
                            <Bytes value={record(item.host)?.disk_free_bytes} />
                          </p>
                          <p>
                            Process coverage:{' '}
                            {display(
                              record(item.process_coverage)?.availability,
                            )}{' '}
                            ·{' '}
                            {display(
                              record(item.process_coverage)?.snapshot_returned,
                            )}{' '}
                            limited process snapshots ·{' '}
                            {display(
                              record(item.process_coverage)?.permission_denied,
                            )}{' '}
                            permission denied
                          </p>
                        </>
                      )}
                      <p>
                        {display(item.availability)} · {display(item.source)} ·{' '}
                        {display(item.provider)}
                      </p>
                    </div>
                  </details>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                No samples or events in this window.
              </p>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={cursors.length === 1}
                className={control}
                onClick={() => setCursors((items) => items.slice(0, -1))}
              >
                Previous
              </button>
              <span className="text-xs text-slate-500">
                Page {cursors.length}
              </span>
              <button
                type="button"
                disabled={!page.data.next_cursor}
                className={control}
                onClick={() => {
                  if (page.data?.next_cursor)
                    setCursors((items) => [
                      ...items,
                      page.data.next_cursor || undefined,
                    ])
                }}
              >
                Next
              </button>
            </div>
          </>
        )
      )}
    </div>
  )
}
