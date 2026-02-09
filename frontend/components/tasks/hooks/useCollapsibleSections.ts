'use client'

import { useCallback, useState } from 'react'

interface UseCollapsibleSectionsReturn {
  descriptionOpen: boolean
  subtasksOpen: boolean
  timelineOpen: boolean
  agentTimelineOpen: boolean
  setDescriptionOpen: (open: boolean) => void
  setSubtasksOpen: (open: boolean) => void
  setTimelineOpen: (open: boolean) => void
  setAgentTimelineOpen: (open: boolean) => void
  resetCollapsibleState: () => void
}

export function useCollapsibleSections(): UseCollapsibleSectionsReturn {
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const [subtasksOpen, setSubtasksOpen] = useState(false)
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [agentTimelineOpen, setAgentTimelineOpen] = useState(false)

  const resetCollapsibleState = useCallback(() => {
    setDescriptionOpen(false)
    setSubtasksOpen(false)
    setTimelineOpen(false)
    setAgentTimelineOpen(false)
  }, [])

  return {
    descriptionOpen,
    subtasksOpen,
    timelineOpen,
    agentTimelineOpen,
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    setAgentTimelineOpen,
    resetCollapsibleState,
  }
}
