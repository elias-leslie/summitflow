'use client'

import Image from 'next/image'
import { useCallback, useEffect, useRef, useState } from 'react'

interface ComparisonSliderProps {
  /** URL for the "before" image (original screenshot) */
  beforeImageUrl: string
  /** URL for the "after" image (generated mockup) */
  afterImageUrl: string
  /** Alt text for accessibility */
  beforeAlt?: string
  afterAlt?: string
}

/**
 * A before/after comparison slider component.
 *
 * Displays two images overlaid with a vertical divider that can be
 * dragged left/right to reveal more of either image.
 */
export function ComparisonSlider({
  beforeImageUrl,
  afterImageUrl,
  beforeAlt = 'Before',
  afterAlt = 'After',
}: ComparisonSliderProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [sliderPosition, setSliderPosition] = useState(50)
  const [isDragging, setIsDragging] = useState(false)

  const updateSliderPosition = useCallback((clientX: number) => {
    if (!containerRef.current) return

    const rect = containerRef.current.getBoundingClientRect()
    const x = clientX - rect.left
    const percentage = Math.max(0, Math.min(100, (x / rect.width) * 100))
    setSliderPosition(percentage)
  }, [])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsDragging(true)
      updateSliderPosition(e.clientX)
    },
    [updateSliderPosition],
  )

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging) return
      updateSliderPosition(e.clientX)
    },
    [isDragging, updateSliderPosition],
  )

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      setIsDragging(true)
      updateSliderPosition(e.touches[0].clientX)
    },
    [updateSliderPosition],
  )

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (!isDragging) return
      updateSliderPosition(e.touches[0].clientX)
    },
    [isDragging, updateSliderPosition],
  )

  const handleTouchEnd = useCallback(() => {
    setIsDragging(false)
  }, [])

  // Add global mouse/touch event listeners for dragging
  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      window.addEventListener('touchmove', handleTouchMove)
      window.addEventListener('touchend', handleTouchEnd)
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleTouchEnd)
    }
  }, [
    isDragging,
    handleMouseMove,
    handleMouseUp,
    handleTouchMove,
    handleTouchEnd,
  ])

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden cursor-ew-resize select-none"
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
    >
      {/* After image (full size, visible on right side of slider) */}
      <div className="absolute inset-0">
        <Image
          src={afterImageUrl}
          alt={afterAlt}
          fill
          className="object-contain"
          unoptimized
          draggable={false}
        />
      </div>

      {/* Before image (clipped to left side of slider) */}
      <div
        className="absolute inset-0 overflow-hidden"
        style={{ width: `${sliderPosition}%` }}
      >
        <div
          className="relative w-full h-full"
          style={{ width: `${100 / (sliderPosition / 100)}%` }}
        >
          <Image
            src={beforeImageUrl}
            alt={beforeAlt}
            fill
            className="object-contain"
            unoptimized
            draggable={false}
          />
        </div>
      </div>

      {/* Slider line and handle */}
      <div
        className="absolute top-0 bottom-0 w-0.5 bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.4)]"
        style={{ left: `${sliderPosition}%`, transform: 'translateX(-50%)' }}
      >
        {/* Handle */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 bg-slate-800 border-2 border-phosphor-500 rounded-full shadow-[0_0_12px_rgba(0,245,255,0.3)] flex items-center justify-center">
          <div className="flex items-center gap-1">
            <div className="w-0 h-0 border-y-4 border-y-transparent border-r-4 border-r-phosphor-400" />
            <div className="w-0 h-0 border-y-4 border-y-transparent border-l-4 border-l-phosphor-400" />
          </div>
        </div>
      </div>

      {/* Labels */}
      <div className="absolute top-2 left-2 px-2 py-1 bg-slate-950/80 rounded text-xs text-slate-100 font-medium">
        Before
      </div>
      <div className="absolute top-2 right-2 px-2 py-1 bg-slate-950/80 rounded text-xs text-slate-100 font-medium">
        After
      </div>
    </div>
  )
}
