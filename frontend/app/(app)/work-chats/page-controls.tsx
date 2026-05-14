'use client'

import { ActivityIndicator, type StreamStatus } from '@agent-hub/chat-ui'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const update = () => setIsMobile(window.innerWidth < 768)
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  return isMobile
}

export function IconButton({
  title,
  onClick,
  disabled = false,
  active = false,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={cn(
        'flex h-7 w-7 shrink-0 items-center justify-center rounded border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-phosphor-500/40',
        active
          ? 'border-phosphor-500/40 bg-phosphor-500/10 text-phosphor-300'
          : 'border-slate-800 bg-slate-950/60 text-slate-500 hover:border-slate-600 hover:text-slate-200',
        disabled && 'cursor-not-allowed opacity-40',
      )}
    >
      {children}
    </button>
  )
}

export function SelectControl({
  value,
  onChange,
  label,
  children,
  disabled = false,
  className,
}: {
  value: string
  onChange: (value: string) => void
  label: string
  children: React.ReactNode
  disabled?: boolean
  className?: string
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        'h-7 min-w-0 shrink-0 rounded border border-slate-800 bg-slate-950/70 px-2 text-xs text-slate-200 outline-none transition-colors',
        'hover:border-slate-600 focus:border-phosphor-500/50 disabled:cursor-not-allowed disabled:opacity-40',
        className,
      )}
    >
      {children}
    </select>
  )
}

export function PaneBadge({
  title,
  children,
  active = false,
}: {
  title: string
  children: React.ReactNode
  active?: boolean
}) {
  return (
    <span
      title={title}
      className={cn(
        'flex h-6 min-w-6 shrink-0 items-center justify-center rounded border px-1 text-[10px]',
        active
          ? 'border-phosphor-500/30 bg-phosphor-500/10 text-phosphor-300'
          : 'border-slate-800 bg-slate-950/60 text-slate-500',
      )}
    >
      {children}
    </span>
  )
}

export function PaneStatus({
  status,
  error,
}: {
  status: StreamStatus
  error: string | null
}) {
  if (error || status === 'error') {
    return (
      <PaneBadge title={error ?? 'Chat error'} active>
        <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
      </PaneBadge>
    )
  }
  if (status === 'streaming' || status === 'connecting') {
    return (
      <PaneBadge title={status} active>
        <ActivityIndicator state={status} className="scale-75" />
      </PaneBadge>
    )
  }
  return (
    <PaneBadge title="Ready">
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
    </PaneBadge>
  )
}
