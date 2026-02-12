'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  CheckCircle2,
  Clock,
  Layers,
  Loader2,
  XCircle,
  Zap,
  Filter,
  Cpu,
  GitMerge,
  RefreshCw,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  type AutonomousExecutionSettingsUpdate,
  getAutonomousSettings,
  updateAutonomousSettings,
} from '@/lib/api'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select'
import { Slider } from '../ui/slider'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Checkbox } from '../ui/checkbox'

interface AutonomousSettingsPanelProps {
  projectId: string
}

function formatHour(hour: number): string {
  if (hour === 0) return '12 AM'
  if (hour === 12) return '12 PM'
  if (hour === 24) return '12 AM'
  if (hour < 12) return `${hour} AM`
  return `${hour - 12} PM`
}

function isInTimeWindow(startHour: number, endHour: number): boolean {
  const now = new Date()
  const currentHour = now.getHours()

  // Handle 24/7 case
  if (startHour === 0 && endHour === 24) return true

  // Handle same-day window (e.g., 9am - 6pm)
  if (startHour < endHour) {
    return currentHour >= startHour && currentHour < endHour
  }

  // Handle overnight window (e.g., 10pm - 6am)
  return currentHour >= startHour || currentHour < endHour
}

const TASK_TYPES = [
  { value: 'refactor', label: 'Refactor' },
  { value: 'bug', label: 'Bug' },
  { value: 'feature', label: 'Feature' },
  { value: 'chore', label: 'Chore' },
  { value: 'docs', label: 'Docs' },
]

