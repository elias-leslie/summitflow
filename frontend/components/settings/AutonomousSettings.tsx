'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Loader2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  type AutonomousExecutionSettingsUpdate,
  getAutonomousSettings,
  updateAutonomousSettings,
} from '@/lib/api'
import { ExecutionControlSection } from './ExecutionControlSection'
import { TaskFilteringSection } from './TaskFilteringSection'
import { SelfHealingSection } from './SelfHealingSection'
import { MergeReviewSection } from './MergeReviewSection'
import { isInTimeWindow, TASK_TYPES } from './autonomous-utils'

interface AutonomousSettingsPanelProps {
  projectId: string
}

export function AutonomousSettingsPanel({
  projectId,
}: AutonomousSettingsPanelProps) {
  const queryClient = useQueryClient()
  const [currentInWindow, setCurrentInWindow] = useState(false)

  const { data: settings, isLoading } = useQuery({
    queryKey: ['autonomous-settings', projectId],
    queryFn: () => getAutonomousSettings(projectId),
  })

  // Update time window status every minute
  useEffect(() => {
    if (!settings) return

    const updateStatus = () => {
      setCurrentInWindow(isInTimeWindow(settings.start_hour, settings.end_hour))
    }

    updateStatus()
    const interval = setInterval(updateStatus, 60000) // Check every minute

    return () => clearInterval(interval)
  }, [settings])

  const mutation = useMutation({
    mutationFn: (update: AutonomousExecutionSettingsUpdate) =>
      updateAutonomousSettings(projectId, update),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['autonomous-settings', projectId],
      })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!settings) {
    return (
      <div className="text-sm text-slate-400 py-4">
        Failed to load autonomous settings
      </div>
    )
  }

  const handleTimeRangeChange = (values: number[]) => {
    const [start, end] = values
    mutation.mutate({ start_hour: start, end_hour: end })
  }

  const handleConcurrencyChange = (value: string) => {
    mutation.mutate({ max_concurrent: parseInt(value, 10) })
  }

  const handleEnabledToggle = () => {
    mutation.mutate({ enabled: !settings.enabled })
  }

  const handleMaxTasksPerDayChange = (value: string) => {
    const numValue = value === '' ? null : parseInt(value, 10)
    if (numValue === null || (numValue >= 1 && !Number.isNaN(numValue))) {
      mutation.mutate({ max_tasks_per_day: numValue })
    }
  }

  const handleCooldownChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0) {
      mutation.mutate({ cooldown_minutes: numValue })
    }
  }

  const handleTaskTypeToggle = (taskType: string) => {
    const currentTypes = settings.allowed_types || TASK_TYPES.map(t => t.value)
    const newTypes = currentTypes.includes(taskType)
      ? currentTypes.filter(t => t !== taskType)
      : [...currentTypes, taskType]

    // If all types are selected, send null (allow all)
    const allSelected = newTypes.length === TASK_TYPES.length
    mutation.mutate({ allowed_types: allSelected ? null : newTypes })
  }

  const handleModelTierChange = (value: string) => {
    mutation.mutate({ preferred_model_tier: value })
  }

  const handleSelfFixAttemptsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutation.mutate({ max_self_fix_attempts: numValue })
    }
  }

  const handleSupervisorAttemptsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutation.mutate({ max_supervisor_attempts: numValue })
    }
  }

  const handleExtensionsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutation.mutate({ max_extensions: numValue })
    }
  }

  const handleAutoMergeToggle = () => {
    mutation.mutate({ auto_merge_enabled: !settings.auto_merge_enabled })
  }

  const handleRequireReviewToggle = () => {
    mutation.mutate({ require_review: !settings.require_review })
  }

  const handleFrequencyChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 5 && numValue <= 1440) {
      mutation.mutate({ frequency_minutes: numValue })
    }
  }

  const handleAutoMergeTiersChange = (tiers: number[]) => {
    mutation.mutate({ auto_merge_tiers: tiers })
  }

  const selectedTypes = settings.allowed_types || TASK_TYPES.map(t => t.value)

  return (
    <div className="space-y-6">
      {/* Master Toggle */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-400" />
              Autonomous Execution
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Enable AI agents to automatically execute refactor, debt, and
              regression tasks
            </p>
          </div>
          <button
            onClick={handleEnabledToggle}
            disabled={mutation.isPending}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors',
              settings.enabled ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                settings.enabled ? 'translate-x-7' : 'translate-x-1',
              )}
            />
          </button>
        </div>
      </div>

      {/* Execution Control Section */}
      <ExecutionControlSection
        settings={settings}
        currentInWindow={currentInWindow}
        isPending={mutation.isPending}
        onTimeRangeChange={handleTimeRangeChange}
        onConcurrencyChange={handleConcurrencyChange}
        onMaxTasksPerDayChange={handleMaxTasksPerDayChange}
        onCooldownChange={handleCooldownChange}
        onFrequencyChange={handleFrequencyChange}
      />

      {/* Task Filtering Section */}
      <TaskFilteringSection
        settings={settings}
        selectedTypes={selectedTypes}
        isPending={mutation.isPending}
        onTaskTypeToggle={handleTaskTypeToggle}
        onModelTierChange={handleModelTierChange}
      />

      {/* Self-Healing Section */}
      <SelfHealingSection
        settings={settings}
        isPending={mutation.isPending}
        onSelfFixAttemptsChange={handleSelfFixAttemptsChange}
        onSupervisorAttemptsChange={handleSupervisorAttemptsChange}
        onExtensionsChange={handleExtensionsChange}
      />

      {/* Merge & Review Section */}
      <MergeReviewSection
        settings={settings}
        isPending={mutation.isPending}
        onAutoMergeToggle={handleAutoMergeToggle}
        onRequireReviewToggle={handleRequireReviewToggle}
        onAutoMergeTiersChange={handleAutoMergeTiersChange}
      />

      {/* Save indicator */}
      {mutation.isPending && (
        <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Saving...
        </div>
      )}
    </div>
  )
}
