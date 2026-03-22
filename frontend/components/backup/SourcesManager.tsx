'use client'

import { clsx } from 'clsx'
import {
  ChevronRight,
  FlaskConical,
  FolderOpen,
  Loader2,
  Play,
  Save,
} from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { SourceTypeBadge } from './SourceTypeBadge'
import { StatusBadge } from './StatusBadge'
import {
  type Backup,
  type BackupHealthItem,
  type BackupSource,
  type CoverageResponse,
  createBackupSource,
  createSourceBackup,
  fetchInfraCoverage,
  runRestoreDrill,
  updateBackupSource,
} from '@/lib/api/backups'
import { formatBytes, formatDate, formatTimeAgo } from '@/lib/format'

const SOURCE_CONTENTS: Record<string, string> = {
  project: 'Code, assets, and project database',
  config: 'Application settings and preferences',
  workspace: 'Shared workspace files',
  infrastructure: 'PostgreSQL, Redis, Hatchet config, and secrets',
}

// ─── Restore Confidence Badge ─────────────────────────────────

const CONFIDENCE_STYLES: Record<string, string> = {
  verified: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/20',
  stale: 'bg-amber-500/12 text-amber-400 border-amber-500/20',
  partial: 'bg-amber-500/12 text-amber-400 border-amber-500/20',
  untested: 'bg-slate-700/50 text-slate-500 border-slate-600/40',
}

function RestoreConfidenceBadge({ confidence }: { confidence: string | null }) {
  const label = confidence ?? 'untested'
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] uppercase tracking-[0.12em] font-medium border leading-none',
        CONFIDENCE_STYLES[label] ?? CONFIDENCE_STYLES.untested,
      )}
    >
      <span
        className={clsx(
          'w-1.5 h-1.5 rounded-full',
          label === 'verified' && 'bg-emerald-400',
          (label === 'stale' || label === 'partial') && 'bg-amber-400',
          label === 'untested' && 'bg-slate-500',
        )}
      />
      {label}
    </span>
  )
}

// ─── Coverage Chips ─────────────────────────────────────────────

function CoverageChips({ coverage }: { coverage: CoverageResponse | null }) {
  if (!coverage) return null

  const components = coverage.result?.components ?? coverage.contract.map((c) => ({
    key: c.key, label: c.label, category: c.category, present: false, error: null,
  }))

  return (
    <div className="flex flex-wrap gap-1.5">
      {components.map((comp) => {
        if (comp.category === 'excluded') {
          return (
            <span
              key={comp.key}
              className="inline-flex items-center gap-1.5 rounded bg-slate-900/40 px-2 py-1 text-[10px] text-slate-600 line-through border border-slate-800/30"
              title={`Excluded: ${comp.key}`}
            >
              {comp.label}
            </span>
          )
        }
        const isOptional = comp.category === 'optional'
        return (
          <span
            key={comp.key}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded px-2 py-1 text-[10px] border',
              isOptional
                ? 'bg-slate-900/40 text-slate-500 border-slate-800/30'
                : comp.present
                  ? 'bg-emerald-500/8 text-emerald-400/80 border-emerald-500/15'
                  : 'bg-red-500/8 text-red-400/80 border-red-500/15',
            )}
          >
            <span
              className={clsx(
                'w-1.5 h-1.5 rounded-full shrink-0',
                isOptional
                  ? 'bg-slate-600'
                  : comp.present
                    ? 'bg-emerald-500'
                    : 'bg-red-500',
              )}
            />
            {comp.label}
          </span>
        )
      })}
    </div>
  )
}

const HEALTH_ACCENT: Record<string, string> = {
  green: 'border-l-emerald-500',
  yellow: 'border-l-amber-500',
  red: 'border-l-red-500',
}

const HEALTH_DOT: Record<string, string> = {
  green: 'bg-emerald-500',
  yellow: 'bg-amber-500',
  red: 'bg-red-500',
}

const FREQUENCY_OPTIONS = [
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
]

const RETENTION_OPTIONS = [
  { value: 7, label: '7 days' },
  { value: 14, label: '14 days' },
  { value: 30, label: '30 days' },
  { value: 60, label: '60 days' },
  { value: 90, label: '90 days' },
]

// ─── Source Card ─────────────────────────────────────────────────

