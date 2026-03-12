import {
  ChevronDown,
  ChevronUp,
  Lightbulb,
  Loader2,
  Trash2,
  Zap,
} from 'lucide-react'

interface TaskCardActionsProps {
  isIdea: boolean
  canExpand: boolean
  expanded: boolean
  isExecuting?: boolean
  taskId: string
  onDelete?: (taskId: string) => void
  onExecuteNow?: (taskId: string) => void
  onExpandToggle: (e: React.MouseEvent) => void
}

export function TaskCardActions({
  isIdea,
  canExpand,
  expanded,
  isExecuting,
  taskId,
  onDelete,
  onExecuteNow,
  onExpandToggle,
}: TaskCardActionsProps) {
  return (
    <>
      {onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(taskId)
          }}
          className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
          title="Delete task"
          aria-label="Delete task"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}

      {isIdea && (
        <div className="absolute top-2 right-2">
          <Lightbulb className="h-4 w-4 text-yellow-400" />
        </div>
      )}

      {isIdea && onExecuteNow && (
        <div className="mt-3 pt-2 border-t border-slate-700/50">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onExecuteNow(taskId)
            }}
            disabled={isExecuting}
            className="flex items-center justify-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium rounded bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 border border-yellow-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExecuting ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Executing...
              </>
            ) : (
              <>
                <Zap className="h-3 w-3" />
                Execute Now
              </>
            )}
          </button>
        </div>
      )}

      {canExpand && (
        <button
          type="button"
          onClick={onExpandToggle}
          className="mt-3 flex items-center justify-center gap-1 w-full py-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" />
              Hide execution details
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" />
              Show execution details
            </>
          )}
        </button>
      )}
    </>
  )
}
