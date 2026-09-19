import { Filter } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Checkbox } from '../ui/checkbox'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { TASK_TYPES } from './autonomous-utils'

interface TaskFilteringSectionProps {
  selectedTypes: string[]
  isPending: boolean
  onTaskTypeToggle: (taskType: string) => void
  externalOrigins: string[] | null
  onExternalOriginsChange: (value: string) => void
}

export function TaskFilteringSection({
  selectedTypes,
  isPending,
  onTaskTypeToggle,
  externalOrigins,
  onExternalOriginsChange,
}: TaskFilteringSectionProps) {
  const [draftOrigins, setDraftOrigins] = useState(
    externalOrigins?.join(', ') ?? '',
  )
  useEffect(() => {
    setDraftOrigins(externalOrigins?.join(', ') ?? '')
  }, [externalOrigins])
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
        <Filter className="w-4 h-4 text-slate-400" />
        Task Filtering
      </h3>

      {/* Allowed Task Types */}
      <div>
        <Label className="text-slate-200 mb-2 block">Allowed Task Types</Label>
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
            All listed autonomous types allowed
          </p>
        )}
      </div>
      <div>
        <Label
          htmlFor="autonomous-external-origins"
          className="text-slate-200 mb-2 block"
        >
          Work sources
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          Choose a source policy, or enter custom origins below.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          <button
            type="button"
            className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-200"
            onClick={() => {
              setDraftOrigins('agent-hub-context-maintenance')
              onExternalOriginsChange('agent-hub-context-maintenance')
            }}
            disabled={isPending}
          >
            Context maintenance only
          </button>
          <button
            type="button"
            className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-200"
            onClick={() => {
              setDraftOrigins('')
              onExternalOriginsChange('')
            }}
            disabled={isPending}
          >
            All work sources
          </button>
        </div>
        <Label
          htmlFor="autonomous-external-origins"
          className="text-slate-300 text-sm mb-2 block"
        >
          Custom origins
        </Label>
        <Input
          id="autonomous-external-origins"
          value={draftOrigins}
          onChange={(event) => setDraftOrigins(event.target.value)}
          disabled={isPending}
          placeholder="agent-hub-context-maintenance"
        />
        <button
          type="button"
          className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-200 mt-2"
          onClick={() => onExternalOriginsChange(draftOrigins)}
          disabled={isPending}
        >
          Apply custom sources
        </button>
      </div>
    </div>
  )
}
