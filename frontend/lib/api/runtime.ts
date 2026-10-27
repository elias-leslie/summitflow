import { fetchWithErrorHandling, postJson } from './utils'

export interface RuntimeServiceStatus {
  name: string
  service: string
  display_name: string
  manager: 'docker' | 'systemd'
  category: 'app' | 'worker' | 'infra'
  state: string
  health: string
  status: string
  ports: string[]
  // systemd boot auto-start: true=enabled, false=disabled, null=not togglable.
  auto_start: boolean | null
  // false when the dashboard cannot control this unit; status explains why.
  controllable?: boolean
  log_streaming?: boolean
  location?: string | null
}

export interface RuntimeServiceMetrics {
  name: string
  service: string
  cpu_percent: string
  mem_usage: string
  mem_percent: string
  net_io: string
  block_io: string
}

export interface RuntimeMetricSample {
  sampled_at: string
  sample_count: number
  state: string | null
  status: string | null
  cpu_percent: number | null
  cpu_percent_max: number | null
  memory_percent: number | null
  memory_percent_max: number | null
  memory_used_bytes: number | null
  memory_used_bytes_max: number | null
  memory_limit_bytes: number | null
  raw_mem_usage: string | null
  net_io: string | null
  block_io: string | null
}

export interface RuntimeMetricSeries {
  service: string
  display_name: string
  manager: string
  category: string
  samples: RuntimeMetricSample[]
}

export interface HealthSummary {
  total: number
  healthy: number
  unhealthy: number
  running: number
  stopped: number
}

export interface RuntimeActionResult {
  success: boolean
  message: string
}

export interface GpuProcess {
  pid: number
  name: string
  command: string | null
  used_mb: number | null
  type: string
}

export interface GpuDevice {
  index: number
  name: string
  utilization_percent: number | null
  memory_total_mb: number
  memory_used_mb: number
  memory_free_mb: number
  memory_percent_used: number
  temperature_c: number | null
  power_draw_w: number | null
  power_limit_w: number | null
  status: 'ok' | 'warning' | 'critical'
  processes: GpuProcess[]
}

export interface GpuStatus {
  available: boolean
  error: string | null
  devices: GpuDevice[]
  timestamp: string
}

export interface RuntimeModeStatus {
  runtime: 'docker' | 'docker-stopped' | 'native' | 'hybrid'
  apps_runtime: 'docker' | 'native' | 'stopped'
  infra_runtime: 'docker' | 'native' | 'stopped'
  current_mode: 'dev' | 'prod'
  configured_mode: 'dev' | 'prod'
  default_mode: 'dev' | 'prod'
  source: 'detected' | 'persisted' | 'default'
  is_running: boolean
}

export interface ProxmoxNodeStatus {
  node: string
  status: string
  cpu_percent: number | null
  memory_used_bytes: number | null
  memory_total_bytes: number | null
  uptime_seconds: number | null
}

export interface ProxmoxGuestStatus {
  vmid: number
  name: string
  node: string
  type: 'qemu' | 'lxc'
  status: string
  cpu_percent: number | null
  memory_used_bytes: number | null
  memory_total_bytes: number | null
  uptime_seconds: number | null
  tags: string[]
  onboot?: boolean | null
}

export interface ProxmoxStatus {
  configured: boolean
  reachable: boolean
  api_url: string | null
  error: string | null
  nodes: ProxmoxNodeStatus[]
  guests: ProxmoxGuestStatus[]
}

export interface MaintenanceRun {
  id: number
  workflow_name: string
  status: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  rows_cleaned: number
  summary: Record<string, unknown>
  error_message: string | null
  created_at: string
}

export interface DisruptionAgent {
  agent: string
  provider: string | null
  project: string | null
  source: string
}

export interface DisruptionHandshake {
  id: string
  to: string
  from: string
  state: string
  reply: 'none' | 'yes' | 'no' | 'eta' | 'withdrawn'
  acked_by: string | null
  note: string | null
  eta_until: string | null
  eta_running: boolean
  created: string
}

export interface DisruptionHold {
  project: string
  holder: string
  kind: 'hold' | 'op'
  purpose: string | null
  since: string
}

export interface HostDisruption {
  target: string
  host: string
  generated_at: string
  clear: boolean
  blocking: string[]
  unknown: string[]
  agents: DisruptionAgent[]
  handshakes: DisruptionHandshake[]
  holds: DisruptionHold[]
  leases: { project: string; holder: string; paths: number }[]
  backups: {
    summitflow: { id: string; source_id: string | null }[]
    units: string[]
    processes: string[]
  }
}

export interface CleanupSetting {
  name: string
  value: number
  default: number
  saved: boolean
  min: number
  max: number
}

export interface MaintenanceStatus {
  latest: Record<string, MaintenanceRun>
  recent: MaintenanceRun[]
}

function apiUrl(path: string): string {
  // Keep runtime traffic same-origin so Next can proxy protected actions/logs
  // and inject the internal service secret server-side, including SSE requests.
  return path
}

function queryString(
  params: Record<string, string | number | undefined>,
): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) search.set(key, String(value))
  })
  const value = search.toString()
  return value ? `?${value}` : ''
}

