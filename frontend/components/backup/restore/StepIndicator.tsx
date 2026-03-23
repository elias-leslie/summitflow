import { clsx } from 'clsx'
import { CheckCircle2 } from 'lucide-react'

interface StepIndicatorProps {
  stepNum: number
  label: string
  active: boolean
  completed: boolean
}

export function StepIndicator({
  stepNum,
  label,
  active,
  completed,
}: StepIndicatorProps) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={clsx(
          'w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium',
          completed
            ? 'bg-green-500 text-slate-50'
            : active
              ? 'bg-phosphor-500 text-slate-50'
              : 'bg-slate-700 text-slate-400',
        )}
      >
        {completed ? <CheckCircle2 className="w-4 h-4" /> : stepNum}
      </div>
      <span
        className={clsx(
          'text-sm',
          active ? 'text-slate-200' : 'text-slate-500',
        )}
      >
        {label}
      </span>
    </div>
  )
}
