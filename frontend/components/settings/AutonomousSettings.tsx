'use client'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getAutonomousSettings } from '@/lib/api'
import { ExecutionControlSection } from './ExecutionControlSection'
import { TaskFilteringSection } from './TaskFilteringSection'
import { SelfHealingSection } from './SelfHealingSection'
import { QualityGateSection } from './QualityGateSection'
import { MergeReviewSection } from './MergeReviewSection'
import { MasterToggle } from './MasterToggle'
import { isInTimeWindow, TASK_TYPES } from './autonomous-utils'
import { useAutonomousSettingsHandlers } from './useAutonomousSettingsHandlers'

interface AutonomousSettingsPanelProps {
  projectId: string
}

export function AutonomousSettingsPanel({
  projectId,
}: AutonomousSettingsPanelProps) {
  const [currentInWindow, setCurrentInWindow] = useState(false)

  const { data: settings, isLoading } = useQuery({
    queryKey: ['autonomous-settings', projectId],
    queryFn: () => getAutonomousSettings(projectId),
  })

  useEffect(() => {
    if (!settings) return
    const updateStatus = () => {
      setCurrentInWindow(isInTimeWindow(settings.start_hour, settings.end_hour))
    }
    updateStatus()
    const interval = setInterval(updateStatus, 60000)
    return () => clearInterval(interval)
  }, [settings])

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
      <MasterToggle
        enabled={settings.enabled}
        isPending={handlers.isPending}
        onToggle={handlers.handleEnabledToggle}
      />

      <ExecutionControlSection
        settings={settings}
        currentInWindow={currentInWindow}
        isPending={handlers.isPending}
        onTimeRangeChange={handlers.handleTimeRangeChange}
        onConcurrencyChange={handlers.handleConcurrencyChange}
        onMaxTasksPerDayChange={handlers.handleMaxTasksPerDayChange}
        onCooldownChange={handlers.handleCooldownChange}
        onFrequencyChange={handlers.handleFrequencyChange}
      />

      <TaskFilteringSection
        settings={settings}
        selectedTypes={selectedTypes}
        isPending={handlers.isPending}
        onTaskTypeToggle={handlers.handleTaskTypeToggle}
        onModelTierChange={handlers.handleModelTierChange}
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
