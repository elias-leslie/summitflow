import { Filter } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Label } from '../ui/label'
import { Checkbox } from '../ui/checkbox'
import { TASK_TYPES } from './autonomous-utils'

interface TaskFilteringSectionProps {
  settings: AutonomousExecutionSettings
  selectedTypes: string[]
  isPending: boolean
  onTaskTypeToggle: (taskType: string) => void
}

export function TaskFilteringSection({
  selectedTypes,
  isPending,
  onTaskTypeToggle,
}: TaskFilteringSectionProps) {
  return (
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
                onCheckedChange={() => onTaskTypeToggle(taskType.value)}
                disabled={isPending}
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

    </div>
  )
}
