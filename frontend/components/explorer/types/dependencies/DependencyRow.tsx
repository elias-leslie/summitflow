/**
 * DependencyRow - Row content renderer for package dependencies
 *
 * Displays package name, version, type badge (Python/Node.js),
 * vulnerability indicators, and outdated status.
 */

import { AlertTriangle, CheckCircle, Package, Shield, ShieldAlert, ShieldX } from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'
import { ColumnValue } from '../../DataList'

interface DependencyRowProps {
  entry: ExplorerEntry
}

// Type badge colors
const typeBadgeStyles = {
  python: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
  nodejs: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
} as const

// Vulnerability badge logic
function getVulnBadge(vulns: { critical?: number; high?: number; medium?: number; low?: number } | undefined) {
  if (!vulns) return { icon: Shield, color: 'text-slate-500', label: '-' }

  const critical = vulns.critical ?? 0
  const high = vulns.high ?? 0
  const medium = vulns.medium ?? 0
  const total = critical + high + medium + (vulns.low ?? 0)

  if (critical > 0 || high > 0) {
    return {
      icon: ShieldX,
      color: 'text-red-400',
      bgColor: 'bg-red-500/10',
      label: `${critical + high}`,
    }
  }
  if (medium > 0) {
    return {
      icon: ShieldAlert,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      label: `${medium}`,
    }
  }
  if (total === 0) {
    return {
      icon: Shield,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      label: '✓',
    }
  }
  return {
    icon: Shield,
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10',
    label: `${total}`,
  }
}

export function DependencyRow({ entry }: DependencyRowProps) {
  const meta = entry.metadata
  const packageType = (meta.package_type as 'python' | 'nodejs') || 'python'
  const lockedVersion = meta.locked_version as string | null
  const isOutdated = meta.is_outdated as boolean
  const isWorkspaceRef = meta.is_workspace_ref as boolean
  const isDevDep = meta.is_dev_dependency as boolean
  const vulns = meta.vulnerabilities as { critical?: number; high?: number; medium?: number; low?: number } | undefined

  const vulnBadge = getVulnBadge(vulns)
  const VulnIcon = vulnBadge.icon

  return (
    <>
      {/* Package icon */}
      <span className="flex-shrink-0 text-slate-500">
        <Package className="w-4 h-4 text-indigo-400/70" />
      </span>

      {/* Package name with optional badges */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <ColumnValue className="truncate font-medium text-slate-200">
          {entry.name}
        </ColumnValue>
        {isDevDep && (
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
            dev
          </span>
        )}
        {isWorkspaceRef && (
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-purple-500/20 text-purple-400 border border-purple-500/30">
            workspace
          </span>
        )}
      </div>

      {/* Version */}
      <ColumnValue width="100px" mono muted={!lockedVersion} className="text-xs">
        {lockedVersion || '-'}
      </ColumnValue>

      {/* Type badge */}
      <ColumnValue width="80px" align="center">
        <span
          className={cn(
            'inline-flex px-2 py-0.5 text-[10px] font-semibold uppercase rounded border',
            typeBadgeStyles[packageType],
          )}
        >
          {packageType === 'python' ? 'PY' : 'JS'}
        </span>
      </ColumnValue>

      {/* Vulnerability badge */}
      <ColumnValue width="90px" align="center">
        <span
          className={cn(
            'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium',
            vulnBadge.bgColor,
            vulnBadge.color,
          )}
        >
          <VulnIcon className="w-3 h-3" />
          <span>{vulnBadge.label}</span>
        </span>
      </ColumnValue>

      {/* Outdated status */}
      <ColumnValue width="80px" align="right">
        {isOutdated ? (
          <span className="inline-flex items-center gap-1 text-amber-400 text-xs">
            <AlertTriangle className="w-3 h-3" />
            <span>Update</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-emerald-400/70 text-xs">
            <CheckCircle className="w-3 h-3" />
            <span>Current</span>
          </span>
        )}
      </ColumnValue>
    </>
  )
}
