'use client'

import { useParams, usePathname } from 'next/navigation'
import { useMemo, useState } from 'react'
import { NotificationBell } from '@/components/notifications'
import { NotesButton, NotesProvider } from '@summitflow/notes-ui'
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
      <header className="flex-shrink-0 border-b border-slate-700/60 bg-slate-950/80 backdrop-blur-xl">
        <div className="relative flex h-[72px] items-center gap-4 px-4 sm:px-6">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_0%,rgba(255,0,102,0.12),transparent_30%),radial-gradient(circle_at_82%_0%,rgba(0,245,255,0.08),transparent_26%)] opacity-90" />
          <div className="relative z-10 flex min-w-0 flex-1 items-center gap-4">
            <div className="flex shrink-0 items-center rounded-[1.35rem] border border-slate-700/60 bg-slate-900/72 px-3 py-2 shadow-[0_18px_44px_-34px_rgba(0,0,0,0.95)]">
              <AnimatedLogo />
            </div>
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
              <div className="relative flex min-w-0 flex-1 rounded-full border border-slate-700/60 bg-slate-900/68 px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_18px_40px_-34px_rgba(0,0,0,0.95)]">
                <Navigation compact={compact} dense={isSearchExpanded} />
              </div>
            </div>
          </div>
          <div className="relative z-10 flex flex-shrink-0 items-center gap-2 rounded-[1.35rem] border border-slate-700/60 bg-slate-900/72 px-2 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_18px_40px_-34px_rgba(0,0,0,0.95)]">
            <TaskSearch onExpandedChange={setIsSearchExpanded} />
            <div className="h-6 w-px bg-slate-800/80" />
            <div className="topbar-button p-1.5">
              <NotesProvider apiPrefix="/api" projectScope="summitflow">
                <NotesButton />
              </NotesProvider>
            </div>
            <div className="topbar-button p-1.5">
              <NotificationBell projectId={notificationProjectId} />
            </div>
          </div>
        </div>
      </header>
      <div className="chrome-line" />
    </>
  )
}
