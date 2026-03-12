'use client'

import clsx from 'clsx'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useState, useEffect } from 'react'
import { useSidebarState } from './hooks/useSidebarState'
import { SidebarHeader } from './SidebarHeader'
import { ProjectsAccordion } from './ProjectsAccordion'

export function SidebarContent() {
  const pathname = usePathname()
  const { isCollapsed, mounted, toggleCollapsed } = useSidebarState()
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null)

  // Extract current project ID from URL
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const currentProjectId = projectMatch ? projectMatch[1] : null

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
          'h-full bg-slate-900/50 border-r border-slate-700/50 flex-col',
          'w-16',
          'hidden md:flex',
        )}
      />
    )
  }

  return (
    <nav
      className={clsx(
        'h-full bg-slate-900/50 border-r border-slate-700/50 flex flex-col transition-all duration-300',
        isCollapsed ? 'w-16' : 'w-56',
        'hidden md:flex',
      )}
    >
      {/* Header */}
      <div
        className={clsx('border-b border-slate-700/50', isCollapsed && 'px-1')}
      >
        <SidebarHeader isCollapsed={isCollapsed} />
      </div>

      {/* Projects List */}
      <div className="flex-1 overflow-y-auto py-3 px-2">
        <ProjectsAccordion
          isCollapsed={isCollapsed}
          expandedProjectId={expandedProjectId}
          onExpandProject={setExpandedProjectId}
        />
      </div>

      {/* Collapse Toggle */}
      <div className="p-2 border-t border-slate-700/50">
        <button
          type="button"
          onClick={toggleCollapsed}
          className="w-full flex items-center justify-center p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors"
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
