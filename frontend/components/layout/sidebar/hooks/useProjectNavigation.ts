import { usePathname, useSearchParams } from 'next/navigation'
import type { NavItemConfig, NavItemId } from '../types'

interface UseProjectNavigationReturn {
  currentProjectId: string | null
  activeTab: NavItemId | null
  getProjectNavHref: (projectId: string, item: NavItemConfig) => string
}

export function useProjectNavigation(): UseProjectNavigationReturn {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const currentProjectId = projectMatch ? projectMatch[1] : null

  const getActiveTab = (): NavItemId | null => {
    if (!currentProjectId) return null
    if (pathname.includes('/settings')) return 'settings' as NavItemId
    if (pathname.includes('/git')) return 'git' as NavItemId
    if (pathname.includes('/backups')) return 'backups' as NavItemId
    if (pathname.includes('/design')) return 'design'
    const tab = searchParams.get('tab') as NavItemId | null
    return tab || 'tasks'
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
