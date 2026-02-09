import { AlertCircle, Loader2 } from 'lucide-react'
import type { Task } from '@/lib/api'

// ============================================================================
// Delete Confirmation Dialog
// ============================================================================

interface DeleteConfirmDialogProps {
  task: Task
  isDeleting: boolean
  isError: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteConfirmDialog({
  task,
  isDeleting,
  isError,
  onConfirm,
  onCancel,
}: DeleteConfirmDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
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
              'Delete'
            )}
          </button>
        </div>

        {isError && (
          <p className="mt-3 text-sm text-red-400">
            Failed to delete task. Please try again.
          </p>
        )}
      </div>
    </div>
  )
}
