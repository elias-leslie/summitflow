/**
 * Shared formatters for memory-related components.
 * Consolidates duplicate formatting logic from MemoryPage and MemoryStreamPanel.
 */

/**
 * Format an ISO date string to a human-readable time (e.g., "2:30 PM").
 */
export function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/**
 * Format duration in seconds to a human-readable string (e.g., "5m 30s").
 */
export function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

/**
 * Format token count with K suffix for thousands (e.g., "1.5k").
 */
export function formatTokens(tokens: number | null): string | null {
  if (tokens === null || tokens === undefined) return null;
  if (tokens === 0) return '0';
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return tokens.toString();
}

/**
 * Format age in minutes to human-readable (e.g., "5m", "2h", "3d").
 */
export function formatAge(minutes: number | null): string {
  if (minutes === null) return '-';
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  return `${Math.floor(minutes / 1440)}d`;
}

/**
 * Estimate token count for a string (rough approximation: 4 chars per token).
 */
export function estimateTokens(text: string | null | undefined): number {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}
