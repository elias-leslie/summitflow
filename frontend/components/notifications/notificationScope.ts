/**
 * Global (all-project) notification calls for the top-bar bell outside
 * project pages. Project-scoped calls live in lib/api/notifications.
 */

import type { NotificationListResponse } from '@/lib/api/notifications'
import { buildQueryString, fetchWithErrorHandling } from '@/lib/api/utils'

export async function fetchGlobalNotifications(
  options: { limit?: number; offset?: number } = {},
): Promise<NotificationListResponse> {
  return fetchWithErrorHandling(
    `/api/notifications${buildQueryString(options)}`,
    { errorMessage: 'Failed to fetch notifications' },
  )
}

export async function fetchGlobalNotificationCount(): Promise<number> {
  const data = await fetchWithErrorHandling<{ pending: number }>(
    '/api/notifications/count',
    { errorMessage: 'Failed to fetch notification count' },
  )
  return data.pending
}

export async function dismissAllGlobalNotifications(): Promise<{
  dismissed: number
}> {
  return fetchWithErrorHandling('/api/notifications/dismiss-all', {
    method: 'POST',
    errorMessage: 'Failed to dismiss all notifications',
  })
}
