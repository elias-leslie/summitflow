'use client'

import {
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
  useRef,
  useState,
  type WheelEvent,
} from 'react'
import type { LiveSessionControl, LiveSessionFrame } from '@/lib/api/runtime'
import {
  type FrameAnnotation,
  type InteractionMode,
  MIN_BOX_SIZE,
  mapLiveFramePoint,
  normalizeAnnotationBox,
  WHEEL_THROTTLE_MS,
} from './live-session-workspace-model'

interface LiveSessionInputParams {
  frame: LiveSessionFrame | undefined
  frameImageRef: RefObject<HTMLImageElement | null>
  viewportRef: RefObject<HTMLButtonElement | null>
  sessionActive: boolean
  canSendInput: boolean
  onSendControl: (control: LiveSessionControl) => void
}

export function useLiveSessionInput({
  frame,
  frameImageRef,
  viewportRef,
  sessionActive,
  canSendInput,
  onSendControl,
}: LiveSessionInputParams) {
  const lastWheelAt = useRef(0)
  const [interactionMode, setInteractionMode] =
    useState<InteractionMode>('control')
  const [annotations, setAnnotations] = useState<FrameAnnotation[]>([])
  const [boxStart, setBoxStart] = useState<{ x: number; y: number } | null>(
    null,
  )

  function sendControl(control: LiveSessionControl): void {
    if (!sessionActive) return
    if (!canSendInput) return
    onSendControl(control)
  }

  function pointFromEvent(event: MouseEvent<HTMLButtonElement>) {
    if (!frame) return null
    const rect =
      frameImageRef.current?.getBoundingClientRect() ??
      event.currentTarget.getBoundingClientRect()
    return mapLiveFramePoint(
      event.clientX,
      event.clientY,
      rect,
      frame.viewport_width,
      frame.viewport_height,
    )
  }

  function handleClick(event: MouseEvent<HTMLButtonElement>): void {
    viewportRef.current?.focus()
    const point = pointFromEvent(event)
    if (!point) return
    if (interactionMode === 'pin') {
      setAnnotations((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          kind: 'pin',
          x: point.x,
          y: point.y,
        },
      ])
      return
    }
    if (interactionMode !== 'control') return
    sendControl({ action: 'click', x: point.x, y: point.y })
  }

  function handleWheel(event: WheelEvent<HTMLButtonElement>): void {
    if (interactionMode !== 'control') return
    const now = Date.now()
    if (now - lastWheelAt.current < WHEEL_THROTTLE_MS) return
    lastWheelAt.current = now
    const point = pointFromEvent(event)
    if (!point) return
    sendControl({
      action: 'wheel',
      x: point.x,
      y: point.y,
      delta_x: Math.round(event.deltaX),
      delta_y: Math.round(event.deltaY),
    })
  }

  function handleKey(event: KeyboardEvent<HTMLButtonElement>): void {
    if (interactionMode !== 'control') return
    if (event.metaKey || event.ctrlKey) return
    event.preventDefault()
    if (event.key.length === 1) {
      sendControl({ action: 'text', text: event.key })
      return
    }
    sendControl({ action: 'key', key: event.key })
  }

  function handleMouseDown(event: MouseEvent<HTMLButtonElement>): void {
    if (interactionMode !== 'box') return
    const point = pointFromEvent(event)
    if (!point) return
    setBoxStart(point)
  }

  function handleMouseUp(event: MouseEvent<HTMLButtonElement>): void {
    if (interactionMode !== 'box' || !boxStart) return
    const point = pointFromEvent(event)
    setBoxStart(null)
    if (!point) return
    const box = normalizeAnnotationBox(boxStart, point)
    if ((box.width ?? 0) < MIN_BOX_SIZE || (box.height ?? 0) < MIN_BOX_SIZE) {
      return
    }
    setAnnotations((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        kind: 'box',
        ...box,
      },
    ])
  }

  return {
    annotations,
    clearAnnotations: () => setAnnotations([]),
    handleClick,
    handleKey,
    handleMouseDown,
    handleMouseUp,
    handleWheel,
    interactionMode,
    sendControl,
    setInteractionMode,
  }
}
