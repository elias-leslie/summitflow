// Utility functions for autonomous settings

export function formatHour(hour: number): string {
  if (hour === 0) return '12 AM'
  if (hour === 12) return '12 PM'
  if (hour === 24) return '12 AM'
  if (hour < 12) return `${hour} AM`
  return `${hour - 12} PM`
}

export function isInTimeWindow(startHour: number, endHour: number): boolean {
  const now = new Date()
  const currentHour = now.getHours()

  // Handle 24/7 case
  if (startHour === 0 && endHour === 24) return true

  // Handle same-day window (e.g., 9am - 6pm)
  if (startHour < endHour) {
    return currentHour >= startHour && currentHour < endHour
  }

  // Handle overnight window (e.g., 10pm - 6am)
  return currentHour >= startHour || currentHour < endHour
}

export const TASK_TYPES = [
  { value: 'refactor', label: 'Refactor' },
  { value: 'bug', label: 'Bug' },
  { value: 'feature', label: 'Feature' },
  { value: 'chore', label: 'Chore' },
  { value: 'docs', label: 'Docs' },
]

export const MODEL_TIERS = [
  { value: 'standard', label: 'Standard', description: 'Balanced performance and cost' },
  { value: 'advanced', label: 'Advanced', description: 'Higher capability, higher cost' },
  { value: 'economy', label: 'Economy', description: 'Cost-optimized for simple tasks' },
]
