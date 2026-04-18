import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  type AutonomousExecutionSettings,
  type AutonomousExecutionSettingsUpdate,
  updateAutonomousSettings,
} from '@/lib/api'
import { TASK_TYPES } from './autonomous-utils'

// Creates a handler that parses a string to int and mutates if within [min, max]
function makeBoundedIntHandler(
  mutate: (u: AutonomousExecutionSettingsUpdate) => void,
  key: keyof AutonomousExecutionSettingsUpdate,
  min: number,
  max: number,
) {
  return (value: string) => {
    const n = parseInt(value, 10)
    if (!Number.isNaN(n) && n >= min && n <= max) {
      mutate({ [key]: n } as AutonomousExecutionSettingsUpdate)
    }
  }
}

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

  // --- Execution control ---
  const handleConcurrencyChange = (value: string) =>
    mutate({ max_concurrent: parseInt(value, 10) })

  const handleMaxTasksPerDayChange = (value: string) => {
    const n = value === '' ? null : parseInt(value, 10)
    if (n === null || (n >= 1 && !Number.isNaN(n))) {
      mutate({ max_tasks_per_day: n })
    }
  }

  const handleCooldownChange = makeBoundedIntHandler(
    mutate,
    'cooldown_minutes',
    0,
    Infinity,
  )
  const handleFrequencyChange = makeBoundedIntHandler(
    mutate,
    'frequency_minutes',
    5,
    1440,
  )
  const handleUpkeepFrequencyChange = makeBoundedIntHandler(
    mutate,
    'upkeep_frequency_minutes',
    15,
    1440,
  )
  const handleUpkeepBatchLimitChange = makeBoundedIntHandler(
    mutate,
    'upkeep_batch_limit',
    1,
    10,
  )
  const handleUpkeepEnabledToggle = () =>
    mutate({ upkeep_enabled: !settings.upkeep_enabled })

  // --- Task filtering ---
  const handleTaskTypeToggle = (taskType: string) => {
    const current = settings.allowed_types || TASK_TYPES.map((t) => t.value)
    const next = current.includes(taskType)
      ? current.filter((t) => t !== taskType)
      : [...current, taskType]
    mutate({ allowed_types: next.length === TASK_TYPES.length ? null : next })
  }
  // --- Self-healing ---
  const handleSelfFixAttemptsChange = makeBoundedIntHandler(
    mutate,
    'max_self_fix_attempts',
    0,
    10,
  )
  const handleSupervisorAttemptsChange = makeBoundedIntHandler(
    mutate,
    'max_supervisor_attempts',
    0,
    10,
  )
  const handleExtensionsChange = makeBoundedIntHandler(
    mutate,
    'max_extensions',
    0,
    10,
  )

  // --- Merge / review ---
  const handleAutoMergeToggle = () =>
    mutate({ auto_merge_enabled: !settings.auto_merge_enabled })
  const handleRequireReviewToggle = () =>
    mutate({ require_review: !settings.require_review })
  const handleAutoMergeTiersChange = (tiers: number[]) =>
    mutate({ auto_merge_tiers: tiers })

  // --- Quality gate ---
  const handleQualityToolsChange = (tools: string[]) =>
    mutate({ quality_gate_tools: tools })
  const handleQualityModeChange = (mode: string) =>
    mutate({ quality_gate_mode: mode })
  const handleQualityFixToggle = () =>
    mutate({ quality_gate_fix_enabled: !settings.quality_gate_fix_enabled })

  return {
    isPending: mutation.isPending,
    handleConcurrencyChange,
    handleMaxTasksPerDayChange,
    handleCooldownChange,
    handleUpkeepEnabledToggle,
    handleUpkeepFrequencyChange,
    handleUpkeepBatchLimitChange,
    handleTaskTypeToggle,
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
