/**
 * Utility functions for scan trend calculations
 */

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function calculateTimeWindow(scans: { started_at: string }[]): {
  start: number
  end: number
} {
  const now = Date.now()
  const DAY_MS = 24 * 60 * 60 * 1000
  const MIN_WINDOW = DAY_MS
  const MAX_WINDOW = 30 * DAY_MS

  if (scans.length === 0) return { start: now - MAX_WINDOW, end: now }

  const timestamps = scans.map((s) => new Date(s.started_at).getTime())
  const oldest = Math.min(...timestamps)
  const newest = Math.max(...timestamps)
  const padding = Math.max((newest - oldest) * 0.15, 2 * 60 * 60 * 1000)

  let windowStart = oldest - padding
  let windowEnd = Math.min(newest + padding, now)

  if (windowEnd - windowStart < MIN_WINDOW) {
    const center = (windowStart + windowEnd) / 2
    windowStart = center - MIN_WINDOW / 2
    windowEnd = Math.min(center + MIN_WINDOW / 2, now)
    if (windowEnd - windowStart < MIN_WINDOW)
      windowStart = windowEnd - MIN_WINDOW
  }

  if (windowEnd - windowStart > MAX_WINDOW) windowStart = windowEnd - MAX_WINDOW

  return { start: windowStart, end: windowEnd }
}

export function getTimePosition(
  timestamp: number,
  start: number,
  end: number,
): number {
  const size = end - start
  if (size <= 0) return 50
  return Math.max(0, Math.min(100, ((timestamp - start) / size) * 100))
}
