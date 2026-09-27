'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  type MonitorItem,
  type MonitorLogScope,
  monitorApi,
} from '@/lib/api/monitor'

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
    description: 'User, system, and container logs',
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
  { key: 'apps', label: 'Apps', description: 'Installed packages by provider' },
  { key: 'drivers', label: 'Drivers', description: 'Loaded kernel modules' },
  {
    key: 'disk-space',
    label: 'Disk space',
    description: 'Mounted capacity and bounded path scan',
  },
  {
    key: 'benchmark',
    label: 'Benchmarks',
    description: 'Explicit CPU or cached-file probe',
  },
  {
    key: 'export',
    label: 'Flight recorder',
    description: 'Paged sample and event replay',
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
function detailRows(value: unknown): Array<[string, string]> {
  const details = record(value)
  if (!details) return []
  return Object.entries(details).map(([key, entry]) => [
    key.replaceAll('_', ' '),
    typeof entry === 'string' ||
    typeof entry === 'number' ||
    typeof entry === 'boolean'
      ? String(entry)
      : entry === null
        ? 'Unavailable'
        : JSON.stringify(entry),
  ])
}
function recentLogWindow() {
  const until = new Date()
  return {
    since: new Date(until.getTime() - 15 * 60_000).toISOString(),
    until: until.toISOString(),
  }
}
function fields(item: MonitorItem, kind: Diagnostic): Array<[string, unknown]> {
  const value = record(item.value) || {}
  switch (kind) {
    case 'logs':
      return [
        ['Time', item.measured_at || item.sampled_at],
        ['Source', value.container_name || value.unit || value.service],
        ...(value.scope === 'container'
          ? ([
              ['Container ID', value.container_id],
              ['Stream', value.stream],
            ] as Array<[string, unknown]>)
          : []),
        ['Scope', value.scope],
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
        [
          'Owning PIDs',
          Array.isArray(value.pids) ? value.pids.join(', ') : value.pids,
        ],
        ['Process', value.process_name],
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
      return value.name_truncated === true
        ? [
            ['Package', value.name],
            ['Version', value.version],
            ['Package name', 'Shortened to 128 characters'],
          ]
        : [
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
      return `${time(item.measured_at || item.sampled_at)} · ${display(value.container_name || value.unit || value.service)} · ${display(value.message)}`
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
      return `${display(value.name)}${value.name_truncated === true ? '…' : ''} · ${display(value.version)}`
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
  const [logService, setLogService] = useState(selectedService || '')
  const [logScope, setLogScope] = useState<MonitorLogScope>('user')
  const [priority, setPriority] = useState('')
  const [logWindow, setLogWindow] = useState(recentLogWindow)
  const [logCursors, setLogCursors] = useState<Array<string | undefined>>([
    undefined,
  ])
  const [connectionCursors, setConnectionCursors] = useState<
    Array<string | undefined>
  >([undefined])
  const [connectionFilter, setConnectionFilter] = useState('')
  const [connectionState, setConnectionState] = useState('all')
  const [appsProvider, setAppsProvider] = useState<'dpkg' | 'snap' | 'flatpak'>(
    'dpkg',
  )
  const [appsNameDraft, setAppsNameDraft] = useState('')
  const [appsName, setAppsName] = useState('')
  const [appsCursor, setAppsCursor] = useState<string | null>(null)
  const [appsPrevious, setAppsPrevious] = useState<Array<string | null>>([])
  const [revision, setRevision] = useState(0)
  const resetLogPage = () => {
    setLogWindow(recentLogWindow())
    setLogCursors([undefined])
  }
  const logServices = useQuery({
    queryKey: ['monitor', 'log-services', logScope],
    queryFn: () => monitorApi.logServices(logScope),
    enabled: active === 'logs',
    staleTime: 60_000,
  })
  const availableServices = Array.from(
    new Set([
      ...(logScope === 'user' ? serviceNames : []),
      ...(logServices.data?.items || []).flatMap((item) => {
        const service = record(item.value)?.service
        return typeof service === 'string' ? [service] : []
      }),
    ]),
  ).sort()
  const chosenService =
    logService || (logScope === 'container' ? availableServices[0] || '' : '')
  const query = useQuery({
    queryKey: [
      'monitor',
      'diagnostic',
      active,
      chosenService,
      logScope,
      priority,
      logWindow.since,
      logWindow.until,
      logCursors.at(-1),
      connectionCursors.at(-1),
      appsProvider,
      appsName,
      appsCursor,
      revision,
    ],
    enabled:
      active !== null &&
      !['disk-space', 'benchmark', 'export'].includes(active) &&
      (active !== 'logs' || logScope !== 'container' || !!chosenService),
    queryFn: () => {
      if (active === 'logs')
        return monitorApi.logs({
          service: chosenService || undefined,
          scope: logScope,
          ...logWindow,
          cursor: logScope === 'container' ? undefined : logCursors.at(-1),
          priority:
            logScope !== 'container' && priority ? Number(priority) : undefined,
          limit: 40,
        })
      if (active === 'connections')
        return monitorApi.connections({
          show_addresses: true,
          include_process: true,
          limit: 50,
          cursor: connectionCursors.at(-1),
        })
      if (
        active === 'sensors' ||
        active === 'system-info' ||
        active === 'startup' ||
        active === 'users' ||
        active === 'drivers'
      )
        return monitorApi.diagnostics(
          active,
          active === 'users' || active === 'startup' ? 100 : 50,
        )
      if (active === 'apps')
        return monitorApi.diagnostics('apps', 50, {
          provider: appsProvider,
          name: appsName || undefined,
          cursor: appsCursor || undefined,
        })
      throw new Error('Choose a diagnostic view')
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const current = views.find((view) => view.key === active)
  const connectionItems = query.data?.items || []
  const filteredConnections =
    active === 'connections'
      ? connectionItems.filter((item) => {
          const value = record(item.value) || {}
          const state = String(value.state || '').toLowerCase()
          const protocol = String(value.protocol || '').toLowerCase()
          const term = connectionFilter.trim().toLowerCase()
          const stateMatches =
            connectionState === 'all' ||
            (connectionState === 'listening' && state.includes('listen')) ||
            (connectionState === 'connected' && state === 'established') ||
            (connectionState === 'udp' && protocol.startsWith('udp'))
          return (
            stateMatches &&
            (!term ||
              [
                value.protocol,
                value.family,
                value.state,
                value.local,
                value.remote,
                value.pid,
                value.pids,
                value.process_name,
              ].some((field) =>
                String(field ?? '')
                  .toLowerCase()
                  .includes(term),
              ))
          )
        })
      : connectionItems
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
                onClick={() => {
                  if (active === 'logs') resetLogPage()
                  if (active === 'connections')
                    setConnectionCursors([undefined])
                  setRevision((value) => value + 1)
                }}
              >
                Run again
              </button>
            )}
          </div>
          {active === 'logs' && (
            <div className="mt-3 flex flex-wrap gap-3">
              <label className="text-xs text-slate-400">
                Log source{' '}
                <select
                  className={`${control} ml-1`}
                  value={logScope}
                  onChange={(event) => {
                    setLogScope(event.target.value as MonitorLogScope)
                    setLogService('')
                    setPriority('')
                    resetLogPage()
                  }}
                >
                  <option value="user">User</option>
                  <option value="system">System</option>
                  <option value="container">Containers</option>
                </select>
              </label>
              <label className="text-xs text-slate-400">
                {logScope === 'container' ? 'Container' : 'Service'}{' '}
                <select
                  className={`${control} ml-1`}
                  value={chosenService}
                  onChange={(event) => {
                    setLogService(event.target.value)
                    resetLogPage()
                  }}
                >
                  {logScope !== 'container' && (
                    <option value="">All services</option>
                  )}
                  {availableServices.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              {logScope !== 'container' && (
                <label className="text-xs text-slate-400">
                  Priority{' '}
                  <select
                    className={`${control} ml-1`}
                    value={priority}
                    onChange={(event) => {
                      setPriority(event.target.value)
                      resetLogPage()
                    }}
                  >
                    <option value="">All</option>
                    {Array.from({ length: 8 }, (_, value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {logServices.isLoading && (
                <p role="status" className="self-center text-xs text-slate-400">
                  Loading {logScope === 'container' ? 'containers' : 'services'}
                  …
                </p>
              )}
              {logServices.error && (
                <p role="alert" className="self-center text-xs text-amber-300">
                  {logScope === 'container' ? 'Container' : 'Service'} list
                  unavailable: {logServices.error.message}
                </p>
              )}
              {logServices.data &&
                (logServices.data.coverage.availability !== 'ok' ||
                  logServices.data.errors.length > 0) && (
                  <p className="basis-full text-xs text-amber-300">
                    {logScope === 'container' ? 'Container' : 'Service'}{' '}
                    inventory: {display(logServices.data.coverage.availability)}
                    {errors(logServices.data.errors)
                      ? ` · ${errors(logServices.data.errors)}`
                      : ''}
                  </p>
                )}
            </div>
          )}
          {active === 'connections' && (
            <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-300">
              <label className="min-w-[min(100%,18rem)] flex-1 text-xs text-slate-400">
                Filter returned connections
                <input
                  type="search"
                  value={connectionFilter}
                  onChange={(event) => setConnectionFilter(event.target.value)}
                  placeholder="Protocol, state, address or PID"
                  className={`${control} mt-1 w-full`}
                />
              </label>
              <label className="text-xs text-slate-400">
                State or protocol
                <select
                  value={connectionState}
                  onChange={(event) => setConnectionState(event.target.value)}
                  className={`${control} mt-1 block`}
                >
                  <option value="all">All returned</option>
                  <option value="connected">Connected</option>
                  <option value="listening">Listening</option>
                  <option value="udp">UDP</option>
                </select>
              </label>
              <p className="basis-full text-xs text-slate-500">
                Socket addresses and owning PIDs are shown when the collector
                can read them. Live pages may shift as sockets change.
              </p>
            </div>
          )}
          {active === 'apps' && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label className="text-xs text-slate-400">
                Package source{' '}
                <select
                  className={`${control} ml-1`}
                  value={appsProvider}
                  onChange={(event) => {
                    setAppsProvider(
                      event.target.value as 'dpkg' | 'snap' | 'flatpak',
                    )
                    setAppsCursor(null)
                    setAppsPrevious([])
                  }}
                >
                  <option value="dpkg">Debian packages</option>
                  <option value="snap">Snap packages</option>
                  <option value="flatpak">Flatpak apps</option>
                </select>
              </label>
              <p className="text-xs text-slate-500">
                Live inventory; pages may shift when packages change.
              </p>
              <form
                className="flex basis-full flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  setAppsName(appsNameDraft.trim())
                  setAppsCursor(null)
                  setAppsPrevious([])
                }}
              >
                <label className="min-w-[min(100%,18rem)] flex-1 text-xs text-slate-400">
                  Search package names
                  <input
                    type="search"
                    value={appsNameDraft}
                    maxLength={128}
                    onChange={(event) => setAppsNameDraft(event.target.value)}
                    placeholder="Package name"
                    className={`${control} mt-1 w-full`}
                  />
                </label>
                <button type="submit" className={control}>
                  Search
                </button>
                {appsName && (
                  <button
                    type="button"
                    className={control}
                    onClick={() => {
                      setAppsNameDraft('')
                      setAppsName('')
                      setAppsCursor(null)
                      setAppsPrevious([])
                    }}
                  >
                    Clear
                  </button>
                )}
              </form>
            </div>
          )}
          {active === 'disk-space' ? (
            <DiskSpacePanel />
          ) : active === 'benchmark' ? (
            <BenchmarkPanel />
          ) : active === 'export' ? (
            <FlightRecorderPanel />
          ) : active === 'logs' &&
            logScope === 'container' &&
            !chosenService ? (
            <p role="status" className="mt-3 text-sm text-slate-400">
              {logServices.isLoading
                ? 'Loading containers…'
                : logServices.error
                  ? 'Container list unavailable.'
                  : logServices.data?.coverage.availability !== 'ok'
                    ? `Container inventory ${display(logServices.data?.coverage.availability)}.`
                    : 'No containers available.'}
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
                      ? 'unavailable'
                      : 'shown'}
                    {' · '}
                    {filteredConnections.length} match in{' '}
                    {query.data.items.length} returned · namespace{' '}
                    {display(query.data.coverage.network_namespace)}
                  </p>
                )}
                {active === 'logs' && (
                  <p className="mt-2 text-xs text-slate-500">
                    {time(logWindow.since)} to {time(logWindow.until)}
                    {logScope === 'container'
                      ? ''
                      : ` · page ${logCursors.length}`}
                  </p>
                )}
                {active === 'logs' && logScope === 'container' && (
                  <p className="mt-1 text-xs text-slate-500">
                    Priority filter:{' '}
                    {display(query.data.coverage.priority_filter)}
                    {' · '}Paging: {display(query.data.coverage.pagination)}
                  </p>
                )}
                {active === 'apps' && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    <span>
                      {display(query.data.coverage.source)} · page{' '}
                      {appsPrevious.length + 1} ·{' '}
                      {appsName
                        ? `${display(query.data.coverage.matches_seen)} matches in ${display(query.data.coverage.entries_seen)} entries seen · name contains “${appsName}”`
                        : `${display(query.data.coverage.entries_seen)} entries seen`}
                    </span>
                    {appsPrevious.length > 0 && (
                      <button
                        type="button"
                        className={control}
                        onClick={() => {
                          const previous = appsPrevious.at(-1) ?? null
                          setAppsPrevious((value) => value.slice(0, -1))
                          setAppsCursor(previous)
                        }}
                      >
                        Previous page
                      </button>
                    )}
                    {query.data.next_cursor && (
                      <button
                        type="button"
                        className={control}
                        onClick={() => {
                          setAppsPrevious((value) => [...value, appsCursor])
                          setAppsCursor(query.data?.next_cursor || null)
                        }}
                      >
                        Next page
                      </button>
                    )}
                  </div>
                )}
                {(active === 'connections'
                  ? filteredConnections
                  : query.data.items
                ).length ? (
                  <div className="mt-3 max-h-96 space-y-1 overflow-y-auto">
                    {(active === 'connections'
                      ? filteredConnections
                      : query.data.items
                    ).map((item, index) => (
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
                    {active === 'connections' && query.data.items.length
                      ? 'No returned connections match these filters.'
                      : query.data.coverage.availability === 'ok'
                        ? 'No results in this check.'
                        : `No results: ${display(query.data.coverage.availability)}.`}
                  </p>
                )}
                {((active === 'logs' && logScope !== 'container') ||
                  active === 'connections') &&
                  ((active === 'logs' ? logCursors : connectionCursors).length >
                    1 ||
                    query.data.next_cursor) && (
                    <div className="mt-3 flex items-center gap-2">
                      <button
                        type="button"
                        className={control}
                        disabled={
                          (active === 'logs' ? logCursors : connectionCursors)
                            .length === 1
                        }
                        onClick={() => {
                          if (active === 'logs')
                            setLogCursors((items) => items.slice(0, -1))
                          else
                            setConnectionCursors((items) => items.slice(0, -1))
                        }}
                      >
                        Previous page
                      </button>
                      <span className="text-xs text-slate-500">
                        Page{' '}
                        {active === 'logs'
                          ? logCursors.length
                          : connectionCursors.length}
                      </span>
                      <button
                        type="button"
                        className={control}
                        disabled={!query.data.next_cursor}
                        onClick={() => {
                          const next = query.data?.next_cursor
                          if (!next) return
                          if (active === 'logs')
                            setLogCursors((items) => [...items, next])
                          else setConnectionCursors((items) => [...items, next])
                        }}
                      >
                        Next page
                      </button>
                    </div>
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
  const [mountCursors, setMountCursors] = useState<Array<string | undefined>>([
    undefined,
  ])
  const mounts = useQuery({
    queryKey: ['monitor', 'mounts', mountCursors.at(-1)],
    queryFn: () => monitorApi.mounts(mountCursors.at(-1)),
    staleTime: 60_000,
  })
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
  const diskRows = (scan.data?.items || []).map((item) => ({
    item,
    value: record(item.value) || {},
  }))
  const returnedBytes = diskRows.reduce(
    (sum, row) =>
      sum +
      (typeof row.value.apparent_bytes === 'number' &&
      Number.isFinite(row.value.apparent_bytes)
        ? Math.max(0, row.value.apparent_bytes)
        : 0),
    0,
  )
  return (
    <div className="mt-3 space-y-3">
      <div className="rounded-md border border-slate-800 bg-slate-950/40">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-2">
          <h5 className="text-sm font-medium text-slate-200">
            Mounted filesystems
          </h5>
          <button
            type="button"
            className={control}
            onClick={() => mounts.refetch()}
          >
            Refresh mounts
          </button>
        </div>
        {mounts.isLoading ? (
          <p role="status" className="px-3 py-3 text-sm text-slate-400">
            Loading mounts…
          </p>
        ) : mounts.error ? (
          <p role="alert" className="px-3 py-3 text-sm text-rose-300">
            {mounts.error.message}
          </p>
        ) : mounts.data ? (
          <div className="px-3 py-2">
            <p className="text-xs text-slate-500">
              Page {mountCursors.length} · {mounts.data.items.length} returned ·{' '}
              {display(mounts.data.coverage.availability)}
              {' · sampled '}
              {time(mounts.data.coverage.sampled_at)}
              {mounts.data.truncated ? ' · truncated' : ''}
            </p>
            {mounts.data.coverage.live_pages_may_shift === true && (
              <p className="mt-1 text-xs text-slate-500">
                Pages may shift after a new collector sample.
              </p>
            )}
            {errors(mounts.data.errors) && (
              <p className="mt-1 text-xs text-amber-300">
                {errors(mounts.data.errors)}
              </p>
            )}
            {mounts.data.items.length ? (
              <div className="mt-2 max-h-72 overflow-auto">
                <table className="w-full min-w-[36rem] text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="pb-2">Mount</th>
                      <th>Source / type</th>
                      <th>Total</th>
                      <th>Available</th>
                      <th className="sr-only">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mounts.data.items.map((item, index) => {
                      const value = record(item.value) || {}
                      const mountpoint =
                        typeof value.mountpoint === 'string'
                          ? value.mountpoint
                          : ''
                      return (
                        <tr
                          key={`${mountpoint}-${index}`}
                          className="border-t border-slate-800 text-slate-300"
                        >
                          <td className="py-2 pr-3 font-mono break-all">
                            {display(mountpoint)}
                          </td>
                          <td className="py-2 pr-3 break-all">
                            {display(value.source)}{' '}
                            <span className="text-slate-500">
                              {display(value.filesystem)}
                              {value.counted_in_coverage === false
                                ? ' · shared filesystem capacity'
                                : ''}
                            </span>
                          </td>
                          <td className="py-2 pr-3 whitespace-nowrap">
                            <Bytes value={value.total_bytes} />
                          </td>
                          <td className="py-2 pr-3 whitespace-nowrap">
                            <Bytes value={value.available_bytes} />
                          </td>
                          <td className="py-2 text-right">
                            {mountpoint && (
                              <button
                                type="button"
                                className={control}
                                onClick={() => {
                                  setPath(mountpoint)
                                  scan.mutate(mountpoint)
                                }}
                              >
                                Scan
                              </button>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-400">No mounts returned.</p>
            )}
            {(mountCursors.length > 1 || mounts.data.next_cursor) && (
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  className={control}
                  disabled={mountCursors.length === 1}
                  onClick={() => setMountCursors((items) => items.slice(0, -1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className={control}
                  disabled={!mounts.data.next_cursor}
                  onClick={() => {
                    if (mounts.data?.next_cursor)
                      setMountCursors((items) => [
                        ...items,
                        mounts.data.next_cursor || undefined,
                      ])
                  }}
                >
                  Next
                </button>
              </div>
            )}
          </div>
        ) : null}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (path.trim()) scan.mutate(path.trim())
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="min-w-[min(100%,22rem)] flex-1 text-xs text-slate-400">
          Path on a mounted filesystem
          <input
            required
            type="text"
            value={path}
            onChange={(event) => {
              setPath(event.target.value)
              scan.reset()
            }}
            placeholder="Enter an absolute path"
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
              <p className="border-b border-slate-800 px-3 py-2 text-xs text-slate-400">
                Top-level entries · bars compare returned sizes only
              </p>
              {diskRows.map(({ value }, index) => {
                const apparent =
                  typeof value.apparent_bytes === 'number' &&
                  Number.isFinite(value.apparent_bytes)
                    ? Math.max(0, value.apparent_bytes)
                    : 0
                return (
                  <div
                    key={`${value.name}-${index}`}
                    className="border-b border-slate-800 px-3 py-2 text-xs"
                  >
                    <div className="flex items-center justify-between gap-3">
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
                    <div
                      className="mt-1 h-1.5 rounded bg-slate-800"
                      aria-hidden="true"
                    >
                      <div
                        className="h-full rounded bg-cyan-500"
                        style={{
                          width: `${returnedBytes > 0 ? (apparent / returnedBytes) * 100 : 0}%`,
                        }}
                      />
                    </div>
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
        {time(range.since)} to {time(range.until)} · samples and events · up to
        20 rows per page
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
                        <div className="space-y-2">
                          <p>
                            {display(item.severity)} · {display(item.entity)}
                          </p>
                          {detailRows(item.details).length ? (
                            <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_minmax(0,1fr)]">
                              {detailRows(item.details).map(([key, value]) => (
                                <div key={key} className="contents">
                                  <dt className="text-slate-500">{key}</dt>
                                  <dd className="break-all text-slate-300">
                                    {value}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          ) : (
                            <p>No additional details recorded.</p>
                          )}
                        </div>
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
