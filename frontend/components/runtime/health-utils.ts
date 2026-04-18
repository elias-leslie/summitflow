/**
 * Shared health/status color utilities for runtime components.
 */

export type HealthTone =
  | 'healthy'
  | 'unhealthy'
  | 'warning'
  | 'stopped'
  | 'unknown'

export function resolveHealthTone(state: string, health: string): HealthTone {
  if (health === 'healthy') return 'healthy'
  if (health === 'unhealthy') return 'unhealthy'
  if (state === 'running' || state === 'online') return 'warning'
  if (state === 'exited' || state === 'stopped' || state === 'offline')
    return 'stopped'
  return 'unknown'
}

const borderColors: Record<HealthTone, string> = {
  healthy: 'border-emerald-500/40',
  unhealthy: 'border-red-500/40',
  warning: 'border-amber-500/40',
  stopped: 'border-slate-700',
  unknown: 'border-slate-700',
}

const dotColors: Record<HealthTone, string> = {
  healthy: 'bg-emerald-500',
  unhealthy: 'bg-red-500',
  warning: 'bg-amber-500',
  stopped: 'bg-slate-500',
  unknown: 'bg-slate-600',
}

const leftAccentColors: Record<HealthTone, string> = {
  healthy: 'border-l-emerald-500',
  unhealthy: 'border-l-red-500',
  warning: 'border-l-amber-500',
  stopped: 'border-l-slate-600',
  unknown: 'border-l-slate-700',
}

const textColors: Record<HealthTone, string> = {
  healthy: 'text-emerald-400',
  unhealthy: 'text-red-400',
  warning: 'text-amber-400',
  stopped: 'text-slate-500',
  unknown: 'text-slate-500',
}

export function healthBorderClass(tone: HealthTone): string {
  return borderColors[tone]
}

export function healthDotClass(tone: HealthTone): string {
  return dotColors[tone]
}

export function healthAccentClass(tone: HealthTone): string {
  return leftAccentColors[tone]
}

export function healthTextClass(tone: HealthTone): string {
  return textColors[tone]
}

export function healthLabel(state: string, health: string): string {
  if (health) return health
  return state
}

export function managerLabel(manager: 'docker' | 'systemd'): string {
  return manager === 'systemd' ? 'native' : 'docker'
}

export function formatBytes(value: number | null): string {
  if (value == null || Number.isNaN(value)) return 'n/a'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let current = value
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return unitIndex === 0
    ? `${Math.round(current)}${units[unitIndex]}`
    : `${current.toFixed(1)}${units[unitIndex]}`
}

export function formatUptime(seconds: number | null): string {
  if (seconds == null || seconds < 0) return 'n/a'
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  if (days > 0) return `${days}d ${hours}h`
  const minutes = Math.floor((seconds % 3_600) / 60)
  return `${hours}h ${minutes}m`
}
