/**
 * DependencyDetail - Detail panel for package dependencies
 *
 * Shows full version info, security advisories, source file,
 * and update recommendations.
 */

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  FileCode,
  Package,
  Shield,
  ShieldAlert,
  ShieldX,
} from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'

interface DependencyDetailProps {
  entry: ExplorerEntry
}

export function DependencyDetail({ entry }: DependencyDetailProps) {
  const meta = entry.metadata
  const packageType = (meta.package_type as 'python' | 'nodejs') || 'python'
  const constraint = meta.constraint as string | null
  const lockedVersion = meta.locked_version as string | null
  const latestVersion = meta.latest_version as string | null
  const isOutdated = meta.is_outdated as boolean
  const isWorkspaceRef = meta.is_workspace_ref as boolean
  const isDevDep = meta.is_dev_dependency as boolean
  // Support both deduplicated (source_files) and raw (source_file) entries
  const sourceFiles = (meta.source_files as string[] | undefined) || (meta.source_file ? [meta.source_file as string] : [])
  const versionConflict = meta.version_conflict as boolean | undefined
  const allVersions = (meta.all_versions as string[] | undefined) || []
  const vulns = meta.vulnerabilities as { critical?: number; high?: number; medium?: number; low?: number } | undefined
  const advisories = (meta.audit_advisories as string[]) || []

  const critical = vulns?.critical ?? 0
  const high = vulns?.high ?? 0
  const medium = vulns?.medium ?? 0
  const low = vulns?.low ?? 0
  const totalVulns = critical + high + medium + low

  // Registry URL
  const registryUrl =
    packageType === 'python'
      ? `https://pypi.org/project/${entry.name}/`
      : `https://www.npmjs.com/package/${entry.name}`

  return (
    <div className="space-y-4">
      {/* Package header with type */}
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'flex items-center justify-center w-10 h-10 rounded-lg',
            packageType === 'python'
              ? 'bg-sky-500/10 border border-sky-500/30'
              : 'bg-emerald-500/10 border border-emerald-500/30',
          )}
        >
          <Package
            className={cn(
              'w-5 h-5',
              packageType === 'python' ? 'text-sky-400' : 'text-emerald-400',
            )}
          />
        </div>
        <div>
          <h3 className="font-semibold text-slate-200">{entry.name}</h3>
          <p className="text-xs text-slate-500 capitalize">
            {packageType === 'python' ? 'Python Package' : 'Node.js Package'}
            {isDevDep && ' · Dev Dependency'}
            {isWorkspaceRef && ' · Workspace Reference'}
          </p>
        </div>
        <a
          href={registryUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto p-2 rounded hover:bg-slate-700/50 text-slate-400 hover:text-slate-200 transition-colors"
          title={`View on ${packageType === 'python' ? 'PyPI' : 'npm'}`}
        >
          <ExternalLink className="w-4 h-4" />
        </a>
      </div>

      {/* Version info */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Constraint
          </span>
          <p className="font-mono text-sm text-slate-300 mt-1">
            {constraint || '-'}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Installed
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {lockedVersion || '-'}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Latest
          </span>
          <p
            className={cn(
              'font-mono text-sm mt-1',
              isOutdated ? 'text-amber-400' : 'text-emerald-400',
            )}
          >
            {latestVersion || '-'}
          </p>
        </div>
      </div>

      {/* Update recommendation */}
      {isOutdated && lockedVersion && latestVersion && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-amber-300">
              Update Available
            </p>
            <p className="text-xs text-amber-400/70 mt-0.5 font-mono">
              {lockedVersion}
              <ArrowRight className="w-3 h-3 inline mx-1.5 opacity-50" />
              {latestVersion}
            </p>
          </div>
        </div>
      )}

      {/* Security section */}
      <div className="pt-2 border-t border-slate-700/50">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Security Status
          </span>
          {totalVulns === 0 ? (
            <span className="flex items-center gap-1 text-xs text-emerald-400">
              <Shield className="w-3.5 h-3.5" />
              No vulnerabilities
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-red-400">
              <ShieldX className="w-3.5 h-3.5" />
              {totalVulns} {totalVulns === 1 ? 'vulnerability' : 'vulnerabilities'}
            </span>
          )}
        </div>

        {/* Vulnerability breakdown */}
        {totalVulns > 0 && (
          <div className="flex gap-2 mt-3">
            {critical > 0 && (
              <span className="px-2 py-1 text-xs font-medium rounded border bg-red-500/10 border-red-500/30 text-red-400">
                {critical} Critical
              </span>
            )}
            {high > 0 && (
              <span className="px-2 py-1 text-xs font-medium rounded border bg-red-500/10 border-red-500/30 text-red-400">
                {high} High
              </span>
            )}
            {medium > 0 && (
              <span className="px-2 py-1 text-xs font-medium rounded border bg-amber-500/10 border-amber-500/30 text-amber-400">
                {medium} Medium
              </span>
            )}
            {low > 0 && (
              <span className="px-2 py-1 text-xs font-medium rounded border bg-slate-500/10 border-slate-500/30 text-slate-400">
                {low} Low
              </span>
            )}
          </div>
        )}

        {/* Advisories */}
        {advisories.length > 0 && (
          <div className="mt-3 space-y-2">
            {advisories.slice(0, 5).map((advisory, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2 p-2 rounded bg-slate-800/50 border border-slate-700/50"
              >
                <ShieldAlert className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-slate-300 leading-relaxed">
                  {advisory}
                </p>
              </div>
            ))}
            {advisories.length > 5 && (
              <p className="text-xs text-slate-500 pl-6">
                + {advisories.length - 5} more advisories
              </p>
            )}
          </div>
        )}

        {/* All clear indicator */}
        {totalVulns === 0 && (
          <div className="flex items-center gap-2 mt-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <p className="text-sm text-emerald-300">
              No known security vulnerabilities
            </p>
          </div>
        )}
      </div>

      {/* Version conflict warning */}
      {versionConflict && allVersions.length > 1 && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-amber-300">
              Multiple Versions Detected
            </p>
            <p className="text-xs text-amber-400/70 mt-0.5 font-mono">
              {allVersions.join(', ')}
            </p>
          </div>
        </div>
      )}

      {/* Source files */}
      {sourceFiles.length > 0 && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            {sourceFiles.length === 1 ? 'Source File' : `Source Files (${sourceFiles.length})`}
          </span>
          <div className="mt-2 space-y-1.5">
            {sourceFiles.map((file, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <FileCode className="w-4 h-4 text-slate-500 flex-shrink-0" />
                <p className="font-mono text-xs text-slate-400 truncate">
                  {file}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
