'use client'

import { type StreamStatus } from '@agent-hub/chat-ui'
import {
  ArrowLeftToLine,
  ArrowRightToLine,
  GripVertical,
  MessageSquarePlus,
  Radio,
  ShieldCheck,
} from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  BUILDER_SNAP_PERCENT,
  DEFAULT_VERIFIER_SPLIT,
  VERIFIER_COLLAPSE_THRESHOLD,
  VERIFIER_MAX_PERCENT,
  VERIFIER_MIN_PERCENT,
  VERIFIER_SNAP_PERCENT,
} from './constants'
import { PaneBadge, PaneStatus } from './page-controls'
import type { WorkChatPane } from './types'

export function ChatLane({
  label,
  kind,
  collapsed,
  status,
  error,
  sessionId,
  children,
}: {
  label: string
  kind: 'builder' | 'verifier'
  collapsed: boolean
  status: StreamStatus
  error: string | null
  sessionId: string | null
  children: React.ReactNode
}) {
  const Icon = kind === 'verifier' ? ShieldCheck : MessageSquarePlus

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-slate-800 bg-slate-950/80 px-2">
        <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        {!collapsed ? (
          <span className="min-w-0 truncate text-xs font-medium text-slate-300">
            {label}
          </span>
        ) : null}
        <div className="flex-1" />
        <PaneStatus status={status} error={error} />
        {!collapsed && sessionId ? (
          <PaneBadge title={sessionId}>
            <Radio className="h-3.5 w-3.5" />
          </PaneBadge>
        ) : null}
      </div>
      {collapsed ? (
        <div className="flex min-h-0 flex-1 flex-col items-center gap-2 overflow-hidden px-1 py-2 text-[10px] text-slate-500">
          <Icon className="h-4 w-4 text-slate-500" />
          <PaneStatus status={status} error={error} />
          {sessionId ? (
            <span className="max-w-full truncate">{sessionId.slice(0, 8)}</span>
          ) : null}
        </div>
      ) : null}
      <div className={cn('min-h-0 flex-1', collapsed && 'hidden')}>
        {children}
      </div>
    </div>
  )
}

export function BuilderVerifierSplit({
  pane,
  builderRuntime,
  verifierRuntime,
  builderSessionId,
  verifierSessionId,
  builderLabel,
  onPatch,
  builder,
  verifier,
}: {
  pane: WorkChatPane
  builderRuntime: { status: StreamStatus; error: string | null }
  verifierRuntime: { status: StreamStatus; error: string | null }
  builderSessionId: string | null
  verifierSessionId: string | null
  builderLabel: string
  onPatch: (patch: Partial<WorkChatPane>) => void
  builder: React.ReactNode
  verifier: React.ReactNode
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [dragging, setDragging] = useState(false)
  const split = Math.min(
    VERIFIER_MAX_PERCENT,
    Math.max(
      VERIFIER_MIN_PERCENT,
      pane.verifierSplitPercent || DEFAULT_VERIFIER_SPLIT,
    ),
  )
  const builderCollapsed = split <= VERIFIER_COLLAPSE_THRESHOLD
  const verifierCollapsed = split >= 100 - VERIFIER_COLLAPSE_THRESHOLD

  const updateFromClientX = useCallback(
    (clientX: number) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect?.width) return
      const next = ((clientX - rect.left) / rect.width) * 100
      onPatch({
        verifierSplitPercent: Math.min(
          VERIFIER_MAX_PERCENT,
          Math.max(VERIFIER_MIN_PERCENT, Math.round(next)),
        ),
      })
    },
    [onPatch],
  )

  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      setDragging(true)
      updateFromClientX(event.clientX)
      const onMove = (moveEvent: PointerEvent) => {
        updateFromClientX(moveEvent.clientX)
      }
      const onUp = () => {
        setDragging(false)
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
    },
    [updateFromClientX],
  )

  return (
    <div ref={containerRef} className="flex h-full min-h-0 overflow-hidden">
      <div
        className="min-h-0 min-w-[92px] overflow-hidden"
        style={{ flexBasis: `${split}%` }}
      >
        <ChatLane
          label={builderLabel}
          kind="builder"
          collapsed={builderCollapsed}
          status={builderRuntime.status}
          error={builderRuntime.error}
          sessionId={builderSessionId}
        >
          {builder}
        </ChatLane>
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={VERIFIER_MIN_PERCENT}
        aria-valuemax={VERIFIER_MAX_PERCENT}
        aria-valuenow={split}
        tabIndex={0}
        onPointerDown={startDrag}
        className={cn(
          'group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center border-x border-slate-800 bg-slate-900/80 outline-none transition-colors',
          'hover:border-phosphor-500/50 hover:bg-slate-800 focus:border-phosphor-500/60',
          dragging && 'border-phosphor-500/70 bg-slate-800',
        )}
      >
        <GripVertical className="h-4 w-4 text-slate-500 group-hover:text-slate-200" />
        <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus:pointer-events-auto group-focus:opacity-100">
          <button
            type="button"
            title="Show verifier"
            aria-label="Show verifier"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onPatch({ verifierSplitPercent: VERIFIER_SNAP_PERCENT })
            }}
            className="flex h-6 w-6 items-center justify-center rounded border border-slate-700 bg-slate-950 text-slate-300 shadow hover:border-phosphor-500/60 hover:text-phosphor-200"
          >
            <ArrowLeftToLine className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Show builder"
            aria-label="Show builder"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onPatch({ verifierSplitPercent: BUILDER_SNAP_PERCENT })
            }}
            className="flex h-6 w-6 items-center justify-center rounded border border-slate-700 bg-slate-950 text-slate-300 shadow hover:border-phosphor-500/60 hover:text-phosphor-200"
          >
            <ArrowRightToLine className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        className="min-h-0 min-w-[92px] overflow-hidden"
        style={{ flexBasis: `${100 - split}%` }}
      >
        <ChatLane
          label="Verifier"
          kind="verifier"
          collapsed={verifierCollapsed}
          status={verifierRuntime.status}
          error={verifierRuntime.error}
          sessionId={verifierSessionId}
        >
          {verifier}
        </ChatLane>
      </div>
    </div>
  )
}
