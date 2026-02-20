'use client'

import { clsx } from 'clsx'
import { Activity, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { getAgentHubProxyBase } from '@/components/tasks/useTaskIdeation'

const INTERVAL_OPTIONS = [
  { value: '15', label: '15 min' },
  { value: '30', label: '30 min' },
  { value: '60', label: '1 hour' },
  { value: '120', label: '2 hours' },
  { value: '240', label: '4 hours' },
  { value: '0', label: 'Off' },
] as const

interface Preferences {
  heartbeat_interval_minutes: number
}

export function HeartbeatSettings() {
  const [interval, setInterval] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const base = getAgentHubProxyBase()
    fetch(`${base}/preferences`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Preferences | null) => {
        if (data) setInterval(data.heartbeat_interval_minutes)
      })
      .catch(() => {})
  }, [])

  const updateInterval = useCallback(
    async (minutes: number) => {
      setSaving(true)
      setOpen(false)
      try {
        const base = getAgentHubProxyBase()
        const res = await fetch(`${base}/preferences`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ heartbeat_interval_minutes: minutes }),
        })
        if (!res.ok) throw new Error(`Save failed (${res.status})`)
        setInterval(minutes)
        const label =
          INTERVAL_OPTIONS.find((o) => o.value === String(minutes))?.label ??
          `${minutes}m`
        toast.success(`Heartbeat ${minutes === 0 ? 'disabled' : `set to ${label}`}`)
      } catch {
        toast.error('Failed to update heartbeat interval')
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('[data-heartbeat-settings]')) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (interval == null) return null

  const currentLabel =
    INTERVAL_OPTIONS.find((o) => o.value === String(interval))?.label ??
    (interval === 0 ? 'Off' : `${interval}m`)

  return (
    <div className="relative" data-heartbeat-settings>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        disabled={saving}
        className={clsx(
          'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-2xs font-mono',
          'border transition-all duration-200',
          interval === 0
            ? 'border-slate-750/60 bg-slate-950/40 text-slate-600 hover:border-slate-700'
            : 'border-phosphor-500/15 bg-phosphor-500/5 text-phosphor-500/70 hover:border-phosphor-500/30 hover:text-phosphor-400',
          saving && 'opacity-50 pointer-events-none',
        )}
      >
        {saving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <Activity
            className={clsx(
              'w-3 h-3',
              interval > 0 && 'animate-[pulse_3s_cubic-bezier(0.4,0,0.6,1)_infinite]',
            )}
          />
        )}
        <span>{currentLabel}</span>
      </button>

      {open && (
        <div
          className={clsx(
            'absolute right-0 bottom-full mb-1.5 z-50',
            'bg-slate-900 border border-slate-700 rounded-lg shadow-xl shadow-black/40',
            'min-w-[140px] p-1',
            'animate-fade-in',
          )}
        >
          <div className="px-2.5 py-1.5 text-2xs font-display text-slate-500 uppercase tracking-wider">
            Heartbeat
          </div>
          {INTERVAL_OPTIONS.map((opt) => {
            const isActive = String(interval) === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => updateInterval(Number(opt.value))}
                className={clsx(
                  'flex items-center w-full px-2.5 py-1.5 text-sm rounded-md',
                  'font-mono transition-colors',
                  isActive
                    ? 'bg-phosphor-500/10 text-phosphor-400'
                    : opt.value === '0'
                      ? 'text-slate-500 hover:bg-slate-800/50 hover:text-slate-400'
                      : 'text-slate-300 hover:bg-slate-800/50',
                )}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
