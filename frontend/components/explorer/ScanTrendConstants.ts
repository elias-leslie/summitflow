/**
 * Constants for scan trend visualization
 */

export const TRIGGER_COLORS: Record<string, string> = {
  refactor_it: '#a855f7',
  og_refactor_it: '#a855f7',
  scheduled: '#22c55e',
  celery_beat: '#22c55e',
  daily_qa_scan: '#22c55e',
  manual: '#3b82f6',
  test: '#64748b',
}

export const TRIGGER_LABELS: Record<string, string> = {
  refactor_it: 'Refactor',
  og_refactor_it: 'Refactor',
  scheduled: 'Scheduled',
  celery_beat: 'Scheduled',
  daily_qa_scan: 'QA Scan',
  manual: 'Manual',
  test: 'Test',
}

export function getTriggerColor(trigger: string): string {
  return TRIGGER_COLORS[trigger] || '#64748b'
}

export function getTriggerLabel(trigger: string): string {
  return TRIGGER_LABELS[trigger] || trigger.replace(/_/g, ' ')
}
