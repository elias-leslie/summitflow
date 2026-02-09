import { useState, useEffect } from 'react'
import { COLLAPSED_KEY } from '../types'

interface UseSidebarStateReturn {
  isCollapsed: boolean
  mounted: boolean
  toggleCollapsed: () => void
}

export function useSidebarState(): UseSidebarStateReturn {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    const storedCollapsed = localStorage.getItem(COLLAPSED_KEY)

    if (storedCollapsed !== null) {
      setIsCollapsed(storedCollapsed === 'true')
    }
    setMounted(true)
  }, [])

  const toggleCollapsed = () => {
    const newValue = !isCollapsed
    setIsCollapsed(newValue)
    localStorage.setItem(COLLAPSED_KEY, String(newValue))
  }

  return {
    isCollapsed,
    mounted,
    toggleCollapsed,
  }
}