export const runtimeApi = {
  getStatus: () =>
    fetchWithErrorHandling<RuntimeServiceStatus[]>(
      apiUrl('/api/docker/status'),
      {
        errorMessage: 'Failed to fetch runtime status',
      },
    ),
  getMetrics: () =>
    fetchWithErrorHandling<RuntimeServiceMetrics[]>(
      apiUrl('/api/docker/metrics'),
      {
        errorMessage: 'Failed to fetch runtime metrics',
      },
    ),
  getMetricHistory: (params?: {
    service?: string
    manager?: string
    category?: string
    sinceMinutes?: number
    bucketSeconds?: number
    limit?: number
  }) =>
    fetchWithErrorHandling<RuntimeMetricSeries[]>(
      apiUrl(
        `/api/docker/metrics/history${queryString({
          service: params?.service,
          manager: params?.manager,
          category: params?.category,
          since_minutes: params?.sinceMinutes,
          bucket_seconds: params?.bucketSeconds,
          limit: params?.limit,
        })}`,
      ),
      {
        errorMessage: 'Failed to fetch runtime metric history',
      },
    ),
  getHealth: () =>
    fetchWithErrorHandling<HealthSummary>(apiUrl('/api/docker/health'), {
      errorMessage: 'Failed to fetch health summary',
    }),
  getRuntime: () =>
    fetchWithErrorHandling<RuntimeModeStatus>(apiUrl('/api/docker/runtime'), {
      errorMessage: 'Failed to fetch runtime mode',
    }),
  getProxmoxStatus: () =>
    fetchWithErrorHandling<ProxmoxStatus>(apiUrl('/api/docker/proxmox'), {
      errorMessage: 'Failed to fetch Proxmox status',
    }),
  controlProxmoxGuest: (
    node: string,
    guestType: 'qemu' | 'lxc',
    vmid: number,
    action: 'start' | 'stop' | 'shutdown' | 'reboot',
  ) =>
    fetchWithErrorHandling<{
      status: string
      node: string
      guest_type: 'qemu' | 'lxc'
      action: string
      vmid: number
      task?: string
    }>(
      apiUrl(
        `/api/docker/proxmox/guests/${node}/${guestType}/${vmid}/${action}`,
      ),
      {
        method: 'POST',
        errorMessage: `Failed to ${action} Proxmox guest ${vmid}`,
      },
    ),
  setProxmoxGuestAutoStart: (
    node: string,
    guestType: 'qemu' | 'lxc',
    vmid: number,
    enabled: boolean,
  ) =>
    fetchWithErrorHandling<{
      status: string
      node: string
      vmid: number
      onboot: boolean
    }>(
      apiUrl(
        `/api/docker/proxmox/guests/${node}/${guestType}/${vmid}/autostart`,
      ),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
        errorMessage: `Failed to set auto-start for Proxmox guest ${vmid}`,
      },
    ),
  getHostDisruption: () =>
    fetchWithErrorHandling<HostDisruption>(apiUrl('/api/system/disruption'), {
      errorMessage: 'Failed to check whether the host can be disrupted',
    }),
  getCleanupSettings: () =>
    fetchWithErrorHandling<{ settings: CleanupSetting[] }>(
      apiUrl('/api/system/cleanup-settings'),
      { errorMessage: 'Failed to load cleanup settings' },
    ),
  saveCleanupSettings: (values: Record<string, number | null>) =>
    fetchWithErrorHandling<{ settings: CleanupSetting[] }>(
      apiUrl('/api/system/cleanup-settings'),
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
        errorMessage: 'Failed to save cleanup settings',
      },
    ),
  getMaintenanceStatus: () =>
    fetchWithErrorHandling<MaintenanceStatus>(
      apiUrl('/api/system/maintenance'),
      {
        errorMessage: 'Failed to fetch maintenance status',
      },
    ),
  getLogs: (service: string, tail = 100) =>
    fetchWithErrorHandling<{ logs: string }>(
      apiUrl(`/api/docker/logs/${service}?tail=${tail}`),
      {
        errorMessage: 'Failed to fetch service logs',
      },
    ),

  restart: (service: string) =>
    fetchWithErrorHandling<RuntimeActionResult>(
      apiUrl(`/api/docker/restart/${service}`),
      {
        method: 'POST',
        errorMessage: 'Failed to restart service',
      },
    ),
  stop: (service: string) =>
    fetchWithErrorHandling<RuntimeActionResult>(
      apiUrl(`/api/docker/stop/${service}`),
      {
        method: 'POST',
        errorMessage: 'Failed to stop service',
      },
    ),
  start: (service: string) =>
    fetchWithErrorHandling<RuntimeActionResult>(
      apiUrl(`/api/docker/start/${service}`),
      {
        method: 'POST',
        errorMessage: 'Failed to start service',
      },
    ),
  enableAutostart: (service: string) =>
    fetchWithErrorHandling<RuntimeActionResult>(
      apiUrl(`/api/docker/enable/${service}`),
      {
        method: 'POST',
        errorMessage: 'Failed to enable auto-start',
      },
    ),
  disableAutostart: (service: string) =>
    fetchWithErrorHandling<RuntimeActionResult>(
      apiUrl(`/api/docker/disable/${service}`),
      {
        method: 'POST',
        errorMessage: 'Failed to disable auto-start',
      },
    ),
  getGpuStatus: () =>
    fetchWithErrorHandling<GpuStatus>(apiUrl('/api/system/gpu'), {
      errorMessage: 'Failed to fetch GPU status',
    }),
  switchRuntimeMode: (mode: 'dev' | 'prod') =>
    postJson<RuntimeActionResult>(
      apiUrl('/api/docker/runtime'),
      { mode },
      'Failed to switch runtime mode',
    ),

  logStreamUrl: (service: string, tail = 100) =>
    apiUrl(`/api/docker/logs/${service}?follow=true&tail=${tail}`),
}
