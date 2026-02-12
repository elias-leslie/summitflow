import { useCallback, useEffect, useState } from 'react'

type TabId = 'tasks' | 'explorer' | 'health'
export type ExplorerType =
  | 'files'
  | 'database'
  | 'celery'
  | 'api'
  | 'pages'
  | 'dependencies'
  | 'architecture'

const VALID_TABS: TabId[] = ['tasks', 'explorer', 'health']
const VALID_EXPLORER_TYPES: ExplorerType[] = [
  'files',
  'database',
  'celery',
  'api',
  'pages',
  'dependencies',
  'architecture',
]

const getLastTabKey = (projectId: string) => `summitflow_last_tab_${projectId}`
const getExplorerTypeKey = (projectId: string) =>
  `${getLastTabKey(projectId)}_explorer_type`

interface UseTabPersistenceOptions {
  projectId: string
  urlTab: TabId | null
  urlExplorerType: ExplorerType | null
}

interface UseTabPersistenceReturn {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void
  explorerType: ExplorerType
  setExplorerType: (type: ExplorerType) => void
  hasRestoredTab: boolean
}

export function useTabPersistence({
  projectId,
  urlTab,
  urlExplorerType,
}: UseTabPersistenceOptions): UseTabPersistenceReturn {
  const [activeTab, setActiveTabInternal] = useState<TabId>(urlTab || 'tasks')
  const [hasRestoredTab, setHasRestoredTab] = useState(false)

  // Initialize explorer type from URL or default
  const [explorerType, setExplorerTypeInternal] = useState<ExplorerType>(
    urlExplorerType && VALID_EXPLORER_TYPES.includes(urlExplorerType)
      ? urlExplorerType
      : 'files',
  )

  // Restore last tab from localStorage on mount (if no URL tab specified)
  useEffect(() => {
    if (!urlTab && !hasRestoredTab) {
      const lastTab = localStorage.getItem(
        getLastTabKey(projectId),
      ) as TabId | null
      if (lastTab && VALID_TABS.includes(lastTab)) {
        setActiveTabInternal(lastTab)
        // Also restore explorer type if it was the explorer tab
        if (lastTab === 'explorer') {
          const lastType = localStorage.getItem(
            getExplorerTypeKey(projectId),
          ) as ExplorerType | null
          if (lastType && VALID_EXPLORER_TYPES.includes(lastType)) {
            setExplorerTypeInternal(lastType)
          }
        }
      }
      setHasRestoredTab(true)
    }
  }, [projectId, urlTab, hasRestoredTab])

  // Sync with URL changes
  useEffect(() => {
    if (urlTab && VALID_TABS.includes(urlTab)) {
      setActiveTabInternal(urlTab)
    }
    // Sync explorer type from URL
    if (urlExplorerType && VALID_EXPLORER_TYPES.includes(urlExplorerType)) {
      setExplorerTypeInternal(urlExplorerType)
    }
  }, [urlTab, urlExplorerType])

  // Save active tab to localStorage whenever it changes
  useEffect(() => {
    if (hasRestoredTab) {
      localStorage.setItem(getLastTabKey(projectId), activeTab)
      // Also save explorer type if on explorer tab
      if (activeTab === 'explorer') {
        localStorage.setItem(getExplorerTypeKey(projectId), explorerType)
      }
    }
  }, [activeTab, explorerType, projectId, hasRestoredTab])

  // Wrapped setters that also persist
  const setActiveTab = useCallback((tab: TabId) => {
    setActiveTabInternal(tab)
  }, [])

  const setExplorerType = useCallback((type: ExplorerType) => {
    setExplorerTypeInternal(type)
  }, [])

  return {
    activeTab,
    setActiveTab,
    explorerType,
    setExplorerType,
    hasRestoredTab,
  }
}

// Re-export types for convenience
export type { TabId }
export { VALID_TABS, VALID_EXPLORER_TYPES }
