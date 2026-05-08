'use client'

import { clsx } from 'clsx'
import {
  Bot,
  ExternalLink,
  ListChecks,
  PauseCircle,
  Wrench,
} from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Button } from '../ui/button'

export type AutomationMode = 'off' | 'queue' | 'upkeep'

interface AutomationModeSectionProps {
  mode: AutomationMode
  settings: AutonomousExecutionSettings
  isPending: boolean
  onModeChange: (mode: AutomationMode) => void
}

const MODES: Array<{
  value: AutomationMode
  label: string
  description: string
  icon: typeof PauseCircle
}> = [
  {
    value: 'off',
    label: 'Off',
    description: 'No scheduled agent pickup.',
    icon: PauseCircle,
  },
  {
    value: 'queue',
    label: 'Queue',
    description: 'Work approved autonomous tasks.',
    icon: ListChecks,
  },
  {
    value: 'upkeep',
    label: 'Queue + upkeep',
    description: 'Also create routine maintenance tasks.',
    icon: Wrench,
  },
]

function statusText(settings: AutonomousExecutionSettings): string {
  if (settings.execution_allowed) return 'Agent Hub allows execution'
  if (!settings.enabled) return 'Agent Hub auto-exec is off'
  return settings.permission_reason || 'Agent Hub is blocking execution'
}

export function AutomationModeSection({
  mode,
  settings,
  isPending,
  onModeChange,
}: AutomationModeSectionProps) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-base font-medium text-slate-100">
            <Bot className="h-4 w-4 text-slate-400" />
            Automation Mode
          </h3>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            Jenny is not in the scheduled path. Tasks route by task/subtask type
            to Agent Hub agents; Agent Hub selects the model.
          </p>
        </div>
        <a
          href="https://agent.summitflow.dev/access-control/permissions"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-amber-300 hover:text-amber-200"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Agent Hub access
        </a>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {MODES.map((option) => {
          const Icon = option.icon
          const active = mode === option.value
          return (
            <Button
              key={option.value}
              type="button"
              variant="outline"
              disabled={isPending}
              onClick={() => onModeChange(option.value)}
              className={clsx(
                'h-auto justify-start gap-3 rounded-lg border-slate-700 bg-slate-900/35 px-4 py-3 text-left hover:bg-slate-800',
                active && 'border-amber-400/60 bg-amber-500/10 text-amber-100',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {option.label}
                </span>
                <span className="mt-1 block text-xs font-normal text-slate-400">
                  {option.description}
                </span>
              </span>
            </Button>
          )
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <span
          className={clsx(
            'rounded-full px-2 py-1 font-medium',
            settings.execution_allowed
              ? 'bg-emerald-500/10 text-emerald-300'
              : 'bg-amber-500/10 text-amber-300',
          )}
        >
          {statusText(settings)}
        </span>
        {settings.permission_tier && (
          <span className="rounded-full bg-slate-900/60 px-2 py-1 font-medium text-slate-300">
            {settings.permission_tier}
          </span>
        )}
      </div>
    </div>
  )
}
