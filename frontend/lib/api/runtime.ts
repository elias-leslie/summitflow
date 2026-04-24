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

export interface MaintenanceStatus {
  latest: Record<string, MaintenanceRun>
  recent: MaintenanceRun[]
}

export interface LiveSessionStatus {
  id: string
  kind: 'browser'
  state: 'active' | 'expired' | 'closed'
  target_url: string
  current_url: string | null
  title: string | null
  sensitive: boolean
  created_at: string
  expires_at: string
  viewport_width: number
  viewport_height: number
  control_policy: string
  capture_policy: string
}

export interface LiveSessionFrame {
  session_id: string
  captured_at: string
  image_data_url: string
  viewport_width: number
  viewport_height: number
  sensitive: boolean
}

export type LiveSessionControl =
  | { action: 'click'; x: number; y: number }
  | { action: 'key'; key: string }
  | { action: 'text'; text: string }
  | { action: 'wheel'; x: number; y: number; delta_x: number; delta_y: number }
  | { action: 'navigate'; target_url: string }
  | { action: 'resize'; viewport_width: number; viewport_height: number }

function apiUrl(path: string): string {
  // Keep runtime traffic same-origin so Next can proxy protected actions/logs
  // and inject the internal service secret server-side, including SSE requests.
  return path
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
  switchRuntimeMode: (mode: 'dev' | 'prod') =>
    postJson<RuntimeActionResult>(
      apiUrl('/api/docker/runtime'),
      { mode },
      'Failed to switch runtime mode',
    ),

  listLiveSessions: () =>
    fetchWithErrorHandling<LiveSessionStatus[]>(
      apiUrl('/api/docker/live-sessions'),
      {
        errorMessage: 'Failed to fetch live sessions',
      },
    ),
  createLiveSession: (
    targetUrl = 'https://www.amazon.com/photos/all',
    viewportWidth = 1440,
    viewportHeight = 900,
  ) =>
    postJson<LiveSessionStatus>(
      apiUrl('/api/docker/live-sessions'),
      {
        kind: 'browser',
        target_url: targetUrl,
        viewport_width: viewportWidth,
        viewport_height: viewportHeight,
      },
      'Failed to create live browser session',
    ),
  getLiveSession: (sessionId: string) =>
    fetchWithErrorHandling<LiveSessionStatus>(
      apiUrl(`/api/docker/live-sessions/${sessionId}`),
      {
        errorMessage: 'Failed to fetch live session',
      },
    ),
  getLiveSessionFrame: (sessionId: string) =>
    fetchWithErrorHandling<LiveSessionFrame>(
      apiUrl(`/api/docker/live-sessions/${sessionId}/frame`),
      {
        cache: 'no-store',
        errorMessage: 'Failed to fetch live session frame',
      },
    ),
  controlLiveSession: (sessionId: string, control: LiveSessionControl) =>
    postJson<LiveSessionStatus>(
      apiUrl(`/api/docker/live-sessions/${sessionId}/control`),
      control,
      'Failed to control live session',
    ),
  setLiveSessionSensitive: (sessionId: string, sensitive: boolean) =>
    postJson<LiveSessionStatus>(
      apiUrl(`/api/docker/live-sessions/${sessionId}/sensitive`),
      { sensitive },
      'Failed to update live session sensitivity',
    ),
  teardownLiveSession: (sessionId: string) =>
    postJson<LiveSessionStatus>(
      apiUrl(`/api/docker/live-sessions/${sessionId}/teardown`),
      {},
      'Failed to close live session',
    ),

  logStreamUrl: (service: string, tail = 100) =>
    apiUrl(`/api/docker/logs/${service}?follow=true&tail=${tail}`),
}
