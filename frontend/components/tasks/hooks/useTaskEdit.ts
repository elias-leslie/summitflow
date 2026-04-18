'use client'

import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { type Task, updateTask } from '@/lib/api/tasks'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

interface UseTaskEditOptions {
  task: Task | null
  projectId: string
  onTaskUpdate?: (task: Task) => void
  setTask: (task: Task) => void
}

interface UseTaskEditReturn {
  isEditing: boolean
  editTitle: string
  editDescription: string
  setEditTitle: (title: string) => void
  setEditDescription: (description: string) => void
  handleEditStart: () => void
  handleEditCancel: () => void
  handleEditSave: () => Promise<void>
  resetEditState: () => void
}

export function useTaskEdit({
  task,
  projectId,
  onTaskUpdate,
  setTask,
}: UseTaskEditOptions): UseTaskEditReturn {
  const { syncUpdatedTask } = useTaskMutationSync(projectId)
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')

  const handleEditStart = useCallback(() => {
    if (!task) return
    setEditTitle(task.title)
    setEditDescription(task.description || '')
    setIsEditing(true)
  }, [task])

  const handleEditCancel = useCallback(() => {
    setIsEditing(false)
    setEditTitle('')
    setEditDescription('')
  }, [])

  const handleEditSave = useCallback(async () => {
    if (!task) return
    try {
      const updated = await updateTask(projectId, task.id, {
        title: editTitle,
        description: editDescription,
      })
      setTask(updated)
      onTaskUpdate?.(updated)
      syncUpdatedTask(updated)
      setIsEditing(false)
      toast.success('Task details saved')
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to save task details'))
    }
  }, [
    editDescription,
    editTitle,
    onTaskUpdate,
    projectId,
    setTask,
    syncUpdatedTask,
    task,
  ])

  const resetEditState = useCallback(() => {
    setIsEditing(false)
    setEditTitle('')
    setEditDescription('')
  }, [])

  return {
    isEditing,
    editTitle,
    editDescription,
    setEditTitle,
    setEditDescription,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    resetEditState,
  }
}
