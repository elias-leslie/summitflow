import clsx from 'clsx'
import type { LucideIcon } from 'lucide-react'

interface StatsWidgetProps {
  label: string
  value: number
  icon: LucideIcon
  color: string
}

export function StatsWidget({ label, value, icon: Icon, color }: StatsWidgetProps) {
  return (
    <div className="flex flex-col p-4 rounded-lg bg-slate-900/50 border border-slate-800">
      <div className="flex items-center gap-2 mb-1">
        <Icon className={clsx("w-4 h-4", color)} />
        <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
      </div>
      <span className={clsx("text-2xl font-bold font-mono", color)}>{value}</span>
    </div>
  )
}
