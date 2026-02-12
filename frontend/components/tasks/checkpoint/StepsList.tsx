import { CheckCircle, Circle } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface StepsListProps {
  steps: string[]
  type: 'completed' | 'remaining'
}

export function StepsList({ steps, type }: StepsListProps) {
  const isCompleted = type === 'completed'
  const Icon = isCompleted ? CheckCircle : Circle
  const iconClass = isCompleted
    ? 'h-3 w-3 text-phosphor-500 mt-0.5 flex-shrink-0'
    : 'h-3 w-3 text-slate-400 mt-0.5 flex-shrink-0'
  const textClass = isCompleted
    ? 'text-slate-600 dark:text-slate-400'
    : 'text-slate-500'

  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-slate-500">
        {isCompleted ? 'Completed' : 'Remaining'}
      </div>
      <ScrollArea className="max-h-24">
        {steps.slice(0, 10).map((step, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs py-0.5">
            <Icon className={iconClass} />
            <span className={textClass}>{step}</span>
          </div>
        ))}
        {steps.length > 10 && (
          <div className="text-xs text-slate-400 pl-4">
            +{steps.length - 10} more
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
