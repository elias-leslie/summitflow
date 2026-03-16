'use client'

import { useLayoutEffect, useRef, useState } from 'react'

export function useAdaptiveNavigation(searchExpanded: boolean) {
  const slotRef = useRef<HTMLDivElement>(null)
  const measureRef = useRef<HTMLDivElement>(null)
  const [compact, setCompact] = useState(false)

  useLayoutEffect(() => {
    const slot = slotRef.current
    const measure = measureRef.current

    if (!slot || !measure || typeof ResizeObserver === 'undefined') {
      return
    }

    let frame = 0

    const update = () => {
      frame = 0
      setCompact(measure.scrollWidth > slot.clientWidth)
    }

    const scheduleUpdate = () => {
      if (frame) return
      frame = window.requestAnimationFrame(update)
    }

    scheduleUpdate()

    const observer = new ResizeObserver(scheduleUpdate)
    observer.observe(slot)
    observer.observe(measure)

    return () => {
      if (frame) {
        window.cancelAnimationFrame(frame)
      }
      observer.disconnect()
    }
  }, [searchExpanded])

  return { compact, measureRef, slotRef }
}
