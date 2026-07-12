'use client'

import { NotesButton, NotesProvider } from '@summitflow/notes-ui'
import { Menu } from 'lucide-react'
import { useParams, usePathname } from 'next/navigation'
import { useMemo, useRef, useState } from 'react'
import { NotificationBell } from '@/components/notifications'
import { DEFAULT_PROJECT_ID, getProjectIdOrDefault } from '@/lib/project-config'

import { MobileNavigationSheet } from './MobileNavigationSheet'
import { AnimatedLogo } from './topbar/AnimatedLogo'
import { DatabaseWorkbenchButton } from './topbar/DatabaseWorkbenchButton'
import { Navigation } from './topbar/Navigation'
import { TaskSearch } from './topbar/TaskSearch'
import { useAdaptiveNavigation } from './topbar/useAdaptiveNavigation'
import { WorkspaceFilesButton } from './topbar/WorkspaceFilesButton'

export function TopBar() {
  const pathname = usePathname()
  const params = useParams<{ id?: string }>()
  const [isSearchExpanded, setIsSearchExpanded] = useState(false)
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
  const mobileNavigationTriggerRef = useRef<HTMLButtonElement>(null)
  const { compact, measureRef, slotRef } =
    useAdaptiveNavigation(isSearchExpanded)

  const notificationProjectId = useMemo(() => {
    if (pathname?.startsWith('/projects/')) {
      return getProjectIdOrDefault(params.id)
    }
    return DEFAULT_PROJECT_ID
  }, [params.id, pathname])

  const setMobileNavigation = (open: boolean) => {
    setMobileNavigationOpen(open)
    if (!open) {
      requestAnimationFrame(() => mobileNavigationTriggerRef.current?.focus())
    }
  }

  return (
    <>
      <header className="relative z-40 flex-shrink-0 border-b border-slate-700/60 bg-slate-950/88 backdrop-blur-md">
        <div className="relative flex h-[64px] items-center gap-3 px-3 sm:px-4 lg:h-[68px] lg:px-5">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.015),transparent)] opacity-60" />
          <div className="relative z-10 flex min-w-0 flex-1 items-center gap-3">
            <div className="flex shrink-0 items-center rounded-[1.15rem] border border-slate-700/60 bg-slate-900/84 px-2.5 py-1.5 shadow-[0_14px_32px_-26px_rgba(0,0,0,0.92)]">
              <AnimatedLogo />
            </div>
            <div
              ref={slotRef}
              className="relative flex min-w-0 flex-1 items-center"
            >
              <button
                ref={mobileNavigationTriggerRef}
                type="button"
                onClick={() => setMobileNavigation(true)}
                aria-label="Open navigation"
                aria-expanded={mobileNavigationOpen}
                aria-controls="mobile-navigation"
                className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-slate-700/60 bg-slate-900/82 text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-colors hover:border-slate-600 hover:bg-slate-800/80 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outrun-500/40 md:hidden"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="relative hidden min-w-0 flex-1 items-center md:flex">
                <div
                  ref={measureRef}
                  aria-hidden="true"
                  className="pointer-events-none absolute left-0 top-0 -z-10 invisible overflow-visible whitespace-nowrap"
                >
                  <Navigation dense={isSearchExpanded} measure />
                </div>
                <div className="relative flex min-w-0 flex-1 rounded-full border border-slate-700/60 bg-slate-900/82 px-1.5 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_14px_30px_-24px_rgba(0,0,0,0.9)]">
                  <Navigation compact={compact} dense={isSearchExpanded} />
                </div>
              </div>
            </div>
          </div>
          <div className="relative z-10 flex flex-shrink-0 items-center gap-1.5 rounded-[1.15rem] border border-slate-700/60 bg-slate-900/84 px-1.5 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_14px_30px_-24px_rgba(0,0,0,0.9)]">
            <TaskSearch onExpandedChange={setIsSearchExpanded} />
            <WorkspaceFilesButton />
            <DatabaseWorkbenchButton />
            <div className="topbar-button p-1">
              <NotesProvider apiPrefix="/api" projectScope="summitflow">
                <NotesButton />
              </NotesProvider>
            </div>
            <div className="topbar-button p-1">
              <NotificationBell projectId={notificationProjectId} />
            </div>
          </div>
        </div>
      </header>
      <div className="chrome-line" />
      <MobileNavigationSheet
        open={mobileNavigationOpen}
        onOpenChange={setMobileNavigation}
      />
    </>
  )
}
