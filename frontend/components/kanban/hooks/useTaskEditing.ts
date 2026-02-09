import { useState } from 'react'
import type { Task } from '@/lib/api'

interface UseTaskEditingProps {
  task: Task
  onTaskUpdate?: (taskId: string, updates: Partial<Task>) => void
}

interface UseTaskEditingReturn {
  isEditing: boolean
  editTitle: string
  editDescription: string
  setEditTitle: (title: string) => void
  setEditDescription: (description: string) => void
  handleEditStart: () => void
  handleEditCancel: () => void
  handleEditSave: () => void
}

export function useTaskEditing({
  task,
  onTaskUpdate,
}: UseTaskEditingProps): UseTaskEditingReturn {
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')

  const handleEditStart = () => {
    setEditTitle(task.title)
    setEditDescription(task.description || '')
    setIsEditing(true)
  }

  const handleEditCancel = () => {
    setIsEditing(false)
    setEditTitle('')
    setEditDescription('')
  }

  const handleEditSave = () => {
    onTaskUpdate?.(task.id, {
      title: editTitle,
      description: editDescription,
    })
    setIsEditing(false)
  }

  return {
    isEditing,
    editTitle,
    editDescription,
    setEditTitle,
    setEditDescription,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
  }
}
