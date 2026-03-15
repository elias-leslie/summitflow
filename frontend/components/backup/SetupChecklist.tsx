'use client'

import { useState } from 'react'
import { clsx } from 'clsx'
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Database,
  HardDrive,
  Loader2,
  ListChecks,
  Play,
  Server,
  ShieldCheck,
} from 'lucide-react'
import Link from 'next/link'
import {
  type BackupHealthItem,
  type BackupSource,
  type StorageStatus,
  type WalStatus,
  createBackupSource,
  createSourceBackup,
  enableWalArchiving,
  updateBackupSource,
} from '@/lib/api/backups'

// ─── Step definitions ─────────────────────────────────────────

interface Step {
  id: string
  icon: React.ReactNode
  title: string
  description: string
  complete: boolean
}

function computeSteps(
  storageStatus: StorageStatus | undefined,
  sources: BackupSource[],
  healthItems: BackupHealthItem[],
  walStatus: WalStatus | undefined,
): Step[] {
  const hasStorage = storageStatus?.configured ?? false
  const hasSources = sources.length > 0
  const hasSchedules = sources.some((s) => s.enabled)
  const hasInfra = sources.some((s) => s.source_type === 'infrastructure')
  const infraHealthy =
    hasInfra &&
    healthItems.some(
      (h) => h.source_type === 'infrastructure' && h.health_status !== 'red',
    )

  const failingCount = healthItems.filter(
    (h) => h.health_status === 'red',
  ).length

  return [
    {
      id: 'storage',
      icon: <HardDrive className="w-4 h-4" />,
      title: 'Remote storage',
      description: hasStorage
        ? `Backups sent to ${storageStatus?.default_backend_name ?? 'remote storage'}`
        : 'Set up a remote destination (NAS, file server) so backups survive even if this machine fails.',
      complete: hasStorage,
    },
    {
      id: 'sources',
      icon: <ListChecks className="w-4 h-4" />,
      title: 'Backup sources',
      description: hasSources
        ? failingCount > 0
          ? `${sources.length} sources registered, but ${failingCount} ha${failingCount === 1 ? 's' : 've'} a failed last backup — check the history below`
          : `${sources.length} sources registered, schedules active, latest backups succeeded`
        : 'Sources define what gets backed up: project code and databases, config, workspaces.',
      complete: hasSources && hasSchedules && failingCount === 0,
    },
    {
      id: 'infra',
      icon: <Server className="w-4 h-4" />,
      title: 'System backup',
      description: hasInfra
        ? infraHealthy
          ? 'PostgreSQL roles, databases, and server config are backed up'
          : 'System backup source exists but last backup failed — check the history below'
        : 'Backs up PostgreSQL roles (users/permissions), databases, and server config. Required for full disaster recovery.',
      complete: infraHealthy,
    },
    {
      id: 'wal',
      icon: <Database className="w-4 h-4" />,
      title: 'Database change log (WAL)',
      description: walStatus?.enabled
        ? 'Active — database can be recovered to any point in time'
        : walStatus?.pending_restart
          ? 'Configured — PostgreSQL restart needed to activate'
          : 'Logs every database write between backups. Without it, data written after the last backup is lost on failure. Only covers the database, not files.',
      complete: !!(walStatus?.enabled || walStatus?.pending_restart),
    },
  ]
}

// ─── Component ──────────────────────────────────────────────────

interface SetupChecklistProps {
  storageStatus: StorageStatus | undefined
  sources: BackupSource[]
  healthItems: BackupHealthItem[]
  walStatus: WalStatus | undefined
  isLoading: boolean
  onSourceChanged: () => void
  onBackupTriggered: () => void
  onWalRefresh: () => void
}

