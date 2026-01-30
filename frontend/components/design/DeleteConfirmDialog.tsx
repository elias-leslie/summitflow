'use client'

import { Loader2, Trash2 } from 'lucide-react'

interface DeleteConfirmDialogProps {
  count: number
  isDeleting: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteConfirmDialog({
  count,
  isDeleting,
  onConfirm,
  onCancel,
}: DeleteConfirmDialogProps): React.ReactElement {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80"
        onClick={onCancel}
      />

      {/* Dialog */}
      <div className="relative bg-slate-900 rounded-xl w-full max-w-md mx-4 p-6 border border-rose-500/30">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-rose-500/10 rounded-lg">
            <Trash2 className="w-6 h-6 text-rose-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-2">
              Delete {count} mockup
              {count > 1 ? 's' : ''}?
            </h3>
            <p className="text-slate-400 text-sm mb-6">
              This action cannot be undone. The selected mockup
              {count > 1 ? 's' : ''} will be permanently
              deleted.
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
