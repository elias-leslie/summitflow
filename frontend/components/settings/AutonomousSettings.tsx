'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, Shield } from 'lucide-react'
import {
  getAutonomousSchedules,
  getAutonomousSettings,
  getRoutineUpkeepStatus,
  runRoutineUpkeep,
  updateAutonomousSchedule,
} from '@/lib/api'
import { AutomationSchedulesSection } from './AutomationSchedulesSection'
import { ExecutionControlSection } from './ExecutionControlSection'
import { RoutineUpkeepSection } from './RoutineUpkeepSection'
import { TaskFilteringSection } from './TaskFilteringSection'
import { SelfHealingSection } from './SelfHealingSection'
import { QualityGateSection } from './QualityGateSection'
import { MergeReviewSection } from './MergeReviewSection'
import { TASK_TYPES } from './autonomous-utils'
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

  const selectedTypes = settings.allowed_types || TASK_TYPES.map(t => t.value)

  return (
    <div className="space-y-6">
      {/* Access control banner — points to Agent Hub */}
      <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700 flex items-start gap-3">
        <Shield className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium text-slate-200">
            Access control managed by Agent Hub
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Enable/disable autonomous execution, permission tiers, and execution
            time windows are now configured in Agent Hub&apos;s Access Control.
          </p>
          <a
            href="/api/agent-hub/projects/permissions"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 mt-2 transition-colors"
          >
            <ExternalLink className="w-3 h-3" />
            Open Agent Hub Permissions
          </a>
        </div>
      </div>

      <ExecutionControlSection
        settings={settings}
        isPending={handlers.isPending}
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
            ? scheduleMutation.variables?.scheduleId ?? null
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
        isPending={handlers.isPending}
        isRunning={upkeepRun.isPending}
        onEnabledToggle={handlers.handleUpkeepEnabledToggle}
        onFrequencyChange={handlers.handleUpkeepFrequencyChange}
        onBatchLimitChange={handlers.handleUpkeepBatchLimitChange}
        onRunNow={() => upkeepRun.mutate()}
      />

      <TaskFilteringSection
        selectedTypes={selectedTypes}
        isPending={handlers.isPending}
        onTaskTypeToggle={handlers.handleTaskTypeToggle}
      />

      <QualityGateSection
        settings={settings}
        isPending={handlers.isPending}
        onToolsChange={handlers.handleQualityToolsChange}
        onModeChange={handlers.handleQualityModeChange}
        onFixEnabledToggle={handlers.handleQualityFixToggle}
      />

      <SelfHealingSection
        settings={settings}
        isPending={handlers.isPending}
        onSelfFixAttemptsChange={handlers.handleSelfFixAttemptsChange}
        onSupervisorAttemptsChange={handlers.handleSupervisorAttemptsChange}
        onExtensionsChange={handlers.handleExtensionsChange}
      />

      <MergeReviewSection
        settings={settings}
        isPending={handlers.isPending}
        onAutoMergeToggle={handlers.handleAutoMergeToggle}
        onRequireReviewToggle={handlers.handleRequireReviewToggle}
        onAutoMergeTiersChange={handlers.handleAutoMergeTiersChange}
      />

      {handlers.isPending && (
        <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Saving...
        </div>
      )}
    </div>
  )
}
