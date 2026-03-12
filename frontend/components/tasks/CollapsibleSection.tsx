'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'

interface CollapsibleSectionProps {
  title: string
  isOpen: boolean
  onToggle: () => void
  children: React.ReactNode
  className?: string
  testId?: string
}

export function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
  className = '',
  testId,
}: CollapsibleSectionProps) {
  return (
    <div className={className}>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 w-full text-left text-sm font-medium text-slate-400 hover:text-slate-300 transition-colors py-1"
        data-testid={testId}
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {title}
      </button>
      {isOpen && <div className="mt-2">{children}</div>}
    </div>
  )
}
