'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { CriteriaProgress } from '@/components/tasks/CriteriaProgress'
import { ExecutionTimeline } from '@/components/tasks/ExecutionTimeline'
import { LinkedCapabilitySection } from '@/components/tasks/LinkedCapabilitySection'
import { ObjectiveSection } from '@/components/tasks/ObjectiveSection'
import { SubtasksSection } from '@/components/tasks/SubtasksSection'
import { TaskMetadata } from '@/components/tasks/TaskMetadata'
import { TaskModalActions } from '@/components/tasks/TaskModalActions'
import { TaskModalHeader } from '@/components/tasks/TaskModalHeader'
import { useTaskModal } from '@/components/tasks/useTaskModal'
import { Dialog, DialogClose, DialogContent } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import type { Task } from '@/lib/api/tasks'
import { deleteTask } from '@/lib/api/tasks'

// ============================================================================
// Collapsible Section Component
// ============================================================================

interface CollapsibleSectionProps {
  title: string
  isOpen: boolean
  onToggle: () => void
  children: React.ReactNode
  className?: string
  testId?: string
}

function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
  className = '',
  testId,
}: CollapsibleSectionProps) {
  return (
    <div className={className}>
      <button
        onClick={onToggle}
        className="flex items-center gap-2 w-full text-left text-sm font-medium text-slate-400 hover:text-slate-300 transition-colors py-1"
        data-testid={testId}
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {title}
      </button>
      {isOpen && <div className="mt-2">{children}</div>}
    </div>
  )
}

// ============================================================================
// Types
// ============================================================================

interface TaskModalProps {
  taskId: string | null
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onTaskUpdate?: (task: Task) => void
  /** Initial task data to avoid refetch if available */
  initialTask?: Task | null
}

// ============================================================================
// Task Modal Component
// ============================================================================

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
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    handleStatusChange,
    handleSubtaskToggle,
    handleStartExecution,
    handleStopExecution,
    handleObjectiveEdit,
    handleToggleAutonomous,
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

  // Capability context
  const capability = task?.capability

  // Status checks for timeline visibility
  const isRunning = task?.status === 'running'
  const isPaused = task?.status === 'paused'
  const isAiReviewing = task?.status === 'ai_reviewing'
  const isCompleted = task?.status === 'completed'

  // Show timeline for active tasks AND completed tasks (to view execution history)
  const showTimeline = isRunning || isPaused || isAiReviewing || isCompleted

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
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
              {/* Execution Error */}
              {executionError && (
                <div className="p-3 bg-red-950/30 border border-red-800/30 rounded-lg mb-4">
                  <p className="text-sm text-red-400">{executionError}</p>
                </div>
              )}

              {/* Action Buttons */}
              <TaskModalActions
                task={task}
                isExecuting={isExecuting}
                isStopping={isStopping}
                isTogglingAutonomous={isTogglingAutonomous}
                isEditing={isEditing}
                onStartExecution={handleStartExecution}
                onStopExecution={handleStopExecution}
                onStatusChange={handleStatusChange}
                onToggleAutonomous={handleToggleAutonomous}
                onEditStart={handleEditStart}
                onEditCancel={handleEditCancel}
                onEditSave={handleEditSave}
                onDelete={handleDeleteClick}
              />

              {/* Objective Section - Always visible at top */}
              <ObjectiveSection
                objective={task.objective}
                onEdit={handleObjectiveEdit}
              />

              {/* Description - Collapsible, collapsed by default */}
              <CollapsibleSection
                title="Description"
                isOpen={descriptionOpen}
                onToggle={() => setDescriptionOpen(!descriptionOpen)}
                testId="description-toggle"
              >
                {isEditing ? (
                  <Textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={3}
                    placeholder="Enter task description..."
                  />
                ) : (
                  <p className="text-sm text-slate-300">
                    {task.description || (
                      <span className="italic text-slate-500">
                        No description
                      </span>
                    )}
                  </p>
                )}
              </CollapsibleSection>

              {/* Linked Capability */}
              {capability && (
                <LinkedCapabilitySection
                  capability={capability}
                  projectId={projectId}
                />
              )}

              {/* Criteria Progress */}
              {task.acceptance_criteria &&
                task.acceptance_criteria.length > 0 && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-medium text-slate-400">
                        Acceptance Criteria
                      </h3>
                      <CriteriaProgress
                        criteria={task.acceptance_criteria}
                        maxVisible={10}
                      />
                    </div>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                      {capability
                        ? `From: ${capability.capability_id}`
                        : 'Task-specific'}
                    </span>
                  </div>
                )}

              {/* Subtasks Section - Collapsible, collapsed by default */}
              {isLoadingSubtasks ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
                </div>
              ) : subtasks.length > 0 ? (
                <CollapsibleSection
                  title={`Subtasks (${subtasks.filter((s) => s.passes).length}/${subtasks.length})`}
                  isOpen={subtasksOpen}
                  onToggle={() => setSubtasksOpen(!subtasksOpen)}
                  testId="subtasks-toggle"
                >
                  <SubtasksSection
                    projectId={projectId}
                    taskId={task.id}
                    subtasks={subtasks}
                    onTogglePass={handleSubtaskToggle}
                  />
                </CollapsibleSection>
              ) : (
                <CollapsibleSection
                  title="Subtasks"
                  isOpen={subtasksOpen}
                  onToggle={() => setSubtasksOpen(!subtasksOpen)}
                  testId="subtasks-toggle"
                >
                  <p className="text-sm text-slate-500 italic">
                    No subtasks defined. Run /plan_it to add subtasks.
                  </p>
                </CollapsibleSection>
              )}

              {/* Execution Timeline - Collapsible at bottom, collapsed by default */}
              {showTimeline && (
                <CollapsibleSection
                  title="Execution Timeline"
                  isOpen={timelineOpen}
                  onToggle={() => setTimelineOpen(!timelineOpen)}
                  testId="timeline-toggle"
                >
                  <ExecutionTimeline
                    taskId={task.id}
                    projectId={task.project_id}
                    autoConnect={isRunning || isAiReviewing}
                    showChatInput={true}
                    chatEnabled={isRunning}
                    className="border border-slate-700 rounded-lg overflow-hidden"
                  />
                </CollapsibleSection>
              )}

              {/* Labels */}
              {task.labels && task.labels.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-2">
                    Labels
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {task.labels.map((label) => (
                      <span
                        key={label}
                        className="text-xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 border border-slate-600"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Metadata */}
              <TaskMetadata task={task} />
            </div>
          </>
        )}

        {/* Delete Confirmation Dialog */}
        {deleteConfirm && task && (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60"
            onClick={() => setDeleteConfirm(false)}
          >
            <div
              className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-3 mb-4">
                <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-lg font-semibold text-slate-100 mb-2">
                    Delete Task
                  </h3>
                  <p className="text-sm text-slate-300 mb-2">
                    Are you sure you want to delete this task?
                  </p>
                  <div className="text-sm font-mono text-slate-400 bg-slate-900 px-3 py-2 rounded mb-3">
                    {task.id}: {task.title}
                  </div>
                  <p className="text-sm text-red-400">
                    This will permanently delete the task and all its subtasks,
                    criteria, and dependencies. This cannot be undone.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setDeleteConfirm(false)}
                  disabled={deleteMutation.isPending}
                  className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDeleteConfirm}
                  disabled={deleteMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 text-white hover:bg-red-500 rounded-md transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {deleteMutation.isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    'Delete'
                  )}
                </button>
              </div>

              {deleteMutation.isError && (
                <p className="mt-3 text-sm text-red-400">
                  Failed to delete task. Please try again.
                </p>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
