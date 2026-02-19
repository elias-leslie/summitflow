import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  type AutonomousExecutionSettings,
  type AutonomousExecutionSettingsUpdate,
  updateAutonomousSettings,
} from '@/lib/api'
import { TASK_TYPES } from './autonomous-utils'

export function useAutonomousSettingsHandlers(
  projectId: string,
  settings: AutonomousExecutionSettings,
) {
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (update: AutonomousExecutionSettingsUpdate) =>
      updateAutonomousSettings(projectId, update),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['autonomous-settings', projectId],
      })
    },
  })

  const mutate = (update: AutonomousExecutionSettingsUpdate) =>
    mutation.mutate(update)

  const handleTimeRangeChange = (values: number[]) => {
    const [start, end] = values
    mutate({ start_hour: start, end_hour: end })
  }

  const handleConcurrencyChange = (value: string) => {
    mutate({ max_concurrent: parseInt(value, 10) })
  }

  const handleEnabledToggle = () => {
    mutate({ enabled: !settings.enabled })
  }

  const handleMaxTasksPerDayChange = (value: string) => {
    const numValue = value === '' ? null : parseInt(value, 10)
    if (numValue === null || (numValue >= 1 && !Number.isNaN(numValue))) {
      mutate({ max_tasks_per_day: numValue })
    }
  }

  const handleCooldownChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0) {
      mutate({ cooldown_minutes: numValue })
    }
  }

  const handleTaskTypeToggle = (taskType: string) => {
    const currentTypes = settings.allowed_types || TASK_TYPES.map(t => t.value)
    const newTypes = currentTypes.includes(taskType)
      ? currentTypes.filter(t => t !== taskType)
      : [...currentTypes, taskType]
    const allSelected = newTypes.length === TASK_TYPES.length
    mutate({ allowed_types: allSelected ? null : newTypes })
  }

  const handleModelTierChange = (value: string) => {
    mutate({ preferred_model_tier: value })
  }

  const handleSelfFixAttemptsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutate({ max_self_fix_attempts: numValue })
    }
  }

  const handleSupervisorAttemptsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutate({ max_supervisor_attempts: numValue })
    }
  }

  const handleExtensionsChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 0 && numValue <= 10) {
      mutate({ max_extensions: numValue })
    }
  }

  const handleAutoMergeToggle = () => {
    mutate({ auto_merge_enabled: !settings.auto_merge_enabled })
  }

  const handleRequireReviewToggle = () => {
    mutate({ require_review: !settings.require_review })
  }

  const handleFrequencyChange = (value: string) => {
    const numValue = parseInt(value, 10)
    if (!Number.isNaN(numValue) && numValue >= 5 && numValue <= 1440) {
      mutate({ frequency_minutes: numValue })
    }
  }

  const handleAutoMergeTiersChange = (tiers: number[]) => {
    mutate({ auto_merge_tiers: tiers })
  }

  const handleQualityToolsChange = (tools: string[]) => {
    mutate({ quality_gate_tools: tools })
  }

  const handleQualityModeChange = (mode: string) => {
    mutate({ quality_gate_mode: mode })
  }

  const handleQualityFixToggle = () => {
    mutate({ quality_gate_fix_enabled: !settings.quality_gate_fix_enabled })
  }

  return {
    isPending: mutation.isPending,
    handleTimeRangeChange,
    handleConcurrencyChange,
    handleEnabledToggle,
    handleMaxTasksPerDayChange,
    handleCooldownChange,
    handleTaskTypeToggle,
    handleModelTierChange,
    handleSelfFixAttemptsChange,
    handleSupervisorAttemptsChange,
    handleExtensionsChange,
    handleAutoMergeToggle,
    handleRequireReviewToggle,
    handleFrequencyChange,
    handleAutoMergeTiersChange,
    handleQualityToolsChange,
    handleQualityModeChange,
    handleQualityFixToggle,
  }
}
