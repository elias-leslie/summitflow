'use client'

import { useCallback, useEffect, useState } from 'react'
import type {
  ContextItem,
  ExpandedContent,
} from '@/components/memory/ContextItemCard'

// Context index types
export interface ContextIndex {
  project_id: string
  session_id: string | null
  items: ContextItem[]
  item_count: number
  index_tokens: number
  full_tokens: number
  reduction_pct: number
  from_cache: boolean
  instructions: string
}

export interface UseContextPanelOptions {
  projectId: string
  sessionId?: string
  activeTab: 'stream' | 'context'
}

export interface UseContextPanelReturn {
  contextIndex: ContextIndex | null
  contextLoading: boolean
  contextError: string | null
  expandedContextIds: Set<string>
  expandedContents: Map<string, ExpandedContent>
  expandingIds: Set<string>
  loadContextIndex: () => Promise<void>
  expandContextItem: (entityId: string) => Promise<void>
}

export function useContextPanel({
  projectId,
  sessionId,
  activeTab,
}: UseContextPanelOptions): UseContextPanelReturn {
  const [contextIndex, setContextIndex] = useState<ContextIndex | null>(null)
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)
  const [expandedContextIds, setExpandedContextIds] = useState<Set<string>>(
    new Set(),
  )
  const [expandedContents, setExpandedContents] = useState<
    Map<string, ExpandedContent>
  >(new Map())
  const [expandingIds, setExpandingIds] = useState<Set<string>>(new Set())

  const loadContextIndex = useCallback(async () => {
    setContextLoading(true)
    setContextError(null)

    try {
      const params = new URLSearchParams()
      if (sessionId) {
        params.set('session_id', sessionId)
      }

      const response = await fetch(
        `/api/projects/${projectId}/context/index?${params}`,
      )

      if (!response.ok) {
        throw new Error(`Failed to load context: ${response.status}`)
      }

      const data = await response.json()
      setContextIndex(data)
    } catch (err) {
      setContextError(
        err instanceof Error ? err.message : 'Failed to load context',
      )
    } finally {
      setContextLoading(false)
    }
  }, [projectId, sessionId])

  // Load context when switching to Context tab
  useEffect(() => {
    if (activeTab === 'context' && !contextIndex && !contextLoading) {
      loadContextIndex()
    }
  }, [activeTab, contextIndex, contextLoading, loadContextIndex])

  const expandContextItem = useCallback(
    async (entityId: string) => {
      // Toggle if already expanded
      if (expandedContextIds.has(entityId)) {
        setExpandedContextIds((prev) => {
          const next = new Set(prev)
          next.delete(entityId)
          return next
        })
        return
      }

      // Check if already have the content
      if (expandedContents.has(entityId)) {
        setExpandedContextIds((prev) => new Set(prev).add(entityId))
        return
      }

      // Fetch the content
      setExpandingIds((prev) => new Set(prev).add(entityId))

      try {
        const response = await fetch(
          `/api/projects/${projectId}/context/expand`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_id: entityId }),
          },
        )

        if (!response.ok) {
          throw new Error(`Failed to expand: ${response.status}`)
        }

        const data = await response.json()
        setExpandedContents((prev) => new Map(prev).set(entityId, data))
        setExpandedContextIds((prev) => new Set(prev).add(entityId))
      } catch (err) {
        console.error('Failed to expand context item:', err)
      } finally {
        setExpandingIds((prev) => {
          const next = new Set(prev)
          next.delete(entityId)
          return next
        })
      }
    },
    [projectId, expandedContextIds, expandedContents],
  )

  return {
    contextIndex,
    contextLoading,
    contextError,
    expandedContextIds,
    expandedContents,
    expandingIds,
    loadContextIndex,
    expandContextItem,
  }
}
