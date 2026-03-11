'use client'

import { AlertCircle, Loader2, Trash2 } from 'lucide-react'

// ============================================================================
// Discriminated union props for different entity types
// ============================================================================

interface TaskDeleteProps {
  entityType: 'task'
  entityName: string
}

interface TasksBulkDeleteProps {
  entityType: 'tasks'
  taskIds: Set<string>
}

interface MockupDeleteProps {
  entityType: 'mockup'
  entityName: string
}

interface MockupsBulkDeleteProps {
  entityType: 'mockups'
  count: number
}

interface FeedbackDeleteProps {
  entityType: 'feedback'
  entityName: string
}

type EntityProps =
  | TaskDeleteProps
  | TasksBulkDeleteProps
  | MockupDeleteProps
  | MockupsBulkDeleteProps
  | FeedbackDeleteProps

interface CommonProps {
  isDeleting: boolean
  isError?: boolean
  onConfirm: () => void
  onCancel: () => void
  /** Override the default z-index class (default: "z-50") */
  zIndex?: string
  /** Use absolute positioning instead of fixed (for nested modals) */
  positioning?: 'fixed' | 'absolute'
}

type ConfirmDeleteDialogProps = EntityProps & CommonProps

// ============================================================================
// Component
// ============================================================================

export function ConfirmDeleteDialog(props: ConfirmDeleteDialogProps) {
  const { isDeleting, isError, onConfirm, onCancel, zIndex = 'z-50', positioning = 'fixed' } = props

  const isDesignEntity =
    props.entityType === 'mockup' || props.entityType === 'mockups'

  // ---- Title ----
  const title = getTitle(props)

  // ---- Description ----
  const description = getDescription(props)

  // ---- Warning text ----
  const warning = getWarning(props)

  // ---- Error message ----
  const errorMessage = getErrorMessage(props)

  // ---- Delete button label ----
  const deleteLabel = getDeleteLabel(props)

  if (isDesignEntity) {
    return (
      <div
        className={`${positioning} inset-0 ${zIndex} flex items-center justify-center${positioning === 'absolute' ? ' bg-black/60 backdrop-blur-sm' : ''}`}
      >
        {/* Backdrop (only for fixed positioning) */}
        {positioning === 'fixed' && (
          <div
            className="absolute inset-0 bg-black/80"
            onClick={onCancel}
          />
        )}

        {/* Dialog */}
        <div
          className="relative bg-slate-900 rounded-xl w-full max-w-md mx-4 p-6 border border-rose-500/30 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-start gap-4">
            <div className="p-3 bg-rose-500/10 rounded-lg">
              <Trash2 className="w-6 h-6 text-rose-400" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-white mb-2">
                {title}
              </h3>
              <p className="text-slate-400 text-sm mb-6">
                {description}
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={onCancel}
                  className="btn-secondary"
                  disabled={isDeleting}
                >
                  Cancel
                </button>
                <button
                  onClick={onConfirm}
                  disabled={isDeleting}
                  className="bg-rose-500 hover:bg-rose-600 text-white px-4 py-2 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {isDeleting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    <>
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Task-style layout (AlertCircle, red theme)
  return (
    <div
      className={`${positioning} inset-0 ${zIndex} flex items-center justify-center bg-black/60`}
      onClick={onCancel}
    >
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-lg font-semibold text-slate-100 mb-2">
              {title}
            </h3>
            <p className="text-sm text-slate-300 mb-3">
              {description}
            </p>

            {/* Entity detail block */}
            {props.entityType === 'task' && (
              <div className="text-sm font-mono text-slate-400 bg-slate-900 px-3 py-2 rounded mb-3">
                {props.entityName}
              </div>
            )}
            {props.entityType === 'tasks' && (
              <div className="text-sm font-mono text-slate-400 bg-slate-900 px-3 py-2 rounded mb-3 max-h-32 overflow-y-auto">
                {Array.from(props.taskIds)
                  .slice(0, 5)
                  .map((id) => (
                    <div key={id}>{id}</div>
                  ))}
                {props.taskIds.size > 5 && (
                  <div className="text-slate-500 italic">
                    ...and {props.taskIds.size - 5} more
                  </div>
                )}
              </div>
            )}

            <p className="text-sm text-red-400">{warning}</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isDeleting}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 text-white hover:bg-red-500 rounded-md transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isDeleting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Deleting...
              </>
            ) : (
              deleteLabel
            )}
          </button>
        </div>

        {isError && (
          <p className="mt-3 text-sm text-red-400">{errorMessage}</p>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// Helper functions
// ============================================================================

function getTitle(props: EntityProps): string {
  switch (props.entityType) {
    case 'task':
      return 'Delete Task'
    case 'tasks': {
      const count = props.taskIds.size
      return `Delete ${count} Task${count !== 1 ? 's' : ''}`
    }
    case 'mockup':
      return 'Delete mockup?'
    case 'mockups': {
      const count = props.count
      return `Delete ${count} mockup${count > 1 ? 's' : ''}?`
    }
    case 'feedback':
      return 'Delete Feedback'
  }
}

function getDescription(props: EntityProps): string {
  switch (props.entityType) {
    case 'task':
      return 'Are you sure you want to delete this task?'
    case 'tasks':
      return 'Are you sure you want to delete these tasks?'
    case 'mockup':
      return `Are you sure you want to delete "${props.entityName}"? This action cannot be undone.`
    case 'mockups': {
      const count = props.count
      return `This action cannot be undone. The selected mockup${count > 1 ? 's' : ''} will be permanently deleted.`
    }
    case 'feedback':
      return `Are you sure you want to delete "${props.entityName}"?`
  }
}

function getWarning(props: EntityProps): string {
  switch (props.entityType) {
    case 'task':
      return 'This will permanently delete the task and all its subtasks, criteria, and dependencies. This cannot be undone.'
    case 'tasks':
      return 'This will permanently delete all selected tasks and their subtasks, criteria, and dependencies. This cannot be undone.'
    case 'feedback':
      return 'This will permanently delete the feedback item and its votes. This cannot be undone.'
    default:
      return ''
  }
}

function getErrorMessage(props: EntityProps): string {
  switch (props.entityType) {
    case 'task':
      return 'Failed to delete task. Please try again.'
    case 'tasks':
      return 'Failed to delete tasks. Please try again.'
    case 'mockup':
      return 'Failed to delete mockup. Please try again.'
    case 'mockups':
      return 'Failed to delete mockups. Please try again.'
    case 'feedback':
      return 'Failed to delete feedback. Please try again.'
  }
}

function getDeleteLabel(props: EntityProps): string {
  switch (props.entityType) {
    case 'task':
    case 'mockup':
      return 'Delete'
    case 'tasks':
      return `Delete ${props.taskIds.size}`
    case 'mockups':
      return `Delete ${props.count}`
    case 'feedback':
      return 'Delete'
  }
}
