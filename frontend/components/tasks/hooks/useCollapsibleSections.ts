'use client'

import { useCallback, useState } from 'react'

interface UseCollapsibleSectionsReturn {
  subtasksOpen: boolean
  setSubtasksOpen: (open: boolean) => void
  resetCollapsibleState: () => void
}

export function useCollapsibleSections(): UseCollapsibleSectionsReturn {
  const [subtasksOpen, setSubtasksOpen] = useState(false)

  const resetCollapsibleState = useCallback(() => {
    setSubtasksOpen(false)
  }, [])

  return {
    subtasksOpen,
    setSubtasksOpen,
    resetCollapsibleState,
  }
}
