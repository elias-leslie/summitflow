'use client'

import { Label } from '@/components/ui/label'

interface AgentHubSectionProps {
  syncAgentHubPermission: boolean
  permissionTier: string
  autoExecEnabled: boolean
  onSyncChange: (value: boolean) => void
  onTierChange: (value: string) => void
  onAutoExecChange: (value: boolean) => void
}

export function AgentHubSection({
  syncAgentHubPermission,
  permissionTier,
  autoExecEnabled,
  onSyncChange,
  onTierChange,
  onAutoExecChange,
}: AgentHubSectionProps) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-800/70 bg-slate-950/40 p-4">
      <div className="space-y-1">
        <div className="text-sm font-medium text-slate-100">
          Agent Hub Access Bootstrap
        </div>
        <p className="text-xs text-slate-500">
          Create the matching project permission row at the same time so the new project is immediately visible to Jenny and specialist agents.
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={syncAgentHubPermission}
          onChange={(event) => onSyncChange(event.target.checked)}
          className="h-4 w-4 rounded border-slate-700 bg-slate-950"
        />
        Provision Agent Hub permission
      </label>

      {syncAgentHubPermission && (
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
          <div className="space-y-2">
            <Label htmlFor="permissionTier">Permission Tier</Label>
            <select
              id="permissionTier"
              value={permissionTier}
              onChange={(event) => onTierChange(event.target.value)}
              className="flex h-10 w-full rounded-md border border-slate-800 bg-slate-950 px-3 text-sm text-slate-100"
            >
              <option value="off">Off</option>
              <option value="read">Read</option>
              <option value="write">Write</option>
              <option value="yolo">YOLO</option>
            </select>
          </div>

          <label className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950 px-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={autoExecEnabled}
              onChange={(event) => onAutoExecChange(event.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-950"
            />
            Auto Exec
          </label>
        </div>
      )}
    </div>
  )
}
