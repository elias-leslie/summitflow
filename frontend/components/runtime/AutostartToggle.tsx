'use client'

import { clsx } from 'clsx'
import { useServiceAction } from './useServiceAction'

interface AutostartToggleProps {
  service: string
  autoStart: boolean | null
  /** 'switch' renders a labelled toggle (cards); 'chip' renders a compact pill (list rows). */
  variant?: 'switch' | 'chip'
}

/**
 * Toggle systemd boot auto-start (UnitFileState) for a service. Renders nothing
 * when autoStart is null (Docker infra / static units that can't be toggled).
 * Changing this only affects whether the unit starts on reboot/login — it does
 * not start or stop the running service.
 */
export function AutostartToggle({
  service,
  autoStart,
  variant = 'switch',
}: AutostartToggleProps) {
  // autoStart === null => not user-togglable; hooks below still run unconditionally.
  const enabled = autoStart === true
  const action = useServiceAction(service, enabled ? 'disable' : 'enable')

  if (autoStart === null) return null

  const title = enabled
    ? 'Auto-start ON — service will start on reboot. Click to disable.'
    : 'Auto-start OFF — service stays down after reboot. Click to enable.'

  if (variant === 'chip') {
    return (
      <button
        type="button"
        onClick={() => action.mutate()}
        disabled={action.isPending}
        title={title}
        className={clsx(
          'text-2xs px-1.5 py-0.5 rounded border transition-colors disabled:opacity-40',
          enabled
            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20'
            : 'bg-slate-700/40 text-slate-500 border-slate-700/60 hover:text-slate-300',
        )}
      >
        {action.isPending ? '...' : enabled ? 'Boot: on' : 'Boot: off'}
      </button>
    )
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={`Toggle auto-start for ${service}`}
      onClick={() => action.mutate()}
      disabled={action.isPending}
      title={title}
      className="flex items-center gap-1.5 disabled:opacity-50 group focus-visible:outline-none"
    >
      <span className="text-2xs uppercase tracking-[0.12em] text-slate-500 font-medium">
        Auto-start
      </span>
      <span
        className={clsx(
          'relative inline-flex h-4 w-7 items-center rounded-full transition-colors duration-200 ring-1',
          enabled
            ? 'bg-emerald-500/30 ring-emerald-500/40'
            : 'bg-slate-700/70 ring-slate-600/50',
        )}
      >
        <span
          className={clsx(
            'inline-block h-3 w-3 transform rounded-full transition-transform duration-200 shadow',
            enabled
              ? 'translate-x-3.5 bg-emerald-400'
              : 'translate-x-0.5 bg-slate-400',
          )}
        />
      </span>
    </button>
  )
}
