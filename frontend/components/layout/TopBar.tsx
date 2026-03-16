'use client'

import { useParams, usePathname } from 'next/navigation'
import { useMemo, useState } from 'react'
import { NotificationBell } from '@/components/notifications'
import { DEFAULT_PROJECT_ID, getProjectIdOrDefault } from '@/lib/project-config'

import { AnimatedLogo } from './topbar/AnimatedLogo'
import { Navigation } from './topbar/Navigation'
import { TaskSearch } from './topbar/TaskSearch'
import { useAdaptiveNavigation } from './topbar/useAdaptiveNavigation'

export function TopBar() {
  const pathname = usePathname()
  const params = useParams<{ id?: string }>()
  const [isSearchExpanded, setIsSearchExpanded] = useState(false)
  const { compact, measureRef, slotRef } =
    useAdaptiveNavigation(isSearchExpanded)
  const notificationProjectId = useMemo(() => {
    if (pathname?.startsWith('/projects/')) {
      return getProjectIdOrDefault(params.id)
    }

    return DEFAULT_PROJECT_ID
  }, [params.id, pathname])

  return (
    <>
      <header className="h-16 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-4">
        <AnimatedLogo />
        <div
          ref={slotRef}
          className="relative flex min-w-0 flex-1 items-center"
        >
          <div
            ref={measureRef}
            aria-hidden="true"
            className="pointer-events-none absolute left-0 top-0 -z-10 invisible overflow-visible whitespace-nowrap"
          >
            <Navigation dense={isSearchExpanded} measure />
          </div>
          <Navigation compact={compact} dense={isSearchExpanded} />
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <TaskSearch onExpandedChange={setIsSearchExpanded} />
          <NotificationBell projectId={notificationProjectId} />
        </div>
      </header>
      <div className="chrome-line" />
    </>
  )
}
