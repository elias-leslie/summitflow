'use client'

import { useParams, usePathname } from 'next/navigation'
import { useMemo } from 'react'
import { NotificationBell } from '@/components/notifications'
import { DEFAULT_PROJECT_ID, getProjectIdOrDefault } from '@/lib/project-config'

import { AnimatedLogo } from './topbar/AnimatedLogo'
import { Navigation } from './topbar/Navigation'
import { TaskSearch } from './topbar/TaskSearch'

export function TopBar() {
  const pathname = usePathname()
  const params = useParams<{ id?: string }>()
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
        <Navigation />
        <div className="flex-1" />
        <TaskSearch />
        <div className="flex items-center gap-1 flex-shrink-0">
          <NotificationBell projectId={notificationProjectId} />
        </div>
      </header>
      <div className="chrome-line" />
    </>
  )
}
