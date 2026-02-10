import { useEffect, useState } from 'react'
import { fetchTask, type Notification, type Task } from '@/lib/api'

export function useTaskDetails(
  notification: Notification | null,
  projectId: string,
) {
  const [taskDetails, setTaskDetails] = useState<Task | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (notification?.task_id) {
      setLoading(true)
      fetchTask(projectId, notification.task_id)
        .then(setTaskDetails)
        .catch(() => setTaskDetails(null))
        .finally(() => setLoading(false))
    } else {
      setTaskDetails(null)
    }
  }, [notification, projectId])

  return { taskDetails, loading }
}
