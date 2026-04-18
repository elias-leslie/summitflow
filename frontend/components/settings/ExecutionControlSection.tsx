import { Layers, Timer } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select'

interface ExecutionControlSectionProps {
  settings: AutonomousExecutionSettings
  isPending: boolean
  onConcurrencyChange: (value: string) => void
  onMaxTasksPerDayChange: (value: string) => void
  onCooldownChange: (value: string) => void
  onFrequencyChange: (value: string) => void
}

export function ExecutionControlSection({
  settings,
  isPending,
  onConcurrencyChange,
  onMaxTasksPerDayChange,
  onCooldownChange,
  onFrequencyChange,
}: ExecutionControlSectionProps) {
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <h3 className="text-base font-medium text-slate-100">
        Execution Control
      </h3>

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
          onValueChange={onConcurrencyChange}
          disabled={isPending}
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
        <Label
          htmlFor="max-tasks-per-day"
          className="text-slate-200 mb-2 block"
        >
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
          onChange={(e) => onMaxTasksPerDayChange(e.target.value)}
          disabled={isPending}
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
          onChange={(e) => onCooldownChange(e.target.value)}
          disabled={isPending}
          className="max-w-[200px]"
        />
      </div>

      {/* Check Frequency */}
      <div>
        <Label
          htmlFor="frequency"
          className="text-slate-200 mb-2 flex items-center gap-2"
        >
          <Timer className="w-4 h-4 text-slate-400" />
          Check Frequency (minutes)
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          How often to check for new work to execute (5–1440 min)
        </p>
        <Input
          id="frequency"
          type="number"
          min={5}
          max={1440}
          value={settings.frequency_minutes}
          onChange={(e) => onFrequencyChange(e.target.value)}
          disabled={isPending}
          className="max-w-[200px]"
        />
      </div>
    </div>
  )
}
