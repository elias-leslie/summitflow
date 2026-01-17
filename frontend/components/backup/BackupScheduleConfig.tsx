'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Calendar,
  CheckCircle2,
  Clock,
  Loader2,
  Power,
  PowerOff,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchBackupSchedule, updateBackupSchedule } from '@/lib/api/backups'

interface BackupScheduleConfigProps {
  projectId: string
}

const FREQUENCY_OPTIONS = [
  { value: 'daily', label: 'Daily', description: 'Backup every day' },
  { value: 'weekly', label: 'Weekly', description: 'Backup once a week' },
  { value: 'monthly', label: 'Monthly', description: 'Backup once a month' },
]

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function BackupScheduleConfig({ projectId }: BackupScheduleConfigProps) {
  const queryClient = useQueryClient()

  const [enabled, setEnabled] = useState(false)
  const [frequency, setFrequency] = useState('daily')
  const [retentionCount, setRetentionCount] = useState(5)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const { data: schedule, isLoading } = useQuery({
    queryKey: ['backup-schedule', projectId],
    queryFn: () => fetchBackupSchedule(projectId),
  })

  // Sync form state when data loads
  useEffect(() => {
    if (schedule) {
      setEnabled(schedule.enabled)
      setFrequency(schedule.frequency)
      setRetentionCount(schedule.retention_count)
    }
  }, [schedule])

  const handleSave = async () => {
    setSaving(true)
    setSaveSuccess(false)

    try {
      await updateBackupSchedule(projectId, {
        enabled,
        frequency,
        retention_count: retentionCount,
      })
      queryClient.invalidateQueries({
        queryKey: ['backup-schedule', projectId],
      })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err) {
      console.error('Failed to save schedule:', err)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges =
    schedule &&
    (enabled !== schedule.enabled ||
      frequency !== schedule.frequency ||
      retentionCount !== schedule.retention_count)

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
        Backup Schedule
      </h3>
      <p className="text-sm text-slate-400 mb-6">
        Configure automatic backups for this project.
      </p>

      <div className="space-y-6">
        {/* Enable/Disable Toggle */}
        <div className="flex items-center justify-between p-4 bg-slate-700/30 rounded-lg">
          <div className="flex items-center gap-3">
            {enabled ? (
              <Power className="w-5 h-5 text-green-400" />
            ) : (
              <PowerOff className="w-5 h-5 text-slate-500" />
            )}
            <div>
              <p className="text-sm font-medium text-slate-200">
                Scheduled Backups
              </p>
              <p className="text-xs text-slate-400">
                {enabled
                  ? 'Backups will run automatically'
                  : 'Automatic backups are disabled'}
              </p>
            </div>
          </div>
          <button
            onClick={() => setEnabled(!enabled)}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors',
              enabled ? 'bg-green-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                enabled ? 'left-7' : 'left-1',
              )}
            />
          </button>
        </div>

        {/* Frequency Selector */}
        <div className={clsx(!enabled && 'opacity-50 pointer-events-none')}>
          <label className="block text-sm font-medium text-slate-300 mb-3">
            Backup Frequency
          </label>
          <div className="grid grid-cols-3 gap-3">
            {FREQUENCY_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => setFrequency(option.value)}
                disabled={!enabled}
                className={clsx(
                  'p-3 rounded-lg border text-left transition-colors',
                  frequency === option.value
                    ? 'border-phosphor-500 bg-phosphor-500/10'
                    : 'border-slate-600 bg-slate-700/30 hover:border-slate-500',
                )}
              >
                <p className="text-sm font-medium text-slate-200">
                  {option.label}
                </p>
                <p className="text-xs text-slate-400 mt-0.5">
                  {option.description}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Retention Count */}
        <div className={clsx(!enabled && 'opacity-50 pointer-events-none')}>
          <label
            htmlFor="retention-count"
            className="block text-sm font-medium text-slate-300 mb-2"
          >
            Backups to Keep
          </label>
          <select
            id="retention-count"
            value={retentionCount}
            onChange={(e) => setRetentionCount(Number(e.target.value))}
            disabled={!enabled}
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md
                       text-slate-200 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
          >
            {[3, 5, 7, 10, 14, 30].map((num) => (
              <option key={num} value={num}>
                {num} backups
              </option>
            ))}
          </select>
          <p className="text-xs text-slate-400 mt-1">
            Older backups will be automatically deleted.
          </p>
        </div>

        {/* Schedule Info */}
        {schedule && (
          <div className="p-4 bg-slate-700/30 rounded-lg space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400 flex items-center gap-2">
                <Clock className="w-4 h-4" />
                Last Backup
              </span>
              <span className="text-slate-200">
                {formatDate(schedule.last_run_at)}
              </span>
            </div>
            {enabled && schedule.next_run_at && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400 flex items-center gap-2">
                  <Calendar className="w-4 h-4" />
                  Next Backup
                </span>
                <span className="text-phosphor-400">
                  {formatDate(schedule.next_run_at)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Save Button */}
        <div className="flex items-center justify-end gap-3 pt-2">
          {saveSuccess && (
            <span className="text-sm text-green-400 flex items-center gap-1">
              <CheckCircle2 className="w-4 h-4" />
              Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
              hasChanges
                ? 'bg-phosphor-600 text-white hover:bg-phosphor-500'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving...
              </>
            ) : (
              'Save Changes'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
