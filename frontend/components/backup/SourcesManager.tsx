'use client'

import { clsx } from 'clsx'
import { ChevronDown, FolderOpen, Loader2, Play, Save } from 'lucide-react'
import Link from 'next/link'
import { Fragment, useMemo, useState } from 'react'
import { SourceTypeBadge } from './SourceTypeBadge'
import { StatusBadge } from './StatusBadge'
import {
  type Backup,
  type BackupHealthItem,
  type BackupSource,
  createBackupSource,
  createSourceBackup,
  updateBackupSource,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

const SOURCE_CONTENTS: Record<string, string> = {
  project: 'Code, assets, and project database',
  config: 'Application settings and preferences',
  workspace: 'Shared workspace files',
  infrastructure: 'PostgreSQL roles, databases, and server config',
}

const HEALTH_DOT: Record<string, string> = {
  green: 'bg-green-400',
  yellow: 'bg-amber-400',
  red: 'bg-red-400',
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

const SELECT_CLASSES =
  'px-2 py-1 bg-slate-700 border border-slate-600 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500'

// ─── Sub-components ─────────────────────────────────────────────

function SourceRow({
  source,
  health,
  isExpanded,
  isBackingUp,
  onToggleExpand,
  onBackupNow,
}: {
  source: BackupSource
  health: BackupHealthItem | undefined
  isExpanded: boolean
  isBackingUp: boolean
  onToggleExpand: () => void
  onBackupNow: () => void
}) {
  const dotColor = HEALTH_DOT[health?.health_status ?? ''] ?? 'bg-slate-600'

  return (
    <tr
      className={clsx(
        'hover:bg-slate-700/20 transition-colors cursor-pointer',
        isExpanded && 'bg-slate-700/20',
      )}
      onClick={onToggleExpand}
    >
      <td className="px-3 py-2.5 text-center">
        <span
          className={clsx('inline-block w-2 h-2 rounded-full', dotColor)}
          title={health?.health_status ?? 'unknown'}
        />
      </td>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-200">{source.name}</span>
          <SourceTypeBadge type={source.source_type} />
        </div>
      </td>
      <td className="px-4 py-2.5">
        {source.enabled ? (
          <span className="text-sm text-slate-300">
            <span
              className={clsx(
                'inline-flex px-1.5 py-0.5 rounded text-xs font-medium',
                'bg-slate-700 text-slate-300',
              )}
            >
              {source.frequency}
            </span>
            {source.next_run_at && (
              <span className="text-slate-500 text-xs ml-2">
                next {formatDate(source.next_run_at)}
              </span>
            )}
          </span>
        ) : (
          <span className="text-xs text-slate-500">Disabled</span>
        )}
      </td>
      <td className="px-4 py-2.5">
        {health?.last_success_at ? (
          <span className="text-sm text-slate-400">
            {formatDate(health.last_success_at)}
          </span>
        ) : (
          <span className="text-sm text-slate-500">Never</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={onBackupNow}
            disabled={isBackingUp}
            className="p-1.5 text-slate-400 hover:text-phosphor-400 transition-colors disabled:opacity-50"
            title="Backup now"
          >
            {isBackingUp ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
          </button>
          <ChevronDown
            className={clsx(
              'w-4 h-4 text-slate-500 transition-transform cursor-pointer',
              isExpanded && 'rotate-180',
            )}
            onClick={onToggleExpand}
          />
        </div>
      </td>
    </tr>
  )
}

function SourceExpandedRow({
  source,
  recentBackups,
  onSaved,
}: {
  source: BackupSource
  recentBackups: Backup[]
  onSaved: () => void
}) {
  const [frequency, setFrequency] = useState<string>(source.frequency)
  const [retention, setRetention] = useState(source.retention_days)
  const [enabled, setEnabled] = useState(source.enabled)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

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
    <tr>
      <td colSpan={5} className="px-4 py-0">
        <div className="py-4 pl-6 border-l-2 border-slate-600 ml-2 space-y-4">
          {/* What's backed up + path */}
          <div className="space-y-1">
            <div className="text-xs text-slate-400">
              <span className="text-slate-500">Contains: </span>
              {SOURCE_CONTENTS[source.source_type] ?? source.source_type}
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <FolderOpen className="w-3.5 h-3.5" />
              <span className="font-mono">{source.path}</span>
            </div>
          </div>

          {/* Schedule Editor */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-slate-500">Frequency</label>
              <select
                value={frequency}
                onChange={(e) => setFrequency(e.target.value)}
                className={SELECT_CLASSES}
              >
                {FREQUENCY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-slate-500">Retention</label>
              <select
                value={retention}
                onChange={(e) => setRetention(Number(e.target.value))}
                className={SELECT_CLASSES}
              >
                {RETENTION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={() => setEnabled(!enabled)}
              className={clsx(
                'px-2.5 py-1 rounded text-xs font-medium border transition-colors',
                enabled
                  ? 'bg-green-500/15 text-green-400 border-green-500/30 hover:bg-green-500/25'
                  : 'bg-slate-700 text-slate-400 border-slate-600 hover:bg-slate-600',
              )}
            >
              {enabled ? 'Enabled' : 'Disabled'}
            </button>
            {hasChanges && (
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-phosphor-600 text-white hover:bg-phosphor-500 transition-colors disabled:opacity-50"
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
              <span className="text-xs text-green-400">Saved</span>
            )}
          </div>

          {/* Recent Backups */}
          {recentBackups.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs text-slate-500">Recent backups</p>
              {recentBackups.map((b) => (
                <div
                  key={b.id}
                  className="flex items-center gap-3 text-xs px-2.5 py-1.5 bg-slate-800/60 rounded"
                >
                  <StatusBadge status={b.status} />
                  <span className="text-slate-400">
                    {formatDate(b.completed_at ?? b.created_at)}
                  </span>
                  {b.size_bytes != null && (
                    <span className="text-slate-500 ml-auto">
                      {formatBytes(b.size_bytes)}
                    </span>
                  )}
                </div>
              ))}
              <Link
                href={`/backups/${recentBackups[0].source_id}`}
                className="inline-block text-xs text-phosphor-400 hover:text-phosphor-300 transition-colors mt-1"
              >
                View all backups for this source
              </Link>
            </div>
          )}
        </div>
      </td>
    </tr>
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
  const [expandedId, setExpandedId] = useState<string | null>(null)
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
      await updateBackupSource(source.id, { enabled: true, frequency: 'daily', retention_days: 30 })
      await createSourceBackup(source.id)
      onBackupTriggered()
      onSourceChanged()
    } catch {
      /* ignore */
    }
    setCreatingInfra(false)
  }

  return (
    <section className="mb-8">
      <h2 className="text-sm font-medium text-slate-300 mb-3">
        Sources & Schedules
      </h2>
      <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-x-auto">
        <table className="w-full min-w-[700px]">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-800/80">
              <th className="w-8 px-3 py-2.5" />
              <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                Source
              </th>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                Schedule
              </th>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                Last Backup
              </th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-400 uppercase tracking-wider w-24" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {sources.map((source) => {
              const isExpanded = expandedId === source.id
              return (
                <Fragment key={source.id}>
                  <SourceRow
                    source={source}
                    health={healthMap[source.id]}
                    isExpanded={isExpanded}
                    isBackingUp={backingUpId === source.id}
                    onToggleExpand={() =>
                      setExpandedId(isExpanded ? null : source.id)
                    }
                    onBackupNow={() => handleBackupNow(source.id)}
                  />
                  {isExpanded && (
                    <SourceExpandedRow
                      key={source.updated_at ?? source.id}
                      source={source}
                      recentBackups={backupsBySource[source.id] ?? []}
                      onSaved={onSourceChanged}
                    />
                  )}
                </Fragment>
              )
            })}

            {/* System Backup row when no infrastructure source exists */}
            {!hasInfraSource && (
              <tr className="hover:bg-slate-700/20 transition-colors">
                <td className="px-3 py-2.5 text-center">
                  <span className="inline-block w-2 h-2 rounded-full bg-slate-600" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-400">
                      System Backup
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border leading-none bg-emerald-500/15 text-emerald-400 border-emerald-500/25">
                      system
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    PostgreSQL roles, databases, and server configuration
                  </p>
                </td>
                <td className="px-4 py-2.5 text-sm text-slate-500">
                  Not configured
                </td>
                <td className="px-4 py-2.5 text-sm text-slate-500">Never</td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={handleCreateInfra}
                    disabled={creatingInfra}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50 ml-auto"
                  >
                    {creatingInfra ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                    Set up & run
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
