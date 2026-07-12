'use client'

import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'
import clsx from 'clsx'
import { AlertCircle, Loader2, Trash2 } from 'lucide-react'
import { useRef } from 'react'

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

interface AssetDeleteProps {
  entityType: 'asset'
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
  | AssetDeleteProps
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
  const cancelButtonRef = useRef<HTMLButtonElement>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(
    typeof document !== 'undefined' &&
      document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  )
  const {
    isDeleting,
    isError,
    onConfirm,
    onCancel,
    zIndex = 'z-50',
    positioning = 'fixed',
  } = props

  const isDesignEntity =
    props.entityType === 'mockup' ||
    props.entityType === 'mockups' ||
    props.entityType === 'asset'

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

  const handleDismiss = () => {
    if (!isDeleting) {
      onCancel()
    }
  }

  const backdrop = (
    <AlertDialogPrimitive.Overlay
      data-testid="confirm-delete-backdrop"
      onClick={handleDismiss}
      className={clsx(
        positioning,
        'inset-0 bg-slate-950/90 backdrop-blur-sm data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=open]:animate-in data-[state=open]:fade-in motion-reduce:animate-none',
        zIndex,
      )}
    />
  )

  const dialog = isDesignEntity ? (
    <AlertDialogPrimitive.Content
      onCloseAutoFocus={(event) => {
        const target = restoreFocusRef.current
        if (target?.isConnected) {
          event.preventDefault()
          target.focus()
        }
      }}
      onEscapeKeyDown={(event) => {
        if (isDeleting) event.preventDefault()
      }}
      className={clsx(
        positioning,
        'left-1/2 top-1/2 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-rose-500/30 bg-slate-900 p-6 shadow-2xl focus:outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95 motion-reduce:animate-none',
        zIndex,
      )}
    >
      <div className="flex items-start gap-4">
        <div className="rounded-lg bg-rose-500/10 p-3">
          <Trash2 aria-hidden="true" className="h-6 w-6 text-rose-400" />
        </div>
        <div className="flex-1">
          <AlertDialogPrimitive.Title className="mb-2 text-lg font-semibold text-slate-100">
            {title}
          </AlertDialogPrimitive.Title>
          <AlertDialogPrimitive.Description className="mb-6 text-sm text-slate-400">
            {description}
          </AlertDialogPrimitive.Description>
          <div className="flex justify-end gap-3">
            <AlertDialogPrimitive.Cancel asChild>
              <button
                ref={cancelButtonRef}
                type="button"
                className="btn-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/50"
                disabled={isDeleting}
              >
                Cancel
              </button>
            </AlertDialogPrimitive.Cancel>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isDeleting}
              className="flex items-center gap-2 rounded-lg bg-rose-500 px-4 py-2 text-slate-50 transition-colors hover:bg-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-50"
            >
              {isDeleting ? (
                <>
                  <Loader2
                    aria-hidden="true"
                    className="h-4 w-4 animate-spin motion-reduce:animate-none"
                  />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash2 aria-hidden="true" className="h-4 w-4" />
                  Delete
                </>
              )}
            </button>
          </div>
          {isError && (
            <p role="alert" className="mt-3 text-sm text-rose-400">
              {errorMessage}
            </p>
          )}
        </div>
      </div>
    </AlertDialogPrimitive.Content>
  ) : (
    <AlertDialogPrimitive.Content
      onCloseAutoFocus={(event) => {
        const target = restoreFocusRef.current
        if (target?.isConnected) {
          event.preventDefault()
          target.focus()
        }
      }}
      onEscapeKeyDown={(event) => {
        if (isDeleting) event.preventDefault()
      }}
      className={clsx(
        positioning,
        'left-1/2 top-1/2 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-slate-700 bg-slate-800 p-6 shadow-xl focus:outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95 motion-reduce:animate-none',
        zIndex,
      )}
    >
      <div className="mb-4 flex items-start gap-3">
        <AlertCircle
          aria-hidden="true"
          className="mt-0.5 h-6 w-6 shrink-0 text-rose-400"
        />
        <div>
          <AlertDialogPrimitive.Title className="mb-2 text-lg font-semibold text-slate-100">
            {title}
          </AlertDialogPrimitive.Title>
          <AlertDialogPrimitive.Description className="mb-3 text-sm text-slate-300">
            {description}
          </AlertDialogPrimitive.Description>

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

          <p className="text-sm text-rose-400">{warning}</p>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3">
        <AlertDialogPrimitive.Cancel asChild>
          <button
            ref={cancelButtonRef}
            type="button"
            disabled={isDeleting}
            className="px-4 py-2 text-sm text-slate-400 transition-colors hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/50 disabled:opacity-50"
          >
            Cancel
          </button>
        </AlertDialogPrimitive.Cancel>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isDeleting}
          className="flex items-center gap-2 rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-slate-50 transition-colors hover:bg-rose-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDeleting ? (
            <>
              <Loader2
                aria-hidden="true"
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
              />
              Deleting...
            </>
          ) : (
            deleteLabel
          )}
        </button>
      </div>

      {isError && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {errorMessage}
        </p>
      )}
    </AlertDialogPrimitive.Content>
  )

  const modal = (
    <>
      {backdrop}
      {dialog}
    </>
  )

  return (
    <AlertDialogPrimitive.Root
      open
      onOpenChange={(open) => {
        if (!open) handleDismiss()
      }}
    >
      {positioning === 'fixed' ? (
        <AlertDialogPrimitive.Portal>{modal}</AlertDialogPrimitive.Portal>
      ) : (
        modal
      )}
    </AlertDialogPrimitive.Root>
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
    case 'asset':
      return 'Delete asset?'
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
    case 'asset':
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
    case 'asset':
      return 'Failed to delete asset. Please try again.'
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
    case 'asset':
      return 'Delete'
    case 'tasks':
      return `Delete ${props.taskIds.size}`
    case 'mockups':
      return `Delete ${props.count}`
    case 'feedback':
      return 'Delete'
  }
}
