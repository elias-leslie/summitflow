/**
 * Shared formatters for Explorer components
 *
 * Centralized formatting utilities to avoid duplication across Row/Detail components.
 * Time/duration formatters re-exported from lib/format.ts for convenience.
 */

export { formatDuration, formatTimeAgo } from '@/lib/format'

export function formatNumber(n: number | undefined | null): string {
  return (n ?? 0).toLocaleString()
}

export function formatPercent(n: number | undefined | null): string {
  if (n === undefined || n === null) return '-'
  return `${n.toFixed(1)}%`
}

export function formatBytes(bytes: number | undefined | null): string {
  const b = bytes ?? 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}
