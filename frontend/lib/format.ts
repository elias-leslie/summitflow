export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Format a timestamp as relative time with recency indicator.
 * Used for timeline events where recent items get special styling.
 */
export function formatTimestamp(timestamp: string): {
  time: string
  isRecent: boolean
} {
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) {
    const diffSecs = Math.floor(diffMs / 1000)
    return { time: `${diffSecs}s ago`, isRecent: true }
  }
  if (diffMins < 60) {
    return { time: `${diffMins}m ago`, isRecent: true }
  }
  return {
    time: date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }),
    isRecent: false,
  }
}

/**
 * Format a date string as relative time (days/weeks/months ago).
 * Returns "never" or "-" for null values depending on use case.
 */
export function formatTimeAgo(
  dateStr: string | null | undefined,
  fallback: string = '-',
): string {
  if (!dateStr) return fallback
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}

/**
 * Format duration in milliseconds to human-readable string.
 */
export function formatDuration(
  ms: number | null | undefined,
  fallback: string = '-',
): string {
  if (ms === undefined || ms === null) return fallback
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}
