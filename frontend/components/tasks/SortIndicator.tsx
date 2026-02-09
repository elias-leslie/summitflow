import { ArrowDown, ArrowUp } from 'lucide-react'
import type { SortDirection, SortField } from './hooks/useTaskSort'

interface SortIndicatorProps {
  field: SortField
  currentField: SortField
  direction: SortDirection
}

export function SortIndicator({
  field,
  currentField,
  direction,
}: SortIndicatorProps) {
  if (currentField !== field) return null
  return direction === 'asc' ? (
    <ArrowUp className="w-3 h-3 inline ml-1" />
  ) : (
    <ArrowDown className="w-3 h-3 inline ml-1" />
  )
}
