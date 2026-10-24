// Values match the backend's Frequency literal (api/backups/models.py).
export const FREQUENCY_OPTIONS = [
  { value: 'hourly', label: 'Hourly' },
  { value: 'four_hourly', label: 'Every 4 hours' },
  { value: 'daily', label: 'Daily, in the nightly window' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
] as const

const RETENTION_DAYS = [7, 14, 30, 60, 90]

export function frequencyLabel(value: string): string {
  return (
    FREQUENCY_OPTIONS.find((option) => option.value === value)?.label ?? value
  )
}

export function retentionLabel(days: number): string {
  return days >= 3650 && days % 365 === 0
    ? `${days / 365} years`
    : `${days} days`
}

/** The standard choices plus the source's current value when it is unusual. */
export function retentionChoices(current: number): number[] {
  return RETENTION_DAYS.includes(current)
    ? RETENTION_DAYS
    : [...RETENTION_DAYS, current].sort((a, b) => a - b)
}
