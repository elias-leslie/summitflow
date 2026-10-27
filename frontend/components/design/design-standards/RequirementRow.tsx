/**
 * RequirementRow - Displays a single requirement with severity styling
 */

'use client'

import { cn } from '@/lib/utils'
import type { RequirementValue } from './types'

interface RequirementRowProps {
  name: string
  value: RequirementValue
}

export function RequirementRow({ name, value }: RequirementRowProps) {
  const severityStyles = {
    error: 'border-red-500/30 bg-red-950/20 text-red-400',
    warning: 'border-amber-500/30 bg-amber-950/20 text-amber-400',
    info: 'border-slate-500/30 bg-slate-950/20 text-slate-400',
  }

  const style = severityStyles[value.severity || 'info']

  const formatValue = () => {
    if (value.exact !== undefined) {
      if (typeof value.exact === 'boolean') {
        return value.exact ? 'true' : 'false'
      }
      return String(value.exact)
    }
    if (value.min !== undefined && value.max !== undefined) {
      return `${value.min} - ${value.max}`
    }
    if (value.min !== undefined) return `>= ${value.min}`
    if (value.max !== undefined) return `<= ${value.max}`
    if (value.allowed) {
      return (
        value.allowed.slice(0, 3).join(', ') +
        (value.allowed.length > 3 ? '...' : '')
      )
    }
    return '-'
  }

  return (
    <div
      className={cn(
        'flex items-center justify-between px-2 py-1 rounded border text-xs',
        style,
      )}
    >
      <span className="text-slate-300">{name.replace(/_/g, ' ')}</span>
      <span className="font-mono">{formatValue()}</span>
    </div>
  )
}
