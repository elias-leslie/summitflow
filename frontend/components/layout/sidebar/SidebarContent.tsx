'use client'

import clsx from 'clsx'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useState, useEffect } from 'react'
import { getProjectIdFromPathname } from '@/lib/project-config'
import { useSidebarState } from './hooks/useSidebarState'
import { SidebarHeader } from './SidebarHeader'
import { ProjectsAccordion } from './ProjectsAccordion'

export function SidebarContent() {
  const pathname = usePathname()
  const { isCollapsed, mounted, toggleCollapsed } = useSidebarState()
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null)

  const currentProjectId = getProjectIdFromPathname(pathname)

  // Auto-expand current project
  useEffect(() => {
    if (!mounted) return

    if (currentProjectId) {
      setExpandedProjectId(currentProjectId)
    }
  }, [currentProjectId, mounted])

  // Loading state
  if (!mounted) {
    return (
      <nav
        className={clsx(
          'hidden h-full flex-col border-r border-slate-700/60 bg-[linear-gradient(180deg,rgba(9,6,16,0.96),rgba(10,7,18,0.92)_40%,rgba(8,5,14,0.97))]',
          'w-[80px]',
          'hidden md:flex',
        )}
      />
    )
  }

  return (
    <nav
      className={clsx(
        'relative hidden h-full flex-col border-r border-slate-700/60 bg-[linear-gradient(180deg,rgba(9,6,16,0.96),rgba(10,7,18,0.92)_40%,rgba(8,5,14,0.97))] shadow-[inset_-1px_0_0_rgba(255,255,255,0.02)] transition-all duration-300 md:flex',
        isCollapsed ? 'w-[80px] lg:w-[84px]' : 'w-[248px] xl:w-[280px]',
        'hidden md:flex',
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top,rgba(255,0,102,0.1),transparent_70%)] opacity-65" />

      {/* Header */}
      <div
        className={clsx('border-b border-slate-700/60 px-2 pt-2', isCollapsed && 'px-2')}
      >
        <SidebarHeader isCollapsed={isCollapsed} />
      </div>

      {/* Projects List */}
      <div className="flex-1 overflow-y-auto px-2.5 py-3">
        <ProjectsAccordion
          isCollapsed={isCollapsed}
          expandedProjectId={expandedProjectId}
          onExpandProject={setExpandedProjectId}
        />
      </div>

      {/* Collapse Toggle */}
      <div className="border-t border-slate-700/60 p-2.5">
        <button
          type="button"
          onClick={toggleCollapsed}
          className="flex w-full items-center justify-center rounded-2xl border border-slate-700/60 bg-slate-900/70 px-3 py-2 text-slate-500 transition-all hover:border-slate-600 hover:bg-slate-800/78 hover:text-slate-200"
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {isCollapsed ? (
            <ChevronRight className="w-5 h-5" />
          ) : (
            <ChevronLeft className="w-5 h-5" />
          )}
        </button>
      </div>
    </nav>
  )
}
