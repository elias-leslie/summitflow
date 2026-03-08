/**
 * RefactorTargetsTableRows - Sub-components for RefactorTargetsTable rows and header
 */

'use client'

import {
  ArrowUpDown,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Flame,
  ShieldAlert,
  Sparkles,
  TimerReset,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RefactorTarget } from './utils/codeHealthApi'
import {
  getIssueStyle,
  getPriorityStyles,
  type SortDir,
  type SortField,
} from './utils/codeHealthUtils'

export function SortableHeader({
  field,
  label,
  currentField,
  currentDir,
  onSort,
  className,
}: {
  field: SortField
  label: string
  currentField: SortField
  currentDir: SortDir
  onSort: (field: SortField) => void
  className?: string
}) {
  const isActive = currentField === field

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        'flex items-center gap-1 hover:text-slate-200 transition-colors',
        isActive && 'text-emerald-400',
        className,
      )}
    >
      <span>{label}</span>
      <ArrowUpDown
        className={cn(
          'w-3 h-3',
          isActive ? 'opacity-100' : 'opacity-30',
          isActive && currentDir === 'asc' && 'rotate-180',
        )}
      />
    </button>
  )
}

export function TargetRow({
  target,
  isExpanded,
  onToggle,
  onFileSelect,
}: {
  target: RefactorTarget
  isExpanded: boolean
  onToggle: () => void
  onFileSelect?: (path: string) => void
}) {
  const style = getPriorityStyles(target.priority)

  const hotspotColor =
    target.hotspot_score >= 500
      ? 'text-red-400'
      : target.hotspot_score >= 100
        ? 'text-amber-400'
        : 'text-slate-400'
  const actionBadge = target.should_create_task
    ? {
        icon: Sparkles,
        label: `AUTO TASK ${target.confidence.toUpperCase()}`,
        className: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
      }
    : target.recommended_action === 'review_manually'
      ? {
          icon: ShieldAlert,
          label: 'REVIEW MANUALLY',
          className: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
        }
      : {
          icon: TimerReset,
          label: 'EXPLORER ONLY',
          className: 'border-slate-700/60 bg-slate-800/70 text-slate-300',
        }
  const ActionIcon = actionBadge.icon

  return (
    <div className={cn('border-b border-slate-700/30', style.bg)}>
      {/* Main row */}
      <div
        className="grid grid-cols-[2rem_1fr_5rem_5rem_4rem_5rem] gap-2 px-3 py-2 items-center cursor-pointer hover:bg-slate-700/20 transition-colors"
        onClick={onToggle}
      >
        <div>
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </div>
        <div className="min-w-0">
          <div className="truncate text-slate-300" title={target.path}>
            <span className="text-slate-500">
              {target.path.split('/').slice(0, -1).join('/')}/
            </span>
            <span className="font-medium">{target.name}</span>
          </div>
          {target.refactor_issues.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-0.5">
              {target.refactor_issues.slice(0, 4).map((issue) => {
                const s = getIssueStyle(issue)
                return (
                  <span
                    key={issue}
                    className={cn('px-1 py-0 text-[10px] rounded border', s.color)}
                  >
                    {s.label}
                  </span>
                )
              })}
              {target.refactor_issues.length > 4 && (
                <span className="text-[10px] text-slate-500">
                  +{target.refactor_issues.length - 4}
                </span>
              )}
            </div>
          )}
        </div>
        <div className={cn('text-right tabular-nums flex items-center justify-end gap-1', hotspotColor)}>
          {target.hotspot_score >= 500 && <Flame className="w-3 h-3" />}
          {target.hotspot_score.toFixed(0)}
        </div>
        <div className={cn('text-right tabular-nums', style.text)}>
          {target.complexity_score.toFixed(1)}
        </div>
        <div className="text-right tabular-nums text-slate-400">
          {target.lines_of_code.toLocaleString()}
        </div>
        <div className="flex justify-center">
          <span
            className={cn(
              'px-2 py-0.5 text-xs rounded text-white font-medium',
              style.badge,
            )}
          >
            {style.label}
          </span>
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div
          className={cn('px-3 py-3 border-t', style.border, 'bg-slate-900/50')}
        >
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div className="space-y-2">
              <div>
                <span className="text-slate-500">Full Path:</span>
                <span className="ml-2 text-slate-300 font-mono">
                  {target.path}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Reason:</span>
                <span className={cn('ml-2', style.text)}>{target.reason}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Automation:</span>
                <span
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] uppercase tracking-wide',
                    actionBadge.className,
                  )}
                >
                  <ActionIcon className="h-3 w-3" />
                  {actionBadge.label}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Complexity Method:</span>
                <span className="ml-2 text-slate-300">
                  {target.complexity_method === 'radon' ? 'Radon CC' : 'Heuristic'}
                </span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex gap-4">
                <span>
                  <span className="text-slate-500">Functions:</span>
                  <span className="ml-2 text-slate-300">
                    {target.function_count}
                  </span>
                </span>
                <span>
                  <span className="text-slate-500">Classes:</span>
                  <span className="ml-2 text-slate-300">
                    {target.class_count}
                  </span>
                </span>
              </div>
              <div className="flex gap-4">
                <span>
                  <span className="text-slate-500">Churn (90d):</span>
                  <span className="ml-2 text-slate-300">
                    {target.commit_count_90d} commits
                  </span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="text-slate-500">Tests:</span>
                  {target.test_file_exists ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  ) : (
                    <XCircle className="w-3 h-3 text-red-400" />
                  )}
                </span>
              </div>
              <div className="flex gap-4">
                <span>
                  <span className="text-slate-500">Signals:</span>
                  <span className="ml-2 text-slate-300">
                    {target.structural_signals} structural / {target.impact_signals} impact
                  </span>
                </span>
                <span>
                  <span className="text-slate-500">Score:</span>
                  <span className="ml-2 text-slate-300">{target.promotion_score}</span>
                </span>
              </div>
              {target.refactor_issues.length > 0 && (
                <div>
                  <span className="text-slate-500 block mb-1">Issues:</span>
                  <div className="flex flex-wrap gap-1">
                    {target.refactor_issues.map((issue) => {
                      const s = getIssueStyle(issue)
                      return (
                        <span
                          key={issue}
                          className={cn('px-1.5 py-0.5 rounded border text-[11px]', s.color)}
                        >
                          {s.label}
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}
              {target.promotion_reasons.length > 0 && (
                <div>
                  <span className="text-slate-500 block mb-1">Promotion Evidence:</span>
                  <ul className="space-y-1 text-slate-300">
                    {target.promotion_reasons.map((reason) => (
                      <li key={reason}>- {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              {target.suppression_reasons.length > 0 && (
                <div>
                  <span className="text-slate-500 block mb-1">Held Back Because:</span>
                  <ul className="space-y-1 text-slate-300">
                    {target.suppression_reasons.map((reason) => (
                      <li key={reason}>- {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              {onFileSelect && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onFileSelect(target.path)
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  View in Explorer
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
