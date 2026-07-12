'use client'

import { useMutation } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import { TaskModalContent } from '@/components/tasks/TaskModalContent'
import { TaskModalHeader } from '@/components/tasks/TaskModalHeader'
import { useTaskModal } from '@/components/tasks/useTaskModal'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Task } from '@/lib/api/tasks'
import { deleteTask } from '@/lib/api/tasks'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

interface TaskModalProps {
  taskId: string | null
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onTaskUpdate?: (task: Task) => void
  /** Initial task data to avoid refetch if available */
  initialTask?: Task | null
}

export function TaskModal({
  taskId,
  projectId,
  open,
  onOpenChange,
  onTaskUpdate,
  initialTask,
}: TaskModalProps) {
  const {
    task,
    subtasks,
    isLoading,
    isLoadingSubtasks,
    error,
    subtasksError,
    isEditing,
    editTitle,
    editDescription,
    setEditDescription,
    isExecuting,
    isStopping,
    executionError,
    isTogglingAutonomous,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    handleStatusChange,
    handleSubtaskToggle,
    handleStartExecution,
    handleStopExecution,
    handleToggleAutonomous,
    handleAgentOverrideChange,
    setEditTitle,
  } = useTaskModal({
    taskId,
    projectId,
    open,
    initialTask,
    onTaskUpdate,
  })

  // Delete state and handlers
  const { syncDeletedTask } = useTaskMutationSync(projectId)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTask(projectId, id),
    onSuccess: (_, deletedTaskId) => {
      syncDeletedTask(deletedTaskId)
      onOpenChange(false)
      setDeleteConfirm(false)
      toast.success('Task deleted')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, 'Failed to delete task'))
    },
  })

  const handleDeleteClick = () => {
    setDeleteConfirm(true)
  }

  const handleDeleteConfirm = () => {
    if (taskId) {
      deleteMutation.mutate(taskId)
    }
  }

  // Don't render if no task ID
  if (!taskId) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
        data-testid="task-modal"
      >
        <DialogTitle className="sr-only">
          {task?.title ?? 'Task details'}
        </DialogTitle>
        <DialogDescription className="sr-only">
          View task status, execution details, activity, and editing controls.
        </DialogDescription>
        <DialogClose />

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-slate-500" />
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <div className="p-6">
            <div className="p-4 bg-red-950/30 border border-red-800/30 rounded-lg">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          </div>
        )}

        {/* Task content */}
        {task && !isLoading && !error && (
          <>
            {/* Header with integrated action bar */}
            <TaskModalHeader
              task={task}
              isEditing={isEditing}
              editTitle={editTitle}
              onEditTitleChange={setEditTitle}
              isExecuting={isExecuting}
              isStopping={isStopping}
              isTogglingAutonomous={isTogglingAutonomous}
              onStartExecution={handleStartExecution}
              onStopExecution={handleStopExecution}
              onStatusChange={handleStatusChange}
              onToggleAutonomous={handleToggleAutonomous}
              onAgentOverrideChange={handleAgentOverrideChange}
              onEditStart={handleEditStart}
              onEditCancel={handleEditCancel}
              onEditSave={handleEditSave}
              onDelete={handleDeleteClick}
            />

            {/* Tabbed body */}
            <TaskModalContent
              task={task}
              projectId={projectId}
              subtasks={subtasks}
              isLoadingSubtasks={isLoadingSubtasks}
              subtasksError={subtasksError}
              isEditing={isEditing}
              editDescription={editDescription}
              executionError={executionError}
              onEditDescriptionChange={setEditDescription}
              onSubtaskToggle={handleSubtaskToggle}
            />
          </>
        )}

        {/* Delete Confirmation Dialog */}
        {deleteConfirm && task && (
          <ConfirmDeleteDialog
            entityType="task"
            entityName={`${task.id}: ${task.title}`}
            isDeleting={deleteMutation.isPending}
            isError={deleteMutation.isError}
            onConfirm={handleDeleteConfirm}
            onCancel={() => setDeleteConfirm(false)}
            zIndex="z-[60]"
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
