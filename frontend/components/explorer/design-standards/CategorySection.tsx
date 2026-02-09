/**
 * CategorySection - Displays a collapsible section for a design rule category
 */

'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import { categoryConfig, defaultCategoryConfig } from './categoryConfig'
import { RuleItem } from './RuleItem'
import type { DesignRule } from './types'

interface CategorySectionProps {
  category: string
  rules: DesignRule[]
  isExpanded: boolean
  onToggle: () => void
}

export function CategorySection({
  category,
  rules,
  isExpanded,
  onToggle,
}: CategorySectionProps) {
  const config = categoryConfig[category] || {
    ...defaultCategoryConfig,
    label: category,
  }

  return (
    <div className="border border-slate-700/50 rounded overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-800/50 hover:bg-slate-800/80 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isExpanded ? (
            <ChevronDown className="w-3 h-3 text-slate-500" />
          ) : (
            <ChevronRight className="w-3 h-3 text-slate-500" />
          )}
          <span className={config.color}>{config.icon}</span>
          <span className="text-slate-200 font-medium">{config.label}</span>
        </div>
        <span className="text-xs text-slate-500">{rules.length} rules</span>
      </button>

      {isExpanded && (
        <div className="divide-y divide-slate-700/30">
          {rules.map((rule) => (
            <RuleItem key={rule.rule_id} rule={rule} />
          ))}
        </div>
      )}
    </div>
  )
}
