import { HelpCircle } from 'lucide-react'

interface PendingQuestionProps {
  question: string
  options?: Array<{ label: string; description?: string }> | null
  recommendation?: string | null
}

export function PendingQuestion({
  question,
  options,
  recommendation,
}: PendingQuestionProps) {
  return (
    <div className="space-y-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
        <HelpCircle className="h-3.5 w-3.5" />
        Pending Question
      </div>
      <div className="text-sm">{question}</div>
      {options && options.length > 0 && (
        <div className="space-y-1 mt-2">
          <div className="text-xs text-slate-500">Options:</div>
          {options.map((opt, i) => (
            <div
              key={i}
              className="text-sm pl-2 text-slate-600 dark:text-slate-400"
            >
              {i + 1}. {opt.label}
            </div>
          ))}
        </div>
      )}
      {recommendation && (
        <div className="text-xs text-slate-500 mt-2">
          Recommendation: {recommendation}
        </div>
      )}
    </div>
  )
}
