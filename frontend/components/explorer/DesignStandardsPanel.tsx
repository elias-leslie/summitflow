/**
 * DesignStandardsPanel - Reference panel showing design standards and rules
 *
 * Displays the project's effective design standards organized by category.
 * Features:
 * - Collapsible category sections
 * - Rule requirements with severity indicators
 * - Links page health to compliance status
 */

'use client'

import { useQuery } from '@tanstack/react-query'
import { buildApiUrl } from '@/lib/api-config'
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Component,
  Droplet,
  Info,
  Layout,
  Loader2,
  Navigation,
  Palette,
  Type,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

// Types
interface DesignRule {
  id: number
  standard_id: number
  category: string
  rule_id: string
  name: string
  requirements: Record<string, RequirementValue>
  created_at: string
  source: string | null
}

interface RequirementValue {
  exact?: string | number | boolean
  min?: number
  max?: number
  allowed?: (string | number)[]
  severity: 'error' | 'warning' | 'info'
}

interface DesignStandardsPanelProps {
  projectId: string
  className?: string
}

// Category icons and colors
const categoryConfig: Record<
  string,
  { icon: React.ReactNode; color: string; label: string }
> = {
  layout: {
    icon: <Layout className="w-4 h-4" />,
    color: 'text-cyan-400',
    label: 'Layout',
  },
  typography: {
    icon: <Type className="w-4 h-4" />,
    color: 'text-violet-400',
    label: 'Typography',
  },
  color: {
    icon: <Droplet className="w-4 h-4" />,
    color: 'text-pink-400',
    label: 'Color',
  },
  components: {
    icon: <Component className="w-4 h-4" />,
    color: 'text-amber-400',
    label: 'Components',
  },
  navigation: {
    icon: <Navigation className="w-4 h-4" />,
    color: 'text-emerald-400',
    label: 'Navigation',
  },
}

// API fetch
async function fetchEffectiveRules(projectId: string): Promise<DesignRule[]> {
  const res = await fetch(
    buildApiUrl(`/api/projects/${projectId}/design-standards/effective-rules`),
  )
  if (!res.ok) {
    // Fallback to base rules if project has no standard
    const baseRes = await fetch(buildApiUrl('/api/design-standards/base/rules'))
    if (!baseRes.ok) throw new Error('Failed to fetch design rules')
    return baseRes.json()
  }
  return res.json()
}

export function DesignStandardsPanel({
  projectId,
  className,
}: DesignStandardsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(),
  )

  const {
    data: rules,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['design-rules', projectId],
    queryFn: () => fetchEffectiveRules(projectId),
    staleTime: 300000, // 5 minutes
    refetchOnWindowFocus: false,
  })

  // Group rules by category
  const rulesByCategory = rules?.reduce<Record<string, DesignRule[]>>(
    (acc, rule) => {
      if (!acc[rule.category]) acc[rule.category] = []
      acc[rule.category].push(rule)
      return acc
    },
    {},
  )

  const toggleCategory = (category: string) => {
    const next = new Set(expandedCategories)
    if (next.has(category)) {
      next.delete(category)
    } else {
      next.add(category)
    }
    setExpandedCategories(next)
  }

  const totalRules = rules?.length ?? 0
  const categoryCount = rulesByCategory
    ? Object.keys(rulesByCategory).length
    : 0

  if (error) {
    return (
      <div
        className={cn('border border-red-500/30 bg-red-950/20 p-4', className)}
      >
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          <span>Failed to load design standards</span>
        </div>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'border border-slate-700/50 bg-gradient-to-b from-slate-900/80 to-slate-950/90',
        'font-mono text-sm',
        className,
      )}
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/30 transition-colors border-b border-slate-700/30"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-pink-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Palette className="w-4 h-4 text-pink-500" />
          <span className="text-pink-400 font-semibold tracking-wide">
            DESIGN STANDARDS
          </span>
          {isLoading && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-2" />
          )}
        </div>

        {/* Summary in header */}
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/50 border border-slate-700/30">
            <span className="text-slate-400">{totalRules}</span>
            <span className="text-slate-500">rules</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/50 border border-slate-700/30">
            <span className="text-slate-400">{categoryCount}</span>
            <span className="text-slate-500">categories</span>
          </div>
        </div>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-2 max-h-[500px] overflow-y-auto">
          {/* Category sections */}
          {rulesByCategory &&
            Object.entries(rulesByCategory).map(([category, categoryRules]) => (
              <CategorySection
                key={category}
                category={category}
                rules={categoryRules}
                isExpanded={expandedCategories.has(category)}
                onToggle={() => toggleCategory(category)}
              />
            ))}

          {!isLoading && !rulesByCategory && (
            <div className="text-center py-8 text-slate-500">
              <Palette className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No design standards configured</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CategorySection({
  category,
  rules,
  isExpanded,
  onToggle,
}: {
  category: string
  rules: DesignRule[]
  isExpanded: boolean
  onToggle: () => void
}) {
  const config = categoryConfig[category] || {
    icon: <Info className="w-4 h-4" />,
    color: 'text-slate-400',
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

function RuleItem({ rule }: { rule: DesignRule }) {
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

function RequirementRow({
  name,
  value,
}: {
  name: string
  value: RequirementValue
}) {
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
