'use client'

import { CheckSquare, Loader2, Trash2 } from 'lucide-react'

interface BulkActionBarProps {
  selectedCount: number
  isDeleting: boolean
  onDelete: () => void
}

export function BulkActionBar({
  selectedCount,
  isDeleting,
  onDelete,
}: BulkActionBarProps): React.ReactElement {
  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 animate-in slide-in-from-bottom-4">
      <div className="bg-slate-900 border-2 border-outrun-500/50 rounded-xl px-6 py-4 shadow-2xl shadow-outrun-500/20 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <CheckSquare className="w-5 h-5 text-outrun-400" />
          <span className="text-white font-medium">
            {selectedCount} selected
          </span>
        </div>
        <div className="h-6 w-px bg-slate-700" />
        <button
          type="button"
          onClick={onDelete}
          disabled={isDeleting}
          className="flex items-center gap-2 px-4 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded-lg transition-all border border-rose-500/30 hover:border-rose-500/50 disabled:opacity-50"
        >
          {isDeleting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Trash2 className="w-4 h-4" />
          )}
          Delete {selectedCount > 1 ? 'All' : ''}
        </button>
      </div>
    </div>
  )
}
