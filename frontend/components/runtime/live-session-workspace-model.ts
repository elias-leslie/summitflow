import type { CSSProperties } from 'react'
import type { LiveSessionStatus } from '@/lib/api/runtime'

export interface LiveFrameRect {
  left: number
  top: number
  width: number
  height: number
}

export interface FrameAnnotation {
  id: string
  kind: 'pin' | 'box'
  x: number
  y: number
  width?: number
  height?: number
}

export interface FrameDisplayRect {
  leftPercent: number
  topPercent: number
  widthPercent: number
  heightPercent: number
}

export type InteractionMode = 'control' | 'pin' | 'box'

export const LIVE_SESSION_TOKEN_PREFIX = 'summitflow-live-session-token'
export const SESSION_REFETCH_INTERVAL_MS = 5000
export const FRAME_REFETCH_INTERVAL_MS = 900
export const WHEEL_THROTTLE_MS = 80
export const MIN_BOX_SIZE = 8

export const LIVE_SESSIONS_QUERY_KEY = ['runtime', 'live-sessions'] as const

export const VIEWPORTS = [
  { label: '720', width: 1280, height: 720 },
  { label: '900', width: 1440, height: 900 },
  { label: '1080', width: 1920, height: 1080 },
] as const

export const EMPTY_FRAME_DISPLAY: FrameDisplayRect = {
  leftPercent: 0,
  topPercent: 0,
  widthPercent: 100,
  heightPercent: 100,
}

type BrowserTargetSession = Pick<
  LiveSessionStatus,
  'browser_target_debug_local' | 'browser_target_host' | 'browser_target_port'
>

export function liveSessionTokenStorageKey(sessionId: string): string {
  return `${LIVE_SESSION_TOKEN_PREFIX}:${sessionId}`
}

export function liveSessionQueryKey(sessionId: string) {
  return ['runtime', 'live-session', sessionId] as const
}

export function liveSessionFrameQueryKey(
  sessionId: string,
  hasOperatorToken: boolean,
) {
  return ['runtime', 'live-session-frame', sessionId, hasOperatorToken] as const
}

export function browserTargetLabel(session: BrowserTargetSession): string {
  if (!session.browser_target_host || !session.browser_target_port) {
    return 'unavailable'
  }
  const mode = session.browser_target_debug_local ? 'debug-local' : 'isolated'
  return `${mode} ${session.browser_target_host}:${session.browser_target_port}`
}

export function shortTime(value: string | null): string {
  if (!value) return 'none'
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function mapLiveFramePoint(
  clientX: number,
  clientY: number,
  rect: LiveFrameRect,
  viewportWidth: number,
  viewportHeight: number,
): { x: number; y: number } | null {
  if (rect.width <= 0 || rect.height <= 0) return null
  const xRatio = (clientX - rect.left) / rect.width
  const yRatio = (clientY - rect.top) / rect.height
  if (xRatio < 0 || xRatio > 1 || yRatio < 0 || yRatio > 1) return null
  return {
    x: Math.round(xRatio * viewportWidth),
    y: Math.round(yRatio * viewportHeight),
  }
}

export function normalizeAnnotationBox(
  start: { x: number; y: number },
  end: { x: number; y: number },
): Pick<FrameAnnotation, 'height' | 'width' | 'x' | 'y'> {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  }
}

export function frameAnnotationStyle(
  annotation: FrameAnnotation,
  frameDisplay: FrameDisplayRect,
  viewportWidth: number,
  viewportHeight: number,
): CSSProperties {
  const left =
    frameDisplay.leftPercent +
    (annotation.x / viewportWidth) * frameDisplay.widthPercent
  const top =
    frameDisplay.topPercent +
    (annotation.y / viewportHeight) * frameDisplay.heightPercent

  if (annotation.kind === 'pin') {
    return {
      left: `${left}%`,
      top: `${top}%`,
    }
  }

  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${((annotation.width ?? 0) / viewportWidth) * frameDisplay.widthPercent}%`,
    height: `${((annotation.height ?? 0) / viewportHeight) * frameDisplay.heightPercent}%`,
  }
}
