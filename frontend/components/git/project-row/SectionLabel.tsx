import clsx from 'clsx'
import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react'

interface SectionLabelProps {
  icon: LucideIcon
  label: string
  count: number
  color: string
  badgeBg: string
  badgeBorder: string
  expanded?: boolean
  onToggle?: () => void
}

export function SectionLabel({
  icon: Icon,
  label,
  count,
  color,
  badgeBg,
  badgeBorder,
  expanded,
  onToggle,
}: SectionLabelProps) {
  const Wrapper = onToggle ? 'button' : 'div'
  return (
    <Wrapper
      onClick={onToggle}
      className={clsx(
        'flex items-center gap-2 mb-2.5 py-0.5',
        onToggle && 'group cursor-pointer hover:opacity-90 transition-opacity',
      )}
    >
      {onToggle &&
        (expanded ? (
          <ChevronDown className="w-3 h-3 text-slate-500" />
        ) : (
          <ChevronRight className="w-3 h-3 text-slate-600 group-hover:text-slate-400 transition-colors" />
        ))}
      <Icon className={clsx('w-3.5 h-3.5', color)} />
      <span className="text-2xs font-semibold uppercase tracking-[0.12em] text-slate-400">
        {label}
      </span>
      <span
        className={clsx(
          'text-[9px] font-mono px-1.5 py-0.5 rounded-full border',
          badgeBg,
          color,
          badgeBorder,
        )}
      >
        {count}
      </span>
    </Wrapper>
  )
}
