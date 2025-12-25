/**
 * Notifications API - user notification management
 */

import { fetchWithErrorHandling, buildQueryString } from "./utils";

// ============================================================================
// Notification Types
// ============================================================================

export interface Notification {
  id: string;
  project_id: string;
  task_id: string | null;
  type: "task_failed" | "task_needs_input" | "task_completed" | "system";
  title: string;
  message: string;
  severity: "info" | "warning" | "error" | "critical";
  status: "pending" | "read" | "dismissed";
  metadata: Record<string, unknown>;
  created_at: string | null;
  read_at: string | null;
  dismissed_at: string | null;
}

export interface NotificationListResponse {
  items: Notification[];
  total: number;
  pending_count: number;
}

// ============================================================================
// Notification API Functions
// ============================================================================

export async function fetchNotifications(
  projectId: string,
  options: { status?: string; limit?: number; offset?: number; include_dismissed?: boolean } = {}
): Promise<NotificationListResponse> {
  const query = buildQueryString(options);
  return fetchWithErrorHandling(`/api/projects/${projectId}/notifications${query}`, {
    errorMessage: "Failed to fetch notifications",
  });
}

export async function fetchNotificationCount(projectId: string): Promise<number> {
  const data = await fetchWithErrorHandling<{ pending: number }>(
    `/api/projects/${projectId}/notifications/count`,
    { errorMessage: "Failed to fetch notification count" }
  );
  return data.pending;
}

export async function markNotificationRead(projectId: string, notificationId: string): Promise<Notification> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/notifications/${notificationId}/read`, {
    method: "PATCH",
    errorMessage: "Failed to mark notification as read",
  });
}

export async function dismissNotification(projectId: string, notificationId: string): Promise<Notification> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/notifications/${notificationId}/dismiss`, {
    method: "PATCH",
    errorMessage: "Failed to dismiss notification",
  });
}
