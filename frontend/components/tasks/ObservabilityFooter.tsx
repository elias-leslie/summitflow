'use client'

interface ObservabilityFooterProps {
  filteredCount: number
  totalCount: number
  maxTurn: number
  searchTerm: string
}

export function ObservabilityFooter({
  filteredCount,
  totalCount,
  maxTurn,
  searchTerm,
}: ObservabilityFooterProps) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900/40 border border-slate-800/50 border-t-0 rounded-b-lg text-2xs text-slate-500">
      <span>
        {filteredCount} of {totalCount} events
        {searchTerm && ` matching "${searchTerm}"`}
      </span>
      <span>{maxTurn} turns</span>
    </div>
  )
}
