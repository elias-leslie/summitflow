'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { fetchProjectHealth, type Project } from '@/lib/api'
import { STALE_STANDARD } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

interface ProjectHealthBadgeProps {
  project: Pick<
    Project,
    'id' | 'name' | 'base_url' | 'health_endpoint' | 'health_status'
  >
  className?: string
  dot?: boolean
}

export function ProjectHealthBadge({
  project,
  className,
  dot = false,
}: ProjectHealthBadgeProps) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const trigger = useRef<HTMLButtonElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const focused = useRef(false)
  const id = useId()
  const configured = Boolean(
    project.base_url?.trim() && project.health_endpoint?.trim(),
  )
  const {
    data: health,
    isFetching,
    error,
  } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    enabled: open && configured,
    staleTime: STALE_STANDARD,
    retry: false,
  })

  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const hide = () => {
    closeTimer.current = setTimeout(() => {
      if (!focused.current) setOpen(false)
    }, 100)
  }

  useEffect(() => {
    if (!open) return
    const updatePosition = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (rect)
        setPosition({
          top: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 260)),
          left: Math.max(8, Math.min(rect.left, window.innerWidth - 328)),
        })
    }
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('keydown', dismiss)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
      window.removeEventListener('keydown', dismiss)
    }
  }, [open])

  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current)
    },
    [],
  )

  const healthy = health?.healthy ?? project.health_status === 'healthy'
  const label = !configured ? 'unconfigured' : healthy ? 'healthy' : 'watch'
  const endpoint = `${project.base_url}${project.health_endpoint}`

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label={`${project.name} health: ${label}`}
        aria-describedby={open ? id : undefined}
        className={clsx(
          'shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950',
          dot
            ? 'flex h-6 w-6 items-center justify-center'
            : 'border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em]',
          !dot &&
            (configured && healthy
              ? 'border-emerald-500/18 bg-emerald-500/10 text-emerald-300'
              : 'border-slate-700/60 bg-slate-900/60 text-slate-400'),
          className,
        )}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={() => {
          focused.current = true
          show()
        }}
        onBlur={() => {
          focused.current = false
          hide()
        }}
        onClick={show}
        data-testid={dot ? 'project-health-indicator' : undefined}
      >
        {dot ? (
          <span
            aria-hidden="true"
            className={clsx(
              'h-3 w-3 rounded-full',
              !configured
                ? 'bg-slate-600'
                : healthy
                  ? 'bg-green-500'
                  : 'bg-rose-500',
            )}
          />
        ) : (
          label
        )}
      </button>
      {open &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            onMouseEnter={show}
            onMouseLeave={hide}
            className="fixed z-[100] max-h-[calc(100vh-1rem)] w-80 max-w-[calc(100vw-1rem)] space-y-2 overflow-y-auto rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300 shadow-xl shadow-black/40"
            style={position}
          >
            <div className="font-semibold text-slate-100">
              {project.name} health
            </div>
            {!configured ? (
              <p>No health endpoint configured.</p>
            ) : (
              <>
                <p className="break-all">
                  Endpoint: <span className="font-mono">{endpoint}</span>
                </p>
                {isFetching && <p role="status">Checking health endpoint...</p>}
                {error ? (
                  <p className="break-words text-rose-300">
                    Health check unavailable:{' '}
                    {getErrorMessage(error, 'Could not load health details.')}
                  </p>
                ) : null}
                {health ? (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                    <dt>Result</dt>
                    <dd>{health.healthy ? 'Healthy' : 'Needs attention'}</dd>
                    <dt>HTTP</dt>
                    <dd>{health.status_code ?? 'Unavailable'}</dd>
                    <dt>Latency</dt>
                    <dd>
                      {health.response_time_ms == null
                        ? 'Unavailable'
                        : `${Math.round(health.response_time_ms)} ms`}
                    </dd>
                    <dt>Checked</dt>
                    <dd>
                      {health.checked_at
                        ? new Date(health.checked_at).toLocaleString()
                        : 'Unavailable'}
                    </dd>
                    {health.error ? (
                      <>
                        <dt>Error</dt>
                        <dd className="break-words text-rose-300">
                          {health.error}
                        </dd>
                      </>
                    ) : null}
                  </dl>
                ) : !isFetching && !error ? (
                  <p>Health details unavailable.</p>
                ) : null}
                {error && health ? (
                  <p className="text-slate-400">Showing the last check.</p>
                ) : null}
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}
