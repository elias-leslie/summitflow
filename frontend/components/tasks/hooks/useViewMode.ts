import { useCallback, useState } from 'react'

export type ViewMode = 'board' | 'table'

const getStorageKey = (projectId: string) => `summitflow-view-mode:${projectId}`

export function useViewMode(projectId: string) {
  const [viewMode, setViewModeInternal] = useState<ViewMode>(() => {
    if (typeof window === 'undefined') return 'board'
    const stored = localStorage.getItem(getStorageKey(projectId))
    return stored === 'table' ? 'table' : 'board'
  })

  const setViewMode = useCallback(
    (mode: ViewMode) => {
      setViewModeInternal(mode)
      localStorage.setItem(getStorageKey(projectId), mode)
    },
    [projectId],
  )

  return { viewMode, setViewMode }
}
