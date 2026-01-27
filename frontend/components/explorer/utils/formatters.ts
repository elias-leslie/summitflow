/**
 * Shared formatters for Explorer components
 *
 * Centralized formatting utilities to avoid duplication across Row/Detail components.
 */

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

export function formatTimeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}

export function formatDuration(ms: number | undefined | null): string {
  if (ms === undefined || ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}