function SourceCard({
  source,
  health,
  recentBackups,
  isBackingUp,
  onBackupNow,
  onSaved,
}: {
  source: BackupSource
  health: BackupHealthItem | undefined
  recentBackups: Backup[]
  isBackingUp: boolean
  onBackupNow: () => void
  onSaved: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [frequency, setFrequency] = useState<string>(source.frequency)
  const [retention, setRetention] = useState(source.retention_days)
  const [enabled, setEnabled] = useState(source.enabled)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [drilling, setDrilling] = useState(false)
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null)

  const isInfra = source.source_type === 'infrastructure'

  // Fetch coverage for infrastructure sources when expanded
  useEffect(() => {
    if (expanded && isInfra && !coverage) {
      fetchInfraCoverage().then(setCoverage).catch(() => {})
    }
  }, [expanded, isInfra, coverage])

  const handleDrill = useCallback(async () => {
    setDrilling(true)
    try {
      await runRestoreDrill()
    } catch {
      /* parent refetch */
    }
    setDrilling(false)
  }, [])

  const healthStatus = health?.health_status ?? ''
  const accentClass = HEALTH_ACCENT[healthStatus] ?? 'border-l-slate-600'
  const dotClass = HEALTH_DOT[healthStatus] ?? 'bg-slate-600'

  const hasChanges =
    frequency !== source.frequency ||
    retention !== source.retention_days ||
    enabled !== source.enabled

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateBackupSource(source.id, {
        frequency,
        retention_days: retention,
        enabled,
      })
      onSaved()
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      /* parent will refetch */
    }
    setSaving(false)
  }

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
        accentClass,
        expanded
          ? 'border-slate-700/80 shadow-lg shadow-black/20'
          : 'hover:bg-slate-800/60',
      )}
    >
      {/* Header row */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => e.key === 'Enter' && setExpanded(!expanded)}
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none group"
      >
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-all duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />
        <div
          className={clsx('w-2 h-2 rounded-full shrink-0', dotClass)}
          title={healthStatus || 'unknown'}
        />
        <span className="font-medium text-white text-sm truncate">
          {source.name}
        </span>
        <SourceTypeBadge type={source.source_type} />

        {/* Schedule info */}
        <div className="hidden sm:flex items-center gap-2 text-[11px] text-slate-500 ml-auto mr-2">
          {source.enabled ? (
            <>
              <span className="rounded bg-slate-700/70 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                {source.frequency}
              </span>
              {health?.last_success_at && (
                <span>{formatTimeAgo(health.last_success_at)}</span>
              )}
            </>
          ) : (
            <span className="text-slate-600">Disabled</span>
          )}
        </div>

        {/* Action buttons */}
        <div
          className="flex items-center gap-1.5 shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          {isInfra && (
            <button
              type="button"
              onClick={handleDrill}
              disabled={drilling}
              className="text-[11px] px-2 py-1 rounded bg-slate-700/40 text-slate-400 hover:bg-slate-700/60 disabled:opacity-40 transition-colors"
              title="Run restore drill"
            >
              {drilling ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <FlaskConical className="w-3 h-3" />
              )}
            </button>
          )}
          <button
            type="button"
            onClick={onBackupNow}
            disabled={isBackingUp}
            className="text-[11px] px-2 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 disabled:opacity-40 transition-colors"
            title="Backup now"
          >
            {isBackingUp ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Play className="w-3 h-3" />
            )}
          </button>
        </div>
      </div>

      {/* Expandable content */}
      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-4 space-y-4">
            {/* What's backed up + path */}
            <div className="space-y-1.5">
              {isInfra && coverage ? (
                <CoverageChips coverage={coverage} />
              ) : (
                <div className="text-xs text-slate-400">
                  {SOURCE_CONTENTS[source.source_type] ?? source.source_type}
                </div>
              )}
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <FolderOpen className="w-3.5 h-3.5 shrink-0" />
                <span className="font-mono truncate">{source.path}</span>
              </div>
            </div>

            {/* Restore confidence — infrastructure only */}
            {isInfra && health && (
              <div className="flex items-center gap-3 px-2.5 py-2 rounded bg-slate-950/40 border border-slate-800/30">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                    Restore
                  </span>
                  <RestoreConfidenceBadge confidence={health.restore_confidence} />
                </div>
                {health.last_drill_at && (
                  <span className="text-[10px] text-slate-600 ml-auto">
                    Drilled {formatTimeAgo(health.last_drill_at)}
                  </span>
                )}
                {health.last_drill_backup_id && (
                  <span className="text-[10px] text-slate-600 font-mono truncate max-w-[80px]">
                    {health.last_drill_backup_id}
                  </span>
                )}
              </div>
            )}

            {/* Metrics row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
              <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Frequency
                </div>
                <div className="truncate text-xs text-slate-200">
                  {source.frequency}
                </div>
              </div>
              <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Retention
                </div>
                <div className="truncate text-xs text-slate-200">
                  {source.retention_days}d
                </div>
              </div>
              <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Last Backup
                </div>
                <div className="truncate text-xs text-slate-200">
                  {health?.last_success_at
                    ? formatTimeAgo(health.last_success_at)
                    : 'Never'}
                </div>
              </div>
              <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Next Run
                </div>
                <div className="truncate text-xs text-slate-200">
                  {source.next_run_at
                    ? formatTimeAgo(source.next_run_at)
                    : '-'}
                </div>
              </div>
            </div>

            {/* Schedule Editor */}
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={frequency}
                onChange={(e) => setFrequency(e.target.value)}
                className="px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
              >
                {FREQUENCY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <select
                value={retention}
                onChange={(e) => setRetention(Number(e.target.value))}
                className="px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
              >
                {RETENTION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setEnabled(!enabled)}
                className={clsx(
                  'text-[11px] px-2 py-1 rounded border transition-colors',
                  enabled
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20'
                    : 'bg-slate-700/50 text-slate-500 border-slate-600/50 hover:text-slate-400',
                )}
              >
                {enabled ? 'Enabled' : 'Disabled'}
              </button>
              {hasChanges && (
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 disabled:opacity-40 transition-colors"
                >
                  {saving ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Save className="w-3 h-3" />
                  )}
                  Save
                </button>
              )}
              {saved && (
                <span className="text-[11px] text-emerald-400">Saved</span>
              )}
            </div>

            {/* Recent Backups */}
            {recentBackups.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Recent backups
                </p>
                {recentBackups.map((b) => (
                  <div
                    key={b.id}
                    className="flex items-center gap-3 text-xs px-2.5 py-1.5 rounded bg-slate-950/40 border border-slate-800/40"
                  >
                    <StatusBadge status={b.status} />
                    <span className="text-slate-400">
                      {formatDate(b.completed_at ?? b.created_at)}
                    </span>
                    {b.size_bytes != null && (
                      <span className="text-slate-500 ml-auto font-mono">
                        {formatBytes(b.size_bytes)}
                      </span>
                    )}
                  </div>
                ))}
                <Link
                  href={`/backups/${recentBackups[0].source_id}`}
                  className="inline-block text-[11px] text-phosphor-400 hover:text-phosphor-300 transition-colors mt-1"
                >
                  View all &rarr;
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Infrastructure Setup Card ───────────────────────────────────

function InfraSetupCard({
  isCreating,
  onCreate,
}: {
  isCreating: boolean
  onCreate: () => void
}) {
  return (
    <div className="rounded-lg border-l-[3px] border-l-slate-600 border border-slate-700/60 bg-slate-800/40 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-slate-600 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">System Backup</span>
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-emerald-400 border border-emerald-500/20">
              system
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            PostgreSQL roles, databases, and server configuration
          </p>
        </div>
        <button
          type="button"
          onClick={onCreate}
          disabled={isCreating}
          className="text-[11px] px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors flex items-center gap-1.5 shrink-0"
        >
          {isCreating ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Play className="w-3 h-3" />
          )}
          Set up & run
        </button>
      </div>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────

interface SourcesManagerProps {
  sources: BackupSource[]
  healthItems: BackupHealthItem[]
  recentBackups: Backup[]
  onSourceChanged: () => void
  onBackupTriggered: () => void
}

export function SourcesManager({
  sources,
  healthItems,
  recentBackups,
  onSourceChanged,
  onBackupTriggered,
}: SourcesManagerProps) {
  const [backingUpId, setBackingUpId] = useState<string | null>(null)
  const [creatingInfra, setCreatingInfra] = useState(false)

  const hasInfraSource = sources.some(
    (s) => s.source_type === 'infrastructure',
  )

  const healthMap = useMemo(() => {
    const map: Record<string, BackupHealthItem> = {}
    for (const h of healthItems) map[h.source_id] = h
    return map
  }, [healthItems])

  const backupsBySource = useMemo(() => {
    const map: Record<string, Backup[]> = {}
    for (const b of recentBackups) {
      if (!map[b.source_id]) map[b.source_id] = []
      if (map[b.source_id].length < 3) map[b.source_id].push(b)
    }
    return map
  }, [recentBackups])

  const handleBackupNow = async (sourceId: string) => {
    setBackingUpId(sourceId)
    try {
      await createSourceBackup(sourceId)
      onBackupTriggered()
    } catch {
      /* parent refetch will show state */
    }
    setBackingUpId(null)
  }

  const handleCreateInfra = async () => {
    setCreatingInfra(true)
    try {
      const source = await createBackupSource({
        id: 'infrastructure',
        name: 'System Backup',
        path: '/',
        source_type: 'infrastructure',
      })
      await updateBackupSource(source.id, {
        enabled: true,
        frequency: 'daily',
        retention_days: 30,
      })
      await createSourceBackup(source.id)
      onBackupTriggered()
      onSourceChanged()
    } catch {
      /* ignore */
    }
    setCreatingInfra(false)
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
          Sources & Schedules
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">
          What gets backed up and when
        </p>
      </div>

      <div className="space-y-2">
        {sources.map((source) => (
          <SourceCard
            key={source.id}
            source={source}
            health={healthMap[source.id]}
            recentBackups={backupsBySource[source.id] ?? []}
            isBackingUp={backingUpId === source.id}
            onBackupNow={() => handleBackupNow(source.id)}
            onSaved={onSourceChanged}
          />
        ))}

        {!hasInfraSource && (
          <InfraSetupCard
            isCreating={creatingInfra}
            onCreate={handleCreateInfra}
          />
        )}
      </div>
    </section>
  )
}
