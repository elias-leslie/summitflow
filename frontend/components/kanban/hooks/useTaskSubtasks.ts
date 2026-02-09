import { useEffect, useState } from 'react'
import { getSubtasksWithSteps, type Subtask } from '@/lib/api/tasks'

interface UseTaskSubtasksProps {
  projectId: string
  taskId: string | undefined
  open: boolean
}

interface UseTaskSubtasksReturn {
  subtasks: Subtask[]
  isLoadingSubtasks: boolean
  setSubtasks: React.Dispatch<React.SetStateAction<Subtask[]>>
}

export function useTaskSubtasks({
  projectId,
  taskId,
  open,
}: UseTaskSubtasksProps): UseTaskSubtasksReturn {
  const [subtasks, setSubtasks] = useState<Subtask[]>([])
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(false)

  useEffect(() => {
    if (!open || !taskId) {
      return
    }

    setIsLoadingSubtasks(true)
    getSubtasksWithSteps(projectId, taskId)
      .then((response) => {
        setSubtasks(response.subtasks)
      })
      .catch((err) => {
        console.error('Failed to fetch subtasks:', err)
        setSubtasks([])
      })
      .finally(() => {
        setIsLoadingSubtasks(false)
      })
  }, [open, taskId, projectId])

  return {
    subtasks,
    isLoadingSubtasks,
    setSubtasks,
  }
}
