import { Lightbulb, Trash2 } from 'lucide-react'

interface TaskCardActionsProps {
  isIdea: boolean
  taskId: string
  onDelete?: (taskId: string) => void
}

export function TaskCardActions({
  isIdea,
  taskId,
  onDelete,
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
          className="absolute right-2 top-2 z-20 rounded p-1 text-slate-500 opacity-0 transition-opacity hover:bg-red-500/20 hover:text-red-400 group-hover:opacity-100 group-focus-within:opacity-100"
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
    </>
  )
}
