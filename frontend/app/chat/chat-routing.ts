import { DEFAULT_PROJECT_ID } from '@/lib/project-config'

interface SearchParamsLike {
  get(name: string): string | null
}

interface ChatUrlOptions {
  projectId?: string
  taskId?: string | null
  notificationId?: string | null
}

export function getChatProjectId(searchParams: SearchParamsLike): string {
  return searchParams.get('project_id')?.trim() || DEFAULT_PROJECT_ID
}

export function buildChatUrl({
  projectId = DEFAULT_PROJECT_ID,
  taskId,
  notificationId,
}: ChatUrlOptions): string {
  const params = new URLSearchParams()

  params.set('project_id', projectId)

  if (taskId) {
    params.set('task_id', taskId)
  }

  if (notificationId) {
    params.set('notification_id', notificationId)
  }

  return `/chat?${params.toString()}`
}

export function buildProjectTaskUrl(projectId: string, taskId: string): string {
  return `/projects/${projectId}/tasks/${taskId}`
}