export function SetupChecklist({
  storageStatus,
  sources,
  healthItems,
  walStatus,
  isLoading,
  onSourceChanged,
  onBackupTriggered,
  onWalRefresh,
}: SetupChecklistProps) {
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)

  const steps = computeSteps(storageStatus, sources, healthItems, walStatus)
  const doneCount = steps.filter((s) => s.complete).length
  const allDone = doneCount === steps.length

  if (isLoading) return null
  if (allDone && dismissed) return null

  const handleSetupInfra = async () => {
    setRunningAction('infra')
    setActionError(null)
    try {
      // Create source if it doesn't exist, or just trigger a backup
      const hasInfra = sources.some((s) => s.source_type === 'infrastructure')
      if (!hasInfra) {
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
      } else {
        const infraSource = sources.find(
          (s) => s.source_type === 'infrastructure',
        )!
        await createSourceBackup(infraSource.id)
      }
      onSourceChanged()
      onBackupTriggered()
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to set up system backup',
      )
    }
    setRunningAction(null)
  }

  const handleEnableWal = async () => {
    setRunningAction('wal')
    setActionError(null)
    setActionNotice(null)
    try {
      await enableWalArchiving()
      setActionNotice(
        'Database change log configured. PostgreSQL restart needed to fully activate.',
      )
      onWalRefresh()
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : 'Failed to enable WAL archiving.',
      )
    }
    setRunningAction(null)
  }

  return (
    <div className="mb-8 bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-5 h-5 text-phosphor-400" />
          <div>
            <h2 className="text-sm font-semibold text-slate-100">
              {allDone
                ? 'Backup protection fully configured'
                : doneCount === 0
                  ? 'Set up backup protection'
                  : `Backup setup — ${doneCount} of ${steps.length} complete`}
            </h2>
            {!allDone && (
              <p className="text-xs text-slate-400 mt-0.5">
                Complete the steps below to fully protect your data
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            {steps.map((step) => (
              <div
                key={step.id}
                className={clsx(
                  'w-2 h-2 rounded-full',
                  step.complete ? 'bg-green-400' : 'bg-slate-600',
                )}
              />
            ))}
          </div>
          {allDone && (
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>

      {/* Steps */}
      <div className="divide-y divide-slate-700/30">
        {steps.map((step) => (
          <div
            key={step.id}
            className={clsx(
              'px-5 py-3.5 flex items-start gap-3',
              step.complete && 'opacity-60',
            )}
          >
            <div className="mt-0.5 shrink-0">
              {step.complete ? (
                <CheckCircle2 className="w-4 h-4 text-green-400" />
              ) : (
                <span className="text-slate-500">{step.icon}</span>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p
                className={clsx(
                  'text-sm font-medium',
                  step.complete ? 'text-slate-400' : 'text-slate-200',
                )}
              >
                {step.title}
              </p>
              <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
                {step.description}
              </p>
            </div>

            {!step.complete && (
              <div className="shrink-0 mt-0.5">
                {step.id === 'storage' && (
                  <Link
                    href="/backups/setup"
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium bg-phosphor-600 text-white hover:bg-phosphor-500 transition-colors"
                  >
                    Configure
                    <ArrowRight className="w-3 h-3" />
                  </Link>
                )}
                {step.id === 'sources' && (
                  <span className="text-xs text-slate-500 italic">
                    See history below
                  </span>
                )}
                {step.id === 'infra' && (
                  <button
                    type="button"
                    onClick={handleSetupInfra}
                    disabled={runningAction === 'infra'}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50"
                  >
                    {runningAction === 'infra' ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                    {sources.some((s) => s.source_type === 'infrastructure')
                      ? 'Retry'
                      : 'Enable'}
                  </button>
                )}
                {step.id === 'wal' && (
                  <button
                    type="button"
                    onClick={handleEnableWal}
                    disabled={runningAction === 'wal'}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50"
                  >
                    {runningAction === 'wal' ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Check className="w-3 h-3" />
                    )}
                    Enable
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Restore guidance — always visible, separate from action steps */}
      <div className="px-5 py-3 border-t border-slate-700/50 bg-slate-800/30">
        <p className="text-xs text-slate-500 leading-relaxed">
          <span className="text-slate-400 font-medium">To restore:</span> expand
          any backup in the history below and click Restore. For a full server
          migration, restore the system backup first (recreates database roles),
          then restore each project individually.
        </p>
      </div>

      {/* Feedback */}
      {(actionError || actionNotice) && (
        <div className="px-5 py-3 border-t border-slate-700/50">
          {actionError && (
            <p className="text-xs text-rose-400">{actionError}</p>
          )}
          {actionNotice && !actionError && (
            <p className="text-xs text-green-400">{actionNotice}</p>
          )}
        </div>
      )}
    </div>
  )
}
