import { buildQueryString, fetchWithErrorHandling } from './utils'

export type MonitorAvailability =
  | 'ok'
  | 'unsupported'
  | 'permission_denied'
  | 'timeout'
  | 'error'
  | 'stale'
  | 'collector_stopped'
  | 'not_collected'
  | 'leaders_only'
  | 'retention_expired'

export interface MonitorEnvelope<T> {
  schema: number
  generated_at: string
  requested: Record<string, unknown>
  coverage: Record<string, unknown>
  items: T[]
  next_cursor: string | null
  truncated: boolean
  errors: unknown[]
}

export interface MonitorItem {
  sampled_at?: string
  measured_at?: string
  freshness?: string
  source?: string
  provider?: string
  mode?: string
  unit?: string
  availability?: MonitorAvailability
  metric?: string
  value?: unknown
  host?: Record<string, unknown>
  services?: Record<string, unknown> | unknown[]
  [key: string]: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function parseEnvelope(value: unknown): MonitorEnvelope<MonitorItem> {
  if (
    !isRecord(value) ||
    value.schema !== 1 ||
    typeof value.generated_at !== 'string'
  ) {
    throw new Error('Monitor returned an invalid response')
  }
  const rawItems = value.items
  if (!Array.isArray(rawItems)) {
    throw new Error('Monitor returned invalid items')
  }
  if (!rawItems.every(isRecord)) {
    throw new Error('Monitor returned invalid items')
  }
  const items = rawItems as MonitorItem[]
  return {
    schema: value.schema,
    generated_at: value.generated_at,
    requested: isRecord(value.requested) ? value.requested : {},
    coverage: isRecord(value.coverage) ? value.coverage : {},
    items,
    next_cursor:
      typeof value.next_cursor === 'string' ? value.next_cursor : null,
    truncated: value.truncated === true,
    errors: Array.isArray(value.errors) ? value.errors : [],
  }
}

async function get(path: string): Promise<MonitorEnvelope<MonitorItem>> {
  const payload = await fetchWithErrorHandling<unknown>(path, {
    errorMessage: 'Failed to load host monitor',
  })
  return parseEnvelope(payload)
}

export const monitorApi = {
  status: () => get('/api/monitor/v1/status?max_bytes=65536'),
  series: (params: {
    metric: string
    entity?: string
    since: string
    until: string
    step: number
    limit: number
  }) =>
    get(
      `/api/monitor/v1/series${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  processes: (params: {
    at?: string
    sort: string
    service?: string
    limit: number
    cursor?: string
  }) =>
    get(
      `/api/monitor/v1/processes${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  events: (params: { since: string; limit: number }) =>
    get(
      `/api/monitor/v1/events${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  diagnostics: (
    kind: 'sensors' | 'system-info' | 'startup' | 'users' | 'apps' | 'drivers',
    limit = 50,
    options?: { provider?: 'dpkg' | 'snap' | 'flatpak'; cursor?: string },
  ) =>
    get(
      `/api/monitor/v1/${kind}${buildQueryString({ limit: kind === 'system-info' ? undefined : limit, ...options, max_bytes: 65536 })}`,
    ),
  logs: (params: {
    service: string
    since?: string
    until?: string
    priority?: number
    limit: number
  }) =>
    get(
      `/api/monitor/v1/logs${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  connections: (params: {
    show_addresses: boolean
    include_process: boolean
    limit: number
  }) =>
    get(
      `/api/monitor/v1/connections${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  diskSpace: (params: {
    path: string
    max_entries: number
    max_depth: number
    timeout_seconds: number
    limit: number
  }) =>
    get(
      `/api/monitor/v1/disk-space${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  benchmark: async (params: {
    kind: 'cpu' | 'disk'
    duration_seconds: number
  }) =>
    parseEnvelope(
      await fetchWithErrorHandling<unknown>('/api/monitor/v1/benchmark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...params, max_bytes: 4096 }),
        errorMessage: 'Benchmark failed',
      }),
    ),
  exportPage: (params: {
    since: string
    until: string
    cursor?: string
    limit: number
  }) =>
    get(
      `/api/monitor/v1/export${buildQueryString({ ...params, max_bytes: 65536 })}`,
    ),
  capture: () =>
    fetchWithErrorHandling<unknown>('/api/monitor/v1/capture', {
      method: 'POST',
      errorMessage: 'Failed to start detail capture',
    }),
}
