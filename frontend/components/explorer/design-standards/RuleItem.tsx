/**
 * RuleItem - Displays a single design rule with its requirements
 */

'use client'

import { AlertCircle, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { RequirementRow } from './RequirementRow'
import type { DesignRule } from './types'

interface RuleItemProps {
  rule: DesignRule
}

export function RuleItem({ rule }: RuleItemProps) {
  const [showDetails, setShowDetails] = useState(false)

  // Count requirements by severity
  const severityCounts = Object.values(rule.requirements).reduce<
    Record<string, number>
  >((acc, req) => {
    const severity = req.severity || 'info'
    acc[severity] = (acc[severity] || 0) + 1
    return acc
  }, {})

  return (
    <div className="bg-slate-900/30">
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-800/30 transition-colors text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          {showDetails ? (
            <ChevronDown className="w-3 h-3 text-slate-600 flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3 h-3 text-slate-600 flex-shrink-0" />
          )}
          <span className="text-slate-300 truncate">{rule.name}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {severityCounts.error && (
            <span className="flex items-center gap-1 text-xs text-red-400">
              <AlertCircle className="w-3 h-3" />
              {severityCounts.error}
            </span>
          )}
          {severityCounts.warning && (
            <span className="flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle className="w-3 h-3" />
              {severityCounts.warning}
            </span>
          )}
        </div>
      </button>

      {showDetails && (
        <div className="px-3 py-2 bg-slate-950/50 border-t border-slate-700/30">
          <div className="text-xs text-slate-500 mb-2">
            Rule ID: <span className="text-slate-400">{rule.rule_id}</span>
          </div>
          <div className="space-y-1">
            {Object.entries(rule.requirements).map(([key, value]) => (
              <RequirementRow key={key} name={key} value={value} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
