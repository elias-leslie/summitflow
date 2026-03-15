/**
 * Docker management API client.
 * Wraps /api/docker/* endpoints for the Docker dashboard.
 */

import { buildApiUrl } from '../api-config'

export interface ContainerStatus {
  name: string
  service: string
  state: string
  health: string
  status: string
  ports: string[]
}

export interface ContainerMetrics {
  name: string
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

export interface BackupInfo {
  filename: string
  size_mb: number
  created: string
}

export interface ActionResult {
  success: boolean
  message: string
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildApiUrl(path), init)
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

export const dockerApi = {
  getStatus: () => fetchJson<ContainerStatus[]>('/api/docker/status'),
  getMetrics: () => fetchJson<ContainerMetrics[]>('/api/docker/metrics'),
  getHealth: () => fetchJson<HealthSummary>('/api/docker/health'),
  getLogs: (service: string, tail = 100) =>
    fetchJson<{ logs: string }>(`/api/docker/logs/${service}?tail=${tail}`),
  getBackups: () => fetchJson<BackupInfo[]>('/api/docker/backups'),

  restart: (service: string) =>
    fetchJson<ActionResult>(`/api/docker/restart/${service}`, { method: 'POST' }),
  stop: (service: string) =>
    fetchJson<ActionResult>(`/api/docker/stop/${service}`, { method: 'POST' }),
  start: (service: string) =>
    fetchJson<ActionResult>(`/api/docker/start/${service}`, { method: 'POST' }),

  backup: (note = '') =>
    fetchJson<ActionResult>(`/api/docker/backup?note=${encodeURIComponent(note)}`, {
      method: 'POST',
    }),
  restore: (filename: string) =>
    fetchJson<ActionResult>('/api/docker/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
    }),

  /** SSE log stream URL for EventSource */
  logStreamUrl: (service: string, tail = 100) =>
    buildApiUrl(`/api/docker/logs/${service}?follow=true&tail=${tail}`),
}
