interface BlockedTasksAlertProps {
  projectId: string
  onTaskClick?: (taskId: string) => void
}

export function BlockedTasksAlert({
  projectId: _projectId,
  onTaskClick: _onTaskClick,
}: BlockedTasksAlertProps) {
  // "blocked" status no longer exists — render nothing
  return null
}