const MODEL_TIERS = [
  { value: 'standard', label: 'Standard', description: 'Balanced performance and cost' },
  { value: 'advanced', label: 'Advanced', description: 'Higher capability, higher cost' },
  { value: 'economy', label: 'Economy', description: 'Cost-optimized for simple tasks' },
]

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
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
        <h3 className="text-base font-medium text-slate-100">Execution Control</h3>

        {/* Time Range */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <Label className="text-slate-200 flex items-center gap-2">
              <Clock className="w-4 h-4 text-slate-400" />
              Execution Window
            </Label>
            {settings.enabled && (
              <span
                className={clsx(
                  'flex items-center gap-1 text-xs px-2 py-1 rounded-full',
                  currentInWindow
                    ? 'bg-phosphor-500/20 text-phosphor-400'
                    : 'bg-amber-500/20 text-amber-400',
                )}
              >
                {currentInWindow ? (
                  <>
                    <CheckCircle2 className="w-3 h-3" />
                    Active window
                  </>
                ) : (
                  <>
                    <XCircle className="w-3 h-3" />
                    Outside window
                  </>
                )}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mb-4">
            Set the daily time range when autonomous execution is allowed
          </p>

          <div className="space-y-4">
            <div className="flex items-center justify-between text-sm text-slate-300">
              <span>{formatHour(settings.start_hour)}</span>
              <span className="text-slate-500">to</span>
              <span>{formatHour(settings.end_hour)}</span>
            </div>

            <Slider
              value={[settings.start_hour, settings.end_hour]}
              min={0}
              max={24}
              step={1}
              onValueChange={handleTimeRangeChange}
              disabled={mutation.isPending}
              className="w-full"
            />

            <div className="flex justify-between text-xs text-slate-500">
              <span>12 AM</span>
              <span>6 AM</span>
              <span>12 PM</span>
              <span>6 PM</span>
              <span>12 AM</span>
            </div>
          </div>

          {settings.start_hour === 0 && settings.end_hour === 24 && (
            <p className="text-xs text-phosphor-400 mt-3">
              Execution allowed 24/7
            </p>
          )}
        </div>

        {/* Max Concurrent */}
        <div>
          <Label className="text-slate-200 mb-2 flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            Max Concurrent Tasks
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Maximum number of tasks to execute in parallel
          </p>

          <Select
            value={settings.max_concurrent.toString()}
            onValueChange={handleConcurrencyChange}
            disabled={mutation.isPending}
          >
            <SelectTrigger className="w-full max-w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">1 task (conservative)</SelectItem>
              <SelectItem value="2">2 tasks (balanced)</SelectItem>
              <SelectItem value="3">3 tasks (aggressive)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Max Tasks Per Day */}
        <div>
          <Label htmlFor="max-tasks-per-day" className="text-slate-200 mb-2 block">
            Max Tasks Per Day
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Maximum tasks to complete per day (leave empty for unlimited)
          </p>
          <Input
            id="max-tasks-per-day"
            type="number"
            min={1}
            placeholder="Unlimited"
            value={settings.max_tasks_per_day ?? ''}
            onChange={(e) => handleMaxTasksPerDayChange(e.target.value)}
            disabled={mutation.isPending}
            className="max-w-[200px]"
          />
        </div>

        {/* Cooldown */}
        <div>
          <Label htmlFor="cooldown" className="text-slate-200 mb-2 block">
            Cooldown Between Tasks (minutes)
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Minimum gap between task dispatches (0 = no cooldown)
          </p>
          <Input
            id="cooldown"
            type="number"
            min={0}
            value={settings.cooldown_minutes}
            onChange={(e) => handleCooldownChange(e.target.value)}
            disabled={mutation.isPending}
            className="max-w-[200px]"
          />
        </div>
      </div>

      {/* Task Filtering Section */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
        <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          Task Filtering
        </h3>

        {/* Allowed Task Types */}
        <div>
          <Label className="text-slate-200 mb-2 block">
            Allowed Task Types
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Select which task types can be executed autonomously
          </p>
          <div className="space-y-2">
            {TASK_TYPES.map((taskType) => (
              <div key={taskType.value} className="flex items-center gap-2">
                <Checkbox
                  checked={selectedTypes.includes(taskType.value)}
                  onCheckedChange={() => handleTaskTypeToggle(taskType.value)}
                  disabled={mutation.isPending}
                />
                <Label className="text-slate-300 text-sm cursor-pointer">
                  {taskType.label}
                </Label>
              </div>
            ))}
          </div>
          {selectedTypes.length === TASK_TYPES.length && (
            <p className="text-xs text-phosphor-400 mt-2">
              All task types allowed
            </p>
          )}
        </div>

        {/* Model Tier Preference */}
        <div>
          <Label className="text-slate-200 mb-2 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-slate-400" />
            Model Tier Preference
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Choose the AI model tier for autonomous execution
          </p>
          <Select
            value={settings.preferred_model_tier}
            onValueChange={handleModelTierChange}
            disabled={mutation.isPending}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODEL_TIERS.map((tier) => (
                <SelectItem key={tier.value} value={tier.value}>
                  <div>
                    <div className="font-medium">{tier.label}</div>
                    <div className="text-xs text-slate-400">{tier.description}</div>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Self-Healing Section */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
        <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-slate-400" />
          Self-Healing
        </h3>
        <p className="text-xs text-slate-400">
          Configure retry limits for automatic failure recovery
        </p>

        {/* Self-Fix Attempts */}
        <div>
          <Label htmlFor="self-fix-attempts" className="text-slate-200 mb-2 block">
            Max Self-Fix Attempts
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Maximum self-fix attempts before supervisor escalation (0-10)
          </p>
          <Input
            id="self-fix-attempts"
            type="number"
            min={0}
            max={10}
            value={settings.max_self_fix_attempts}
            onChange={(e) => handleSelfFixAttemptsChange(e.target.value)}
            disabled={mutation.isPending}
            className="max-w-[200px]"
          />
        </div>

        {/* Supervisor Attempts */}
        <div>
          <Label htmlFor="supervisor-attempts" className="text-slate-200 mb-2 block">
            Max Supervisor Attempts
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Maximum supervisor-guided attempts before blocking (0-10)
          </p>
          <Input
            id="supervisor-attempts"
            type="number"
            min={0}
            max={10}
            value={settings.max_supervisor_attempts}
            onChange={(e) => handleSupervisorAttemptsChange(e.target.value)}
            disabled={mutation.isPending}
            className="max-w-[200px]"
          />
        </div>

        {/* Extensions */}
        <div>
          <Label htmlFor="extensions" className="text-slate-200 mb-2 block">
            Max Extensions
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Maximum extension requests when retry budget exhausted (0-10)
          </p>
          <Input
            id="extensions"
            type="number"
            min={0}
            max={10}
            value={settings.max_extensions}
            onChange={(e) => handleExtensionsChange(e.target.value)}
            disabled={mutation.isPending}
            className="max-w-[200px]"
          />
        </div>
      </div>

      {/* Merge & Review Section */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
        <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
          <GitMerge className="w-4 h-4 text-slate-400" />
          Merge & Review
        </h3>

        {/* Auto-Merge Enabled */}
        <div>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-slate-200 block">
                Auto-Merge Enabled
              </Label>
              <p className="text-xs text-slate-400 mt-1">
                Enable automatic merging of completed tasks
              </p>
            </div>
            <button
              onClick={handleAutoMergeToggle}
              disabled={mutation.isPending}
              className={clsx(
                'relative w-12 h-6 rounded-full transition-colors',
                settings.auto_merge_enabled ? 'bg-phosphor-500' : 'bg-slate-600',
              )}
            >
              <span
                className={clsx(
                  'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                  settings.auto_merge_enabled ? 'translate-x-7' : 'translate-x-1',
                )}
              />
            </button>
          </div>
        </div>

        {/* Require Review */}
        <div>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-slate-200 block">
                Require AI Review
              </Label>
              <p className="text-xs text-slate-400 mt-1">
                Always run AI review before merge (even if auto-merge enabled)
              </p>
            </div>
            <button
              onClick={handleRequireReviewToggle}
              disabled={mutation.isPending}
              className={clsx(
                'relative w-12 h-6 rounded-full transition-colors',
                settings.require_review ? 'bg-phosphor-500' : 'bg-slate-600',
              )}
            >
              <span
                className={clsx(
                  'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                  settings.require_review ? 'translate-x-7' : 'translate-x-1',
                )}
              />
            </button>
          </div>
        </div>
      </div>

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
