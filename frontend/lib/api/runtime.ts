import { buildApiUrl } from '../api-config'

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

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildApiUrl(path), init)
  if (!res.ok) {
    let detail = ''
    try {
      const payload = await res.json()
      detail =
        typeof payload?.detail === 'string'
          ? payload.detail
          : JSON.stringify(payload)
    } catch {
      detail = res.statusText
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

export const runtimeApi = {
  getStatus: () => fetchJson<RuntimeServiceStatus[]>('/api/docker/status'),
  getMetrics: () => fetchJson<RuntimeServiceMetrics[]>('/api/docker/metrics'),
  getHealth: () => fetchJson<HealthSummary>('/api/docker/health'),
  getRuntime: () => fetchJson<RuntimeModeStatus>('/api/docker/runtime'),
  getProxmoxStatus: () => fetchJson<ProxmoxStatus>('/api/docker/proxmox'),
  getLogs: (service: string, tail = 100) =>
    fetchJson<{ logs: string }>(`/api/docker/logs/${service}?tail=${tail}`),

  restart: (service: string) =>
    fetchJson<RuntimeActionResult>(`/api/docker/restart/${service}`, {
      method: 'POST',
    }),
  stop: (service: string) =>
    fetchJson<RuntimeActionResult>(`/api/docker/stop/${service}`, {
      method: 'POST',
    }),
  start: (service: string) =>
    fetchJson<RuntimeActionResult>(`/api/docker/start/${service}`, {
      method: 'POST',
    }),
  switchRuntimeMode: (mode: 'dev' | 'prod') =>
    fetchJson<RuntimeActionResult>('/api/docker/runtime', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    }),

  logStreamUrl: (service: string, tail = 100) =>
    buildApiUrl(`/api/docker/logs/${service}?follow=true&tail=${tail}`),
}
