'use client'

import { clsx } from 'clsx'
import {
  ArrowRight,
  CheckCircle2,
  HardDrive,
  ListChecks,
  Loader2,
  Play,
  Server,
  ShieldCheck,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import {
  type BackupHealthItem,
  type BackupSource,
  createBackupSource,
  createSourceBackup,
  type StorageStatus,
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
): Step[] {
  const hasStorage = storageStatus?.configured ?? false
  const hasSources = sources.length > 0
  const hasSchedules = sources.some((s) => s.enabled)
  const hasInfra = sources.some((s) => s.source_type === 'infrastructure')
  const infraHealth = healthItems.find(
    (h) => h.source_type === 'infrastructure',
  )
  const infraHealthy =
    hasInfra && infraHealth != null && infraHealth.health_status !== 'red'

  const failingCount = healthItems.filter(
    (h) => h.health_status === 'red',
  ).length

  const restoreConfidence = infraHealth?.restore_confidence ?? null
  const restoreValidated = restoreConfidence === 'verified'

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
          ? `${sources.length} sources registered, but ${failingCount} ha${failingCount === 1 ? 's' : 've'} a failed last backup`
          : `${sources.length} sources registered, schedules active`
        : 'Sources define what gets backed up: project code and databases, config, workspaces.',
      complete: hasSources && hasSchedules && failingCount === 0,
    },
    {
      id: 'infra',
      icon: <Server className="w-4 h-4" />,
      title: 'System backup',
      description: hasInfra
        ? infraHealthy
          ? 'PostgreSQL, Redis, Hatchet config, and secrets are backed up'
          : 'System backup source exists but last backup failed'
        : 'Backs up PostgreSQL, Redis, Hatchet config, and secrets for infrastructure recovery.',
      complete: infraHealthy,
    },
    {
      id: 'restore_validation',
      icon: <ShieldCheck className="w-4 h-4" />,
      title: 'Restore validation',
      description: restoreValidated
        ? 'Latest restore drill passed — recovery verified'
        : restoreConfidence === 'stale'
          ? 'Restore drill passed but is stale — re-run to verify current backup'
          : restoreConfidence === 'partial'
            ? 'Restore drill ran but some components failed'
            : 'Run a restore drill to verify backups can actually be restored.',
      complete: restoreValidated,
    },
  ]
}

// ─── Component ──────────────────────────────────────────────────

interface SetupChecklistProps {
  storageStatus: StorageStatus | undefined
  sources: BackupSource[]
  healthItems: BackupHealthItem[]
  isLoading: boolean
  onSourceChanged: () => void
  onBackupTriggered: () => void
}

export function SetupChecklist({
  storageStatus,
  sources,
  healthItems,
  isLoading,
  onSourceChanged,
  onBackupTriggered,
}: SetupChecklistProps) {
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  const steps = computeSteps(storageStatus, sources, healthItems)
  const doneCount = steps.filter((s) => s.complete).length
  const allDone = doneCount === steps.length
  const remainingCount = steps.length - doneCount
  const summary = allDone
    ? 'All protection steps are configured and restore validation is current.'
    : `${doneCount} of ${steps.length} complete. ${remainingCount} ${remainingCount === 1 ? 'step still needs attention.' : 'steps still need attention.'}`

  if (isLoading) return null

  const handleSetupInfra = async () => {
    setRunningAction('infra')
    setActionError(null)
    try {
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

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-900/30 overflow-hidden',
        allDone ? 'border-l-emerald-500' : 'border-l-phosphor-500',
      )}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="px-4 py-3 flex items-center justify-between w-full text-left cursor-pointer hover:bg-slate-800/30 transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3">
          <ShieldCheck
            className={clsx(
              'w-4 h-4',
              allDone ? 'text-emerald-400' : 'text-phosphor-400',
            )}
          />
          <div>
            <h2 className="text-sm font-medium text-slate-100">
              {allDone
                ? 'Backup protection fully configured'
                : doneCount === 0
                  ? 'Set up backup protection'
                  : `Backup setup — ${doneCount} of ${steps.length} complete`}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">{summary}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Progress dots */}
          <div className="flex items-center gap-1">
            {steps.map((step) => (
              <div
                key={step.id}
                className={clsx(
                  'w-2 h-2 rounded-full transition-colors',
                  step.complete ? 'bg-emerald-500' : 'bg-slate-600',
                )}
              />
            ))}
          </div>
          <span className="text-2xs text-slate-500">
            {expanded ? 'Hide' : 'Details'}
          </span>
        </div>
      </button>

      {/* Steps */}
      {expanded && (
        <div className="border-t border-slate-800/40">
          {steps.map((step) => (
            <div
              key={step.id}
              className={clsx(
                'px-4 py-3 flex items-start gap-3 border-b border-slate-800/30 last:border-b-0',
                step.complete && 'opacity-50',
              )}
            >
              <div className="mt-0.5 shrink-0">
                {step.complete ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
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
                      className="flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 transition-colors"
                    >
                      Configure
                      <ArrowRight className="w-3 h-3" />
                    </Link>
                  )}
                  {step.id === 'sources' && (
                    <span className="text-2xs text-slate-600 italic">
                      See below
                    </span>
                  )}
                  {step.id === 'infra' && (
                    <button
                      type="button"
                      onClick={handleSetupInfra}
                      disabled={runningAction === 'infra'}
                      className="flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors"
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
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Restore guidance — only when expanded */}
      {(!allDone || expanded) && (
        <div className="px-4 py-2.5 border-t border-slate-800/40 bg-slate-900/30">
          <p className="text-2xs text-slate-500 leading-relaxed">
            <span className="text-slate-400 font-medium">To restore:</span>{' '}
            expand any backup in the history below and click Restore.
          </p>
        </div>
      )}

      {/* Feedback */}
      {actionError && (
        <div className="px-4 py-2.5 border-t border-slate-800/40">
          <p className="text-xs text-rose-400">{actionError}</p>
        </div>
      )}
    </div>
  )
}
