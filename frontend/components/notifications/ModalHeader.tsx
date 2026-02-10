import { AlertCircle, Loader2, RefreshCw, X } from 'lucide-react'
import type { Notification } from '@/lib/api'

interface ModalHeaderProps {
  notification: Notification
  retrying: boolean
  onRetry: () => void
  onClose: () => void
}

export function ModalHeader({
  notification,
  retrying,
  onRetry,
  onClose,
}: ModalHeaderProps) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 bg-slate-900/50">
      <div className="flex items-center gap-3">
        <AlertCircle className="w-5 h-5 text-rose-400" />
        <div>
          <h2 className="text-sm font-medium text-slate-200">
            {notification.title}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {notification.task_id || 'No linked task'}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {notification.task_id && (
          <button
            onClick={onRetry}
            disabled={retrying}
            className="btn-ghost p-2 rounded-lg text-amber-400 hover:text-amber-300 hover:bg-amber-950/30"
            title="Retry Task"
          >
            {retrying ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
          </button>
        )}
        <button
          onClick={onClose}
          className="btn-ghost p-2 rounded-lg"
          title="Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
