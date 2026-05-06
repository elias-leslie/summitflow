'use client'

import { Loader2 } from 'lucide-react'
import type {
  KeyboardEventHandler,
  MouseEventHandler,
  RefObject,
  WheelEventHandler,
} from 'react'
import {
  type FrameAnnotation,
  type FrameDisplayRect,
  frameAnnotationStyle,
} from './live-session-workspace-model'

interface LiveSessionViewportProps {
  viewportRef: RefObject<HTMLButtonElement | null>
  frameImageRef: RefObject<HTMLImageElement | null>
  frameImageUrl: string | null | undefined
  tokenMissing: boolean
  annotations: FrameAnnotation[]
  frameDisplay: FrameDisplayRect
  viewportWidth: number
  viewportHeight: number
  onFrameImageLoad: () => void
  onClick: MouseEventHandler<HTMLButtonElement>
  onMouseDown: MouseEventHandler<HTMLButtonElement>
  onMouseUp: MouseEventHandler<HTMLButtonElement>
  onKeyDown: KeyboardEventHandler<HTMLButtonElement>
  onWheel: WheelEventHandler<HTMLButtonElement>
}

export function LiveSessionViewport({
  viewportRef,
  frameImageRef,
  frameImageUrl,
  tokenMissing,
  annotations,
  frameDisplay,
  viewportWidth,
  viewportHeight,
  onFrameImageLoad,
  onClick,
  onMouseDown,
  onMouseUp,
  onKeyDown,
  onWheel,
}: LiveSessionViewportProps) {
  return (
    <button
      type="button"
      ref={viewportRef}
      aria-label="Live browser viewport"
      onClick={onClick}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onKeyDown={onKeyDown}
      onWheel={onWheel}
      className="relative flex min-h-[50vh] w-full items-center justify-center overflow-hidden rounded-lg border border-slate-800 bg-black p-0 outline-none ring-0 focus:border-sky-500/60"
    >
      {frameImageUrl ? (
        // biome-ignore lint/performance/noImgElement: Live JPEG data URL from local backend broker.
        <img
          ref={frameImageRef}
          src={frameImageUrl}
          onLoad={onFrameImageLoad}
          alt="Live browser frame"
          draggable={false}
          className="block max-h-[calc(100vh-8rem)] w-full object-contain"
        />
      ) : tokenMissing ? (
        <div className="px-6 text-center text-sm text-amber-200">
          Operator token required. Start a new session from Runtime.
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading frame
        </div>
      )}
      {annotations.length > 0 && (
        <div className="pointer-events-none absolute inset-0">
          {annotations.map((annotation, index) =>
            annotation.kind === 'pin' ? (
              <div
                key={annotation.id}
                className="absolute -ml-3 -mt-3 flex h-6 w-6 items-center justify-center rounded-full border border-amber-200 bg-amber-400/90 text-[10px] font-semibold text-slate-950 shadow-lg shadow-black/40"
                style={frameAnnotationStyle(
                  annotation,
                  frameDisplay,
                  viewportWidth,
                  viewportHeight,
                )}
              >
                {index + 1}
              </div>
            ) : (
              <div
                key={annotation.id}
                className="absolute border-2 border-cyan-300 bg-cyan-300/10 shadow-lg shadow-black/40"
                style={frameAnnotationStyle(
                  annotation,
                  frameDisplay,
                  viewportWidth,
                  viewportHeight,
                )}
              />
            ),
          )}
        </div>
      )}
    </button>
  )
}
