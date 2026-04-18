/**
 * ArchitectureDetail - Detail panel for architecture entries
 *
 * Shows full violation details, affected files, and recommendations.
 */

import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  Copy,
  FileCode,
  Layers,
} from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'

interface ArchitectureDetailProps {
  entry: ExplorerEntry
}

interface Violation {
  violation_type: string
  file_path: string
  detail: string
  severity: string
  line_start?: number
  line_end?: number
  related_files?: string[]
}

// Severity color mapping
const severityStyles = {
  error: {
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    text: 'text-red-400',
  },
  warning: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
  },
} as const

// Violation type labels and icons
const violationTypeInfo = {
  parallel_implementation: {
    label: 'Parallel Implementation',
    icon: Code2,
    description: 'Multiple implementations of the same functionality',
  },
  missing_infrastructure: {
    label: 'Missing Infrastructure',
    icon: AlertTriangle,
    description: 'Missing caching, error handling, or observability',
  },
  duplicate_utility: {
    label: 'Duplicate Utility',
    icon: Copy,
    description: 'Literal code duplication detected',
  },
} as const

export function ArchitectureDetail({ entry }: ArchitectureDetailProps) {
  const meta = entry.metadata
  const scanScope = (meta.scan_scope as string) || 'both'
  const violations = (meta.violations as Violation[]) || []
  const violationCounts = meta.violation_counts as
    | {
        parallel_implementation?: number
        missing_infrastructure?: number
        duplicate_utility?: number
      }
    | undefined
  const filesAnalyzed = (meta.files_with_violations as number) ?? 0
  const scanDurationMs = (meta.last_scan_duration_ms as number) ?? 0

  const totalViolations =
    (violationCounts?.parallel_implementation ?? 0) +
    (violationCounts?.missing_infrastructure ?? 0) +
    (violationCounts?.duplicate_utility ?? 0)

  return (
    <div className="space-y-4">
      {/* Module header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-rose-500/10 border border-rose-500/30">
          <Layers className="w-5 h-5 text-rose-400" />
        </div>
        <div>
          <h3 className="font-semibold text-slate-200">{entry.name}</h3>
          <p className="text-xs text-slate-500">
            {scanScope === 'backend'
              ? 'Backend Module'
              : scanScope === 'frontend'
                ? 'Frontend Module'
                : 'Full Stack Module'}
          </p>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Affected Files
          </span>
          <p className="font-mono text-sm text-slate-300 mt-1">
            {filesAnalyzed}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Violations
          </span>
          <p
            className={cn(
              'font-mono text-sm mt-1',
              totalViolations > 0 ? 'text-amber-400' : 'text-emerald-400',
            )}
          >
            {totalViolations}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Scan Time
          </span>
          <p className="font-mono text-sm text-slate-300 mt-1">
            {scanDurationMs > 0 ? `${scanDurationMs}ms` : '-'}
          </p>
        </div>
      </div>

      {/* Violation breakdown by type */}
      {totalViolations > 0 && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Violations by Type
          </span>
          <div className="flex gap-2 mt-3">
            {Object.entries(violationCounts || {}).map(([type, count]) => {
              if (!count) return null
              const info =
                violationTypeInfo[type as keyof typeof violationTypeInfo]
              if (!info) return null
              const Icon = info.icon
              const isError = type === 'parallel_implementation'

              return (
                <span
                  key={type}
                  className={cn(
                    'px-2 py-1 text-xs font-medium rounded border flex items-center gap-1.5',
                    isError
                      ? 'bg-red-500/10 border-red-500/30 text-red-400'
                      : 'bg-amber-500/10 border-amber-500/30 text-amber-400',
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {count} {info.label}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* All clear indicator */}
      {totalViolations === 0 && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <p className="text-sm text-emerald-300">
            No architecture violations detected
          </p>
        </div>
      )}

      {/* Violation details */}
      {violations.length > 0 && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Violation Details
          </span>
          <div className="mt-3 space-y-2">
            {violations.slice(0, 10).map((violation, idx) => {
              const styles =
                severityStyles[
                  violation.severity as keyof typeof severityStyles
                ] || severityStyles.warning
              const typeInfo =
                violationTypeInfo[
                  violation.violation_type as keyof typeof violationTypeInfo
                ]
              const Icon = typeInfo?.icon || AlertTriangle

              return (
                <div
                  key={idx}
                  className={cn(
                    'p-3 rounded-lg border',
                    styles.bg,
                    styles.border,
                  )}
                >
                  <div className="flex items-start gap-2">
                    <Icon
                      className={cn(
                        'w-4 h-4 flex-shrink-0 mt-0.5',
                        styles.text,
                      )}
                    />
                    <div className="flex-1 min-w-0">
                      <p className={cn('text-sm font-medium', styles.text)}>
                        {typeInfo?.label || violation.violation_type}
                      </p>
                      <p className="text-xs text-slate-300 mt-1">
                        {violation.detail}
                      </p>
                      {violation.file_path && (
                        <div className="flex items-center gap-1.5 mt-2">
                          <FileCode className="w-3.5 h-3.5 text-slate-500" />
                          <span className="font-mono text-xs text-slate-400 truncate">
                            {violation.file_path}
                            {violation.line_start && `:${violation.line_start}`}
                          </span>
                        </div>
                      )}
                      {violation.related_files &&
                        violation.related_files.length > 0 && (
                          <div className="mt-2 pl-5">
                            <span className="text-[10px] text-slate-500 uppercase">
                              Related files:
                            </span>
                            <ul className="mt-1 space-y-0.5">
                              {violation.related_files
                                .slice(0, 3)
                                .map((file, fidx) => (
                                  <li
                                    key={fidx}
                                    className="font-mono text-xs text-slate-500"
                                  >
                                    {file}
                                  </li>
                                ))}
                            </ul>
                          </div>
                        )}
                    </div>
                  </div>
                </div>
              )
            })}
            {violations.length > 10 && (
              <p className="text-xs text-slate-500 pl-6">
                + {violations.length - 10} more violations
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
