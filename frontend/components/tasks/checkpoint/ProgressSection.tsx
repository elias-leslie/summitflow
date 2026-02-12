import { StepsList } from './StepsList'

interface ProgressSectionProps {
  completedSteps: string[]
  remainingSteps: string[]
}

export function ProgressSection({
  completedSteps,
  remainingSteps,
}: ProgressSectionProps) {
  const totalSteps = completedSteps.length + remainingSteps.length
  const progress =
    totalSteps > 0 ? (completedSteps.length / totalSteps) * 100 : 0

  if (totalSteps === 0) return null

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-slate-500">
        <span>Progress</span>
        <span>
          {completedSteps.length}/{totalSteps} steps
        </span>
      </div>
      <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-phosphor-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="space-y-2 mt-3">
        {completedSteps.length > 0 && (
          <StepsList steps={completedSteps} type="completed" />
        )}
        {remainingSteps.length > 0 && (
          <StepsList steps={remainingSteps} type="remaining" />
        )}
      </div>
    </div>
  )
}
