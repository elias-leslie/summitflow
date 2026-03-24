'use client'

import clsx from 'clsx'
import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  SkipBack,
  SkipForward,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

// ============================================================================
// Types
// ============================================================================

interface ReplayControlsProps {
  /** Total number of events */
  totalEvents: number
  /** Currently highlighted event index (-1 for none) */
  currentIndex: number
  /** Callback when the active event changes */
  onIndexChange: (index: number) => void
  /** Event timestamps for density visualization */
  timestamps?: string[]
  className?: string
}

const SPEED_OPTIONS = [1, 2, 5, 10] as const
type Speed = (typeof SPEED_OPTIONS)[number]

// ============================================================================
// ReplayControls Component
// ============================================================================

export function ReplayControls({
  totalEvents,
  currentIndex,
  onIndexChange,
  timestamps,
  className = '',
}: ReplayControlsProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(1)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  // Clear interval on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  // Play/pause timer
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    if (isPlaying && currentIndex < totalEvents - 1) {
      const baseInterval = 1000 // 1 event per second at 1x
      intervalRef.current = setInterval(() => {
        onIndexChange(currentIndex + 1)
      }, baseInterval / speed)
    }

    // Auto-stop at end
    if (isPlaying && currentIndex >= totalEvents - 1) {
      setIsPlaying(false)
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [isPlaying, speed, currentIndex, totalEvents, onIndexChange])

  const handlePlayPause = useCallback(() => {
    if (currentIndex >= totalEvents - 1) {
      // Reset to start if at end
      onIndexChange(0)
      setIsPlaying(true)
    } else {
      setIsPlaying((prev) => !prev)
    }
  }, [currentIndex, totalEvents, onIndexChange])

  const handleStepBack = useCallback(() => {
    setIsPlaying(false)
    onIndexChange(Math.max(0, currentIndex - 1))
  }, [currentIndex, onIndexChange])

  const handleStepForward = useCallback(() => {
    setIsPlaying(false)
    onIndexChange(Math.min(totalEvents - 1, currentIndex + 1))
  }, [currentIndex, totalEvents, onIndexChange])

  const handleSkipToStart = useCallback(() => {
    setIsPlaying(false)
    onIndexChange(0)
  }, [onIndexChange])

  const handleSkipToEnd = useCallback(() => {
    setIsPlaying(false)
    onIndexChange(totalEvents - 1)
  }, [totalEvents, onIndexChange])

  const handleScrubberClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      const x = e.clientX - rect.left
      const ratio = x / rect.width
      const index = Math.round(ratio * (totalEvents - 1))
      setIsPlaying(false)
      onIndexChange(Math.max(0, Math.min(totalEvents - 1, index)))
    },
    [totalEvents, onIndexChange],
  )

  const cycleSpeed = useCallback(() => {
    setSpeed((prev) => {
      const idx = SPEED_OPTIONS.indexOf(prev)
      return SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length]
    })
  }, [])

  if (totalEvents === 0) return null

  const progress =
    totalEvents > 1 ? (currentIndex / (totalEvents - 1)) * 100 : 0

  return (
    <div
      className={clsx('flex items-center gap-2 px-3 py-2 bg-slate-900/80 border border-slate-800/50 rounded-lg', className)}
    >
      {/* Transport controls */}
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={handleSkipToStart}
          className="p-1 text-slate-500 hover:text-slate-300 transition-colors rounded hover:bg-slate-700/50"
          title="Skip to start"
        >
          <SkipBack className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={handleStepBack}
          disabled={currentIndex <= 0}
          className="p-1 text-slate-500 hover:text-slate-300 transition-colors rounded hover:bg-slate-700/50 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Previous event"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={handlePlayPause}
          className={clsx('p-1.5 rounded transition-colors', isPlaying ? 'text-cyan-400 bg-cyan-500/20 hover:bg-cyan-500/30' : 'text-slate-400 hover:text-slate-300 hover:bg-slate-700/50')}
          title={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? (
            <Pause className="h-4 w-4" />
          ) : (
            <Play className="h-4 w-4" />
          )}
        </button>
        <button
          type="button"
          onClick={handleStepForward}
          disabled={currentIndex >= totalEvents - 1}
          className="p-1 text-slate-500 hover:text-slate-300 transition-colors rounded hover:bg-slate-700/50 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Next event"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={handleSkipToEnd}
          className="p-1 text-slate-500 hover:text-slate-300 transition-colors rounded hover:bg-slate-700/50"
          title="Skip to end"
        >
          <SkipForward className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Speed control */}
      <button
        type="button"
        onClick={cycleSpeed}
        className="text-2xs px-1.5 py-0.5 bg-slate-800/60 rounded text-slate-400 hover:text-slate-300 hover:bg-slate-700/60 transition-colors font-mono tabular-nums shrink-0"
        title="Playback speed"
      >
        {speed}x
      </button>

      {/* Scrubber / progress bar */}
      <div
        className="flex-1 relative h-6 cursor-pointer group"
        onClick={handleScrubberClick}
      >
        {/* Track */}
        <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          {/* Progress fill */}
          <div
            className="h-full bg-gradient-to-r from-cyan-600 to-cyan-400 rounded-full transition-[width] duration-100"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Event density ticks */}
        {timestamps && timestamps.length > 0 && timestamps.length <= 200 && (
          <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-3 pointer-events-none">
            {timestamps.map((_, i) => {
              const pos = totalEvents > 1 ? (i / (totalEvents - 1)) * 100 : 50
              return (
                <div
                  key={i}
                  className="absolute top-0 w-px h-full bg-slate-600/40"
                  style={{ left: `${pos}%` }}
                />
              )
            })}
          </div>
        )}

        {/* Thumb */}
        {totalEvents > 1 && (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-cyan-400 rounded-full shadow-lg shadow-cyan-400/30 border-2 border-slate-900 transition-[left] duration-100 group-hover:scale-125"
            style={{ left: `calc(${progress}% - 6px)` }}
          />
        )}
      </div>

      {/* Position counter */}
      <span className="text-2xs text-slate-500 font-mono tabular-nums shrink-0 min-w-[60px] text-right">
        {currentIndex + 1} / {totalEvents}
      </span>
    </div>
  )
}
