import { usePathname, useSearchParams } from 'next/navigation'
import { getProjectIdFromPathname } from '@/lib/project-config'
import { parseProjectTab } from '@/lib/project-tabs'
import type { NavItemConfig, NavItemId } from '../types'

interface UseProjectNavigationReturn {
  currentProjectId: string | null
  activeTab: NavItemId | null
  getProjectNavHref: (projectId: string, item: NavItemConfig) => string
}

export function useProjectNavigation(): UseProjectNavigationReturn {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const currentProjectId = getProjectIdFromPathname(pathname)

  const getActiveTab = (): NavItemId | null => {
    if (!currentProjectId) return null
    if (pathname.includes('/files')) return 'files'
    if (pathname.includes('/design')) return 'design'
    if (pathname.includes('/graph')) return 'graph'
    return parseProjectTab(searchParams.get('tab'))
  }

  const getProjectNavHref = (projectId: string, item: NavItemConfig) => {
    if (item.href) {
      return `/projects/${projectId}${item.href}`
    }
    return `/projects/${projectId}?tab=${item.id}`
  }

  return {
    currentProjectId,
    activeTab: getActiveTab(),
    getProjectNavHref,
  }
}
