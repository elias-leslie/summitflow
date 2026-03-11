'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { type Task, updateTask } from '@/lib/api/tasks'
import {
  invalidateTaskQueries,
  syncTaskInTaskLists,
} from '@/lib/task-cache'

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
  const queryClient = useQueryClient()
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
      syncTaskInTaskLists(queryClient, projectId, updated)
      void invalidateTaskQueries(queryClient, projectId)
      setIsEditing(false)
      toast.success('Task details saved')
    } catch (err) {
      console.error('Failed to update task:', err)
      toast.error('Failed to save task details')
    }
  }, [task, projectId, editTitle, editDescription, onTaskUpdate, queryClient, setTask])

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
