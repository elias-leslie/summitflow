import { CalendarClock, ExternalLink } from 'lucide-react'

interface AutonomousSettingsPanelProps {
  projectId: string
}

export function AutonomousSettingsPanel({
  projectId,
}: AutonomousSettingsPanelProps) {
  const automationsUrl = `https://agent.summitflow.dev/automations?project_id=${encodeURIComponent(projectId)}`

  return (
    <div className="card rounded-xl p-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
        <CalendarClock className="h-5 w-5 text-phosphor-400" />
        Automations
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">
        Set schedules, turn automations on or off, and edit project policy in
        Agent Hub.
      </p>
      <a
        href={automationsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-5 inline-flex items-center gap-2 rounded-lg bg-phosphor-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-phosphor-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-400"
      >
        Open Agent Hub Automations
        <ExternalLink className="h-4 w-4" aria-hidden="true" />
      </a>
    </div>
  )
}
