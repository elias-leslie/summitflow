'use client'

import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import type { Task } from '@/lib/api'
import { EnrichmentModal } from './EnrichmentModal'
import { TaskIdeationDialog } from './TaskIdeationDialog'
import { TaskModal } from './TaskModal'
import { TaskReviewModal } from './TaskReviewModal'

interface TasksTabModalsProps {
  projectId: string
  // Task detail modal
  modalTaskId: string | null
  modalOpen: boolean
  selectedTask: Task | null
  onModalOpenChange: (open: boolean) => void
  onTaskUpdate: (task: Task) => void
  // Create dialog
  showCreate: boolean
  onShowCreateChange: (show: boolean) => void
  // Enrichment modal
  enrichingTask: Task | null
  onEnrichmentComplete: (task: Task) => void
  onEnrichmentError: (error: unknown) => void
  onEnrichmentDismiss: () => void
  // Review modal
  reviewingTask: Task | null
  onReviewOpenChange: (open: boolean) => void
  onTaskAccepted: (task: Task) => void
  onTaskDiscard: () => void
  // Delete confirmation
  deleteConfirmTask: Task | null
  onDeleteConfirm: () => void
  onDeleteCancel: () => void
  isDeletingTask: boolean
  isDeleteError: boolean
  // Bulk delete confirmation
  bulkDeleteConfirm: boolean
  selectedTaskIds: Set<string>
  onBulkDeleteConfirm: () => void
  onBulkDeleteCancel: () => void
  isBulkDeleting: boolean
  isBulkDeleteError: boolean
}

export function TasksTabModals({
  projectId,
  modalTaskId,
  modalOpen,
  selectedTask,
  onModalOpenChange,
  onTaskUpdate,
  showCreate,
  onShowCreateChange,
  enrichingTask,
  onEnrichmentComplete,
  onEnrichmentError,
  onEnrichmentDismiss,
  reviewingTask,
  onReviewOpenChange,
  onTaskAccepted,
  onTaskDiscard,
  deleteConfirmTask,
  onDeleteConfirm,
  onDeleteCancel,
  isDeletingTask,
  isDeleteError,
  bulkDeleteConfirm,
  selectedTaskIds,
  onBulkDeleteConfirm,
  onBulkDeleteCancel,
  isBulkDeleting,
  isBulkDeleteError,
}: TasksTabModalsProps) {
  return (
    <>
      {/* Task Detail Modal */}
      <TaskModal
        taskId={modalTaskId}
        projectId={projectId}
        open={modalOpen}
        onOpenChange={onModalOpenChange}
        onTaskUpdate={onTaskUpdate}
        initialTask={selectedTask}
      />

      {/* Task Ideation Dialog */}
      <TaskIdeationDialog
        open={showCreate}
        onOpenChange={onShowCreateChange}
        projectId={projectId}
      />

      {/* Enrichment Progress Modal */}
      {enrichingTask && (
        <EnrichmentModal
          projectId={projectId}
          task={enrichingTask}
          onComplete={onEnrichmentComplete}
          onError={onEnrichmentError}
          onDismiss={onEnrichmentDismiss}
        />
      )}

      {/* Task Review Modal */}
      {reviewingTask && (
        <TaskReviewModal
          open={!!reviewingTask}
          onOpenChange={onReviewOpenChange}
          projectId={projectId}
          task={reviewingTask}
          onAccept={onTaskAccepted}
          onDiscard={onTaskDiscard}
        />
      )}

      {/* Single Delete Confirmation Dialog */}
      {deleteConfirmTask && (
        <ConfirmDeleteDialog
          entityType="task"
          entityName={`${deleteConfirmTask.id}: ${deleteConfirmTask.title}`}
          isDeleting={isDeletingTask}
          isError={isDeleteError}
          onConfirm={onDeleteConfirm}
          onCancel={onDeleteCancel}
        />
      )}

      {/* Bulk Delete Confirmation Dialog */}
      {bulkDeleteConfirm && (
        <ConfirmDeleteDialog
          entityType="tasks"
          taskIds={selectedTaskIds}
          isDeleting={isBulkDeleting}
          isError={isBulkDeleteError}
          onConfirm={onBulkDeleteConfirm}
          onCancel={onBulkDeleteCancel}
        />
      )}
    </>
  )
}
