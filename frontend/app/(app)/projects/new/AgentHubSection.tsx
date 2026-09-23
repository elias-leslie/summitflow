'use client'

import { Label } from '@/components/ui/label'

interface AgentHubSectionProps {
  syncAgentHubPermission: boolean
  permissionTier: string
  onSyncChange: (value: boolean) => void
  onTierChange: (value: string) => void
}

export function AgentHubSection({
  syncAgentHubPermission,
  permissionTier,
  onSyncChange,
  onTierChange,
}: AgentHubSectionProps) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-800/70 bg-slate-950/40 p-4">
      <div className="space-y-1">
        <div className="text-sm font-medium text-slate-100">
          Agent Hub Access Bootstrap
        </div>
        <p className="text-xs text-slate-500">
          Create the matching project permission row at the same time so the new
          project is immediately visible to Jenny and specialist agents.
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
        <div className="space-y-2">
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
              <option value="full">Full</option>
            </select>
          </div>
        </div>
      )}

      <p className="text-xs text-slate-400">
        Automated execution starts disabled. After creating the project, set
        execution permission and schedules in Agent Hub.
      </p>
      <a
        href="https://agent.summitflow.dev/automations"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block text-xs text-phosphor-300 underline underline-offset-2 hover:text-phosphor-200"
      >
        Open Agent Hub Automations
      </a>
    </div>
  )
}
