'use client'

import { Info, MessageSquare } from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname } from 'next/navigation'
import { useMemo } from 'react'
import { NotificationBell } from '@/components/notifications'
import { usePersonaName } from '@/hooks/usePersonaName'
import { DEFAULT_PROJECT_ID, getProjectIdOrDefault } from '@/lib/project-config'

import { AnimatedLogo } from './topbar/AnimatedLogo'
import { Navigation } from './topbar/Navigation'
import { TaskSearch } from './topbar/TaskSearch'

export function TopBar() {
  const pathname = usePathname()
  const params = useParams<{ id?: string }>()
  const personaName = usePersonaName()
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
          <Link
            href="/chat"
            className="lg:hidden p-2.5 rounded-lg text-phosphor-400 hover:bg-phosphor-500/10 hover:text-phosphor-300 transition-all duration-200"
            title={personaName}
          >
            <MessageSquare className="w-5 h-5" />
          </Link>
          <Link
            href="/about"
            data-testid="topbar-about"
            className="p-2.5 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="About SummitFlow"
          >
            <Info className="w-5 h-5" />
          </Link>
          <NotificationBell projectId={notificationProjectId} />
        </div>
      </header>
      <div className="chrome-line" />
    </>
  )
}
