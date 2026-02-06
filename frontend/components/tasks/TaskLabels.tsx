'use client'

interface TaskLabelsProps {
  labels: string[]
}

export function TaskLabels({ labels }: TaskLabelsProps) {
  if (!labels || labels.length === 0) {
    return null
  }

  return (
    <div>
      <h3 className="text-sm font-medium text-slate-400 mb-2">Labels</h3>
      <div className="flex flex-wrap gap-2">
        {labels.map((label) => (
          <span
            key={label}
            className="text-xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 border border-slate-600"
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
