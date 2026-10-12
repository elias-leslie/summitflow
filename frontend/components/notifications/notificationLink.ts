import type { Notification } from '@/lib/api/notifications'

/** In-app page a notification is about, or null when none applies. */
export function notificationHref(notification: Notification): string | null {
  const meta = notification.metadata ?? {}
  if (
    typeof meta.url === 'string' &&
    meta.url.startsWith('/') &&
    !meta.url.startsWith('//')
  ) {
    return meta.url
  }
  if (notification.task_id) {
    return `/projects/${encodeURIComponent(notification.project_id)}?task=${encodeURIComponent(notification.task_id)}`
  }
  if (meta.nightly_publication) return '/git'
  if (
    meta.backup_alert ||
    meta.backend_id ||
    String(meta.dedupe_key ?? '').startsWith('backup-alert:')
  ) {
    return '/backups'
  }
  if (meta.source === 'host-guardian' || meta.health_transition) {
    return '/runtime'
  }
  return null
}
