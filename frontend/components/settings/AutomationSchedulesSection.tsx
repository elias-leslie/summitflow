'use client'

import { clsx } from 'clsx'
import { CalendarClock, Loader2 } from 'lucide-react'
import type { AutonomousSchedule } from '@/lib/api'

interface AutomationSchedulesSectionProps {
  projectId: string
  schedules: AutonomousSchedule[]
  updatingScheduleId: string | null
  onToggle: (schedule: AutonomousSchedule) => void
}

function scopeLabel(schedule: AutonomousSchedule, projectId: string): string {
  if (schedule.scope === 'project') {
    return 'Project'
  }
  return schedule.managed_project_id === projectId
    ? 'System'
    : `System · ${schedule.managed_project_id}`
}

export function AutomationSchedulesSection({
  projectId,
  schedules,
  updatingScheduleId,
  onToggle,
}: AutomationSchedulesSectionProps) {
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-5">
      <div>
        <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
          <CalendarClock className="w-4 h-4 text-slate-400" />
          Scheduled Jobs
        </h3>
        <p className="text-xs text-slate-400 mt-2">
          Every SummitFlow cron job is listed here. Disable the noisy
          entrypoints first, then tune deeper behavior below.
        </p>
      </div>

      <div className="space-y-3">
        {schedules.map((schedule) => {
          const isPending = updatingScheduleId === schedule.schedule_id
          return (
            <div
              key={schedule.schedule_id}
              className="rounded-xl border border-slate-700/70 bg-slate-900/35 px-4 py-3"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-sm font-medium text-slate-100">
                      {schedule.label}
                    </h4>
                    <span className="rounded-full border border-slate-600/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-300">
                      {schedule.cron}
                    </span>
                    <span className="rounded-full border border-slate-700 bg-slate-800/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-400">
                      {scopeLabel(schedule, projectId)}
                    </span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-400">
                    {schedule.description}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => onToggle(schedule)}
                  disabled={isPending}
                  role="switch"
                  aria-checked={schedule.enabled}
                  aria-label={
                    schedule.enabled
                      ? `Disable ${schedule.label}`
                      : `Enable ${schedule.label}`
                  }
                  className={clsx(
                    'relative h-6 w-12 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
                    schedule.enabled ? 'bg-amber-500' : 'bg-slate-600',
                  )}
                >
                  <span
                    className={clsx(
                      'absolute top-1 h-4 w-4 rounded-full bg-slate-100 shadow-sm transition-transform',
                      schedule.enabled ? 'translate-x-7' : 'translate-x-1',
                    )}
                  />
                </button>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-medium">
                <span
                  className={clsx(
                    'rounded-full px-2 py-1',
                    schedule.enabled
                      ? 'bg-emerald-500/10 text-emerald-300'
                      : 'bg-slate-700/60 text-slate-400',
                  )}
                >
                  {schedule.enabled ? 'Enabled' : 'Disabled'}
                </span>
                {isPending && (
                  <span className="inline-flex items-center gap-1 text-amber-300">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Saving
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
