'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import {
  getAutonomousSchedules,
  getAutonomousSettings,
  getRoutineUpkeepStatus,
  runRoutineUpkeep,
  updateAutonomousSchedule,
  updateAutonomousSettings,
} from '@/lib/api'
import {
  type AutomationMode,
  AutomationModeSection,
} from './AutomationModeSection'
import { AutomationSchedulesSection } from './AutomationSchedulesSection'
import { TASK_TYPES } from './autonomous-utils'
import { ExecutionControlSection } from './ExecutionControlSection'
import { MergeReviewSection } from './MergeReviewSection'
import { QualityGateSection } from './QualityGateSection'
import { RoutineUpkeepSection } from './RoutineUpkeepSection'
import { SelfHealingSection } from './SelfHealingSection'
import { TaskFilteringSection } from './TaskFilteringSection'
import { useAutonomousSettingsHandlers } from './useAutonomousSettingsHandlers'

interface AutonomousSettingsPanelProps {
  projectId: string
}

export function AutonomousSettingsPanel({
  projectId,
}: AutonomousSettingsPanelProps) {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery({
    queryKey: ['autonomous-settings', projectId],
    queryFn: () => getAutonomousSettings(projectId),
  })
  const { data: upkeepStatus } = useQuery({
    queryKey: ['routine-upkeep-status', projectId],
    queryFn: () => getRoutineUpkeepStatus(projectId),
  })
  const { data: schedules = [] } = useQuery({
    queryKey: ['autonomous-schedules', projectId],
    queryFn: () => getAutonomousSchedules(projectId),
  })
  const upkeepRun = useMutation({
    mutationFn: () => runRoutineUpkeep(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['routine-upkeep-status', projectId],
      })
    },
  })
  const scheduleMutation = useMutation({
    mutationFn: ({
      scheduleId,
      enabled,
    }: {
      scheduleId: string
      enabled: boolean
    }) => updateAutonomousSchedule(projectId, scheduleId, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['autonomous-schedules', projectId],
      })
    },
  })
  const modeMutation = useMutation({
    mutationFn: async (mode: AutomationMode) => {
      const enableQueue = mode !== 'off'
      const enableUpkeep = mode === 'upkeep'
      await updateAutonomousSettings(projectId, {
        enabled: enableQueue,
        upkeep_enabled: enableUpkeep,
      })
      await Promise.all([
        updateAutonomousSchedule(projectId, 'work_pickup', {
          enabled: enableQueue,
        }),
        updateAutonomousSchedule(projectId, 'task_generation', {
          enabled: enableUpkeep,
        }),
      ])
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['autonomous-settings', projectId],
      })
      queryClient.invalidateQueries({
        queryKey: ['autonomous-schedules', projectId],
      })
      queryClient.invalidateQueries({
        queryKey: ['routine-upkeep-status', projectId],
      })
    },
  })

  const handlers = useAutonomousSettingsHandlers(projectId, settings!)

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

  const selectedTypes = settings.allowed_types || TASK_TYPES.map((t) => t.value)
  const workPickupEnabled = schedules.some(
    (schedule) => schedule.schedule_id === 'work_pickup' && schedule.enabled,
  )
  const taskGenerationEnabled = schedules.some(
    (schedule) =>
      schedule.schedule_id === 'task_generation' && schedule.enabled,
  )
  const automationMode: AutomationMode =
    settings.enabled && workPickupEnabled
      ? taskGenerationEnabled && settings.upkeep_enabled
        ? 'upkeep'
        : 'queue'
      : 'off'
  const isSaving = handlers.isPending || modeMutation.isPending

  return (
    <div className="space-y-6">
      <AutomationModeSection
        mode={automationMode}
        settings={settings}
        isPending={isSaving}
        onModeChange={(mode) => modeMutation.mutate(mode)}
      />

      <ExecutionControlSection
        settings={settings}
        isPending={isSaving}
        onConcurrencyChange={handlers.handleConcurrencyChange}
        onMaxTasksPerDayChange={handlers.handleMaxTasksPerDayChange}
        onCooldownChange={handlers.handleCooldownChange}
        onFrequencyChange={handlers.handleFrequencyChange}
      />

      <AutomationSchedulesSection
        projectId={projectId}
        schedules={schedules}
        updatingScheduleId={
          scheduleMutation.isPending
            ? (scheduleMutation.variables?.scheduleId ?? null)
            : null
        }
        onToggle={(schedule) =>
          scheduleMutation.mutate({
            scheduleId: schedule.schedule_id,
            enabled: !schedule.enabled,
          })
        }
      />

      <RoutineUpkeepSection
        settings={settings}
        status={upkeepStatus}
        isPending={isSaving}
        isRunning={upkeepRun.isPending}
        onEnabledToggle={handlers.handleUpkeepEnabledToggle}
        onFrequencyChange={handlers.handleUpkeepFrequencyChange}
        onBatchLimitChange={handlers.handleUpkeepBatchLimitChange}
        onRunNow={() => upkeepRun.mutate()}
      />

      <TaskFilteringSection
        selectedTypes={selectedTypes}
        isPending={isSaving}
        onTaskTypeToggle={handlers.handleTaskTypeToggle}
      />

      <QualityGateSection
        settings={settings}
        isPending={isSaving}
        onToolsChange={handlers.handleQualityToolsChange}
        onModeChange={handlers.handleQualityModeChange}
        onFixEnabledToggle={handlers.handleQualityFixToggle}
      />

      <SelfHealingSection
        settings={settings}
        isPending={isSaving}
        onSelfFixAttemptsChange={handlers.handleSelfFixAttemptsChange}
        onSupervisorAttemptsChange={handlers.handleSupervisorAttemptsChange}
        onExtensionsChange={handlers.handleExtensionsChange}
      />

      <MergeReviewSection
        settings={settings}
        isPending={isSaving}
        onAutoMergeToggle={handlers.handleAutoMergeToggle}
        onRequireReviewToggle={handlers.handleRequireReviewToggle}
        onAutoMergeTiersChange={handlers.handleAutoMergeTiersChange}
      />

      {isSaving && (
        <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Saving...
        </div>
      )}
    </div>
  )
}
