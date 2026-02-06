'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { DeleteTaskDialog } from '@/components/tasks/DeleteTaskDialog'
import { TaskModalContent } from '@/components/tasks/TaskModalContent'
import { TaskModalHeader } from '@/components/tasks/TaskModalHeader'
import { useTaskModal } from '@/components/tasks/useTaskModal'
import { Dialog, DialogClose, DialogContent } from '@/components/ui/dialog'
import type { Task } from '@/lib/api/tasks'
import { deleteTask } from '@/lib/api/tasks'

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
    isEditing,
    editTitle,
    editDescription,
    setEditDescription,
    isExecuting,
    isStopping,
    executionError,
    isTogglingAutonomous,
    descriptionOpen,
    subtasksOpen,
    timelineOpen,
    agentTimelineOpen,
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    setAgentTimelineOpen,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    handleStatusChange,
    handleSubtaskToggle,
    handleStartExecution,
    handleStopExecution,
    handleObjectiveEdit,
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
  const queryClient = useQueryClient()
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTask(projectId, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      onOpenChange(false)
      setDeleteConfirm(false)
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
        {/* Close button */}
        <DialogClose onClose={() => onOpenChange(false)} />

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
            {/* Header */}
            <TaskModalHeader
              task={task}
              isEditing={isEditing}
              editTitle={editTitle}
              onEditTitleChange={setEditTitle}
            />

            {/* Scrollable body */}
            <TaskModalContent
              task={task}
              projectId={projectId}
              subtasks={subtasks}
              isLoadingSubtasks={isLoadingSubtasks}
              isEditing={isEditing}
              editDescription={editDescription}
              isExecuting={isExecuting}
              isStopping={isStopping}
              isTogglingAutonomous={isTogglingAutonomous}
              executionError={executionError}
              descriptionOpen={descriptionOpen}
              subtasksOpen={subtasksOpen}
              timelineOpen={timelineOpen}
              agentTimelineOpen={agentTimelineOpen}
              onEditDescriptionChange={setEditDescription}
              onDescriptionToggle={() => setDescriptionOpen(!descriptionOpen)}
              onSubtasksToggle={() => setSubtasksOpen(!subtasksOpen)}
              onTimelineToggle={() => setTimelineOpen(!timelineOpen)}
              onAgentTimelineToggle={() =>
                setAgentTimelineOpen(!agentTimelineOpen)
              }
              onStartExecution={handleStartExecution}
              onStopExecution={handleStopExecution}
              onStatusChange={handleStatusChange}
              onToggleAutonomous={handleToggleAutonomous}
              onAgentOverrideChange={handleAgentOverrideChange}
              onEditStart={handleEditStart}
              onEditCancel={handleEditCancel}
              onEditSave={handleEditSave}
              onDelete={handleDeleteClick}
              onObjectiveEdit={handleObjectiveEdit}
              onSubtaskToggle={handleSubtaskToggle}
            />
          </>
        )}

        {/* Delete Confirmation Dialog */}
        {deleteConfirm && task && (
          <DeleteTaskDialog
            task={task}
            isDeleting={deleteMutation.isPending}
            isError={deleteMutation.isError}
            onConfirm={handleDeleteConfirm}
            onCancel={() => setDeleteConfirm(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
