import { clsx } from 'clsx'
import { Zap } from 'lucide-react'

interface MasterToggleProps {
  enabled: boolean
  isPending: boolean
  onToggle: () => void
}

export function MasterToggle({ enabled, isPending, onToggle }: MasterToggleProps) {
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
            <Zap className="w-4 h-4 text-yellow-400" />
            Autonomous Execution
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Enable AI agents to automatically execute refactor, debt, and
            regression tasks
          </p>
        </div>
        <button
          onClick={onToggle}
          disabled={isPending}
          className={clsx(
            'relative w-12 h-6 rounded-full transition-colors',
            enabled ? 'bg-phosphor-500' : 'bg-slate-600',
          )}
        >
          <span
            className={clsx(
              'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
              enabled ? 'translate-x-7' : 'translate-x-1',
            )}
          />
        </button>
      </div>
    </div>
  )
}
