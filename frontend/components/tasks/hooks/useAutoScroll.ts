import { useCallback, useEffect, useRef } from 'react'

export function useAutoScroll(eventsLength: number) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const wasAtBottomRef = useRef(true)

  const checkIfAtBottom = useCallback(() => {
    if (!scrollRef.current) return true
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    return scrollHeight - scrollTop - clientHeight < 50
  }, [])

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    }
  }, [])

  useEffect(() => {
    if (wasAtBottomRef.current && eventsLength > 0) {
      scrollToBottom()
    }
  }, [eventsLength, scrollToBottom])

  const handleScroll = useCallback(() => {
    wasAtBottomRef.current = checkIfAtBottom()
  }, [checkIfAtBottom])

  return { scrollRef, handleScroll }
}
