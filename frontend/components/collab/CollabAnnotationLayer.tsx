import { type PointerEvent, useRef, useState } from 'react'
import type { CollabAnnotation } from '@/lib/api/collab'

export interface CollabAnchorSelection {
  x: number
  y: number
  width?: number
  height?: number
  viewport_width: number
  viewport_height: number
  scroll_x: number
  scroll_y: number
}

interface CollabAnnotationLayerProps {
  annotations: CollabAnnotation[]
  draftAnchor?: CollabAnchorSelection
  disabled?: boolean
  markKind?: string
  onAnchorChange?: (anchor: CollabAnchorSelection) => void
}

export function CollabAnnotationLayer({
  annotations,
  draftAnchor,
  disabled = false,
  markKind = 'box',
  onAnchorChange,
}: CollabAnnotationLayerProps): React.ReactElement {
  const startRef = useRef<{ x: number; y: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  function pointFromEvent(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left))
    const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top))
    return {
      x,
      y,
      viewport_width: rect.width,
      viewport_height: rect.height,
    }
  }

  function updateDraft(
    event: PointerEvent<HTMLDivElement>,
    mode: 'start' | 'move' | 'end',
  ) {
    if (disabled || !onAnchorChange) return
    const point = pointFromEvent(event)
    if (mode === 'start') {
      startRef.current = { x: point.x, y: point.y }
      setDragging(true)
      event.currentTarget.setPointerCapture(event.pointerId)
      if (markKind === 'pin') {
        onAnchorChange({
          x: point.x,
          y: point.y,
          viewport_width: point.viewport_width,
          viewport_height: point.viewport_height,
          scroll_x: 0,
          scroll_y: 0,
        })
        return
      }
    }

    const start = startRef.current
    if (!start) return
    const x = Math.min(start.x, point.x)
    const y = Math.min(start.y, point.y)
    const width = Math.max(8, Math.abs(point.x - start.x))
    const height = Math.max(8, Math.abs(point.y - start.y))
    onAnchorChange({
      x,
      y,
      width,
      height,
      viewport_width: point.viewport_width,
      viewport_height: point.viewport_height,
      scroll_x: 0,
      scroll_y: 0,
    })
    if (mode === 'end') {
      setDragging(false)
      startRef.current = null
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <div
      className={cn(
        'relative min-h-[260px] overflow-hidden rounded-lg border border-slate-800 bg-slate-950',
        disabled ? 'cursor-default' : 'cursor-crosshair',
      )}
      data-testid="collab-annotation-layer"
      onPointerDown={(event) => updateDraft(event, 'start')}
      onPointerMove={(event) => {
        if (dragging) updateDraft(event, 'move')
      }}
      onPointerUp={(event) => updateDraft(event, 'end')}
    >
      <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:32px_32px]" />
      <div className="absolute inset-x-0 top-0 border-b border-slate-800 bg-slate-950/90 px-3 py-2 text-xs text-slate-400">
        Shared review surface
      </div>
      {annotations.map((annotation, index) => {
        const x = Number(annotation.anchor.x ?? 80 + index * 36)
        const y = Number(annotation.anchor.y ?? 80 + index * 28)
        const width = Number(annotation.anchor.width ?? 160)
        const height = Number(annotation.anchor.height ?? 84)
        const viewportWidth = Number(annotation.anchor.viewport_width ?? 1440)
        const viewportHeight = Number(annotation.anchor.viewport_height ?? 900)
        const left = `${Math.max(0, Math.min(94, (x / viewportWidth) * 100))}%`
        const top = `${Math.max(10, Math.min(88, (y / viewportHeight) * 100))}%`
        const boxWidth = `${Math.max(6, Math.min(40, (width / viewportWidth) * 100))}%`
        const boxHeight = `${Math.max(6, Math.min(32, (height / viewportHeight) * 100))}%`

        if (annotation.kind === 'box' || annotation.kind === 'highlight') {
          return (
            <div
              key={annotation.annotation_id}
              className="absolute rounded border-2 border-cyan-300 bg-cyan-300/10 shadow-lg shadow-black/40"
              style={{ left, top, width: boxWidth, height: boxHeight }}
              title={annotation.comment}
            />
          )
        }

        return (
          <div
            key={annotation.annotation_id}
            className="absolute -ml-3 -mt-3 flex h-6 w-6 items-center justify-center rounded-full border border-amber-200 bg-amber-400 text-[10px] font-semibold text-slate-950 shadow-lg shadow-black/40"
            style={{ left, top }}
            title={annotation.comment}
          >
            {index + 1}
          </div>
        )
      })}
      {draftAnchor && <DraftMark anchor={draftAnchor} kind={markKind} />}
      {annotations.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-slate-500">
          No shared marks yet
        </div>
      )}
    </div>
  )
}

function DraftMark({
  anchor,
  kind,
}: {
  anchor: CollabAnchorSelection
  kind: string
}): React.ReactElement {
  const left = `${Math.max(0, Math.min(94, (anchor.x / anchor.viewport_width) * 100))}%`
  const top = `${Math.max(10, Math.min(88, (anchor.y / anchor.viewport_height) * 100))}%`
  if (kind === 'pin') {
    return (
      <div
        className="absolute -ml-3 -mt-3 flex h-6 w-6 items-center justify-center rounded-full border border-fuchsia-100 bg-fuchsia-300 text-[10px] font-semibold text-slate-950 shadow-lg shadow-black/40"
        style={{ left, top }}
      >
        +
      </div>
    )
  }

  const width = Number(anchor.width ?? 160)
  const height = Number(anchor.height ?? 84)
  const boxWidth = `${Math.max(6, Math.min(44, (width / anchor.viewport_width) * 100))}%`
  const boxHeight = `${Math.max(6, Math.min(36, (height / anchor.viewport_height) * 100))}%`
  return (
    <div
      className="absolute rounded border-2 border-fuchsia-300 bg-fuchsia-300/10 shadow-lg shadow-black/40"
      style={{ left, top, width: boxWidth, height: boxHeight }}
    />
  )
}

function cn(...classes: Array<string | false>): string {
  return classes.filter(Boolean).join(' ')
}
