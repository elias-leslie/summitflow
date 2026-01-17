import { type RefObject, useEffect } from 'react'

/**
 * Hook to detect clicks outside of specified elements.
 * Useful for closing dropdowns, modals, etc when clicking elsewhere.
 *
 * @param refs - Array of refs to elements that should not trigger the handler
 * @param handler - Called when click occurs outside all refs
 * @param enabled - Whether the handler is active (default: true)
 */
export function useClickOutside(
  refs: RefObject<HTMLElement | null>[],
  handler: () => void,
  enabled: boolean = true,
): void {
  useEffect(() => {
    if (!enabled) return

    const handleClickOutside = (e: MouseEvent) => {
      const clickedOutsideAll = refs.every(
        (ref) => ref.current && !ref.current.contains(e.target as Node),
      )
      if (clickedOutsideAll) {
        handler()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [refs, handler, enabled])
}
