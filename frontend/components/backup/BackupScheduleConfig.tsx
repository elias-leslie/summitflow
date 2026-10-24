'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Clock,
  Loader2,
  Power,
  PowerOff,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchBackupSource, updateBackupSource } from '@/lib/api/backups'
import { formatDate } from '@/lib/format'
import { FEEDBACK_TIMEOUT } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'
import {
  FREQUENCY_OPTIONS,
  retentionChoices,
  retentionLabel,
} from './schedule-options'

interface BackupScheduleConfigProps {
  sourceId: string
}

export function BackupScheduleConfig({ sourceId }: BackupScheduleConfigProps) {
  const queryClient = useQueryClient()

  const [enabled, setEnabled] = useState(false)
  const [frequency, setFrequency] = useState('daily')
  const [retentionDays, setRetentionDays] = useState(14)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data: source, isLoading } = useQuery({
    queryKey: ['backup-source', sourceId],
    queryFn: () => fetchBackupSource(sourceId),
  })

  useEffect(() => {
    if (source) {
      setEnabled(source.enabled)
      setFrequency(source.frequency)
      setRetentionDays(source.retention_days)
    }
  }, [source])

  const handleSave = async () => {
    setSaving(true)
    setSaveSuccess(false)
    setSaveError(null)

    try {
      await updateBackupSource(sourceId, {
        enabled,
        frequency,
        retention_days: retentionDays,
      })
      queryClient.invalidateQueries({
        queryKey: ['backup-source', sourceId],
      })
      queryClient.invalidateQueries({
        queryKey: ['backup-sources'],
      })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), FEEDBACK_TIMEOUT)
    } catch (err) {
      setSaveError(getErrorMessage(err, 'Failed to save schedule'))
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = source
    ? enabled !== source.enabled ||
      frequency !== source.frequency ||
      retentionDays !== source.retention_days
    : enabled

  if (isLoading) {
    return (
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
      <h3 className="text-lg font-medium text-slate-100 mb-1 flex items-center gap-2">
        <Calendar className="w-5 h-5 text-phosphor-400" />
        Schedule and retention
      </h3>
      <p className="text-sm text-slate-400 mb-6">
        The only place this source's schedule is set. You can still back it up
        by hand at any time.
      </p>

      <div className="space-y-6">
        <div className="flex items-center justify-between p-4 bg-slate-700/30 rounded-lg">
          <div className="flex items-center gap-3">
            {enabled ? (
              <Power className="w-5 h-5 text-green-400" />
            ) : (
              <PowerOff className="w-5 h-5 text-slate-500" />
            )}
            <div>
              <p className="text-sm font-medium text-slate-200">
                Scheduled backups
              </p>
              <p className="text-xs text-slate-400">
                {enabled
                  ? 'Runs on the schedule below'
                  : 'Off: only manual backups run'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setEnabled(!enabled)}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
              enabled ? 'bg-green-500' : 'bg-slate-600',
            )}
            aria-pressed={enabled}
            aria-label="Toggle scheduled backups"
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-slate-100 rounded-full transition-transform shadow-sm',
                enabled ? 'left-7' : 'left-1',
              )}
            />
          </button>
        </div>

        <div className={clsx(!enabled && 'opacity-50 pointer-events-none')}>
          <label className="block text-sm font-medium text-slate-300 mb-3">
            How often
          </label>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {FREQUENCY_OPTIONS.map((option) => (
              <button
                type="button"
                key={option.value}
                onClick={() => setFrequency(option.value)}
                disabled={!enabled}
                className={clsx(
                  'p-3 rounded-lg border text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
                  frequency === option.value
                    ? 'border-phosphor-500 bg-phosphor-500/10 shadow-[0_0_12px_rgba(0,245,255,0.08)]'
                    : 'border-slate-600 bg-slate-700/30 hover:border-slate-500 hover:bg-slate-700/50',
                )}
              >
                <p className="text-sm font-medium text-slate-200">
                  {option.label}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className={clsx(!enabled && 'opacity-50 pointer-events-none')}>
          <label
            htmlFor="retention-days"
            className="block text-sm font-medium text-slate-300 mb-2"
          >
            Keep backups for
          </label>
          <select
            id="retention-days"
            value={retentionDays}
            onChange={(e) => setRetentionDays(Number(e.target.value))}
            disabled={!enabled}
            className="w-full px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-md
                       text-slate-200 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-all"
          >
            {retentionChoices(source?.retention_days ?? retentionDays).map(
              (days) => (
                <option key={days} value={days}>
                  {retentionLabel(days)}
                </option>
              ),
            )}
          </select>
          <p className="text-xs text-slate-400 mt-1">
            Older backup points are expired automatically.
          </p>
        </div>

        {source && (
          <div className="p-4 bg-slate-700/30 rounded-lg space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400 flex items-center gap-2">
                <Clock className="w-4 h-4" />
                Last backup
              </span>
              <span className="text-slate-200">
                {source.last_run_at ? formatDate(source.last_run_at) : 'Never'}
              </span>
            </div>
            {enabled && source.next_run_at && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400 flex items-center gap-2">
                  <Calendar className="w-4 h-4" />
                  Next backup
                </span>
                <span className="text-phosphor-400">
                  {formatDate(source.next_run_at)}
                </span>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          {saveSuccess && (
            <span className="text-sm text-green-400 flex items-center gap-1">
              <CheckCircle2 className="w-4 h-4" />
              Saved
            </span>
          )}
          {saveError && (
            <span className="text-sm text-red-400 flex items-center gap-1">
              <AlertCircle className="w-4 h-4" />
              {saveError}
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
              hasChanges
                ? 'bg-phosphor-600 text-slate-50 hover:bg-phosphor-500'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving...
              </>
            ) : (
              'Save'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
