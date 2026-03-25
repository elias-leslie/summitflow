'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import Link from 'next/link'
import { useRef } from 'react'
import { fetchProject, fetchProjects } from '@/lib/api'
import { POLL_SLOW } from '@/lib/polling'
import { useProjectNavigation } from './hooks/useProjectNavigation'
import { ProjectAccordionItem } from './ProjectAccordionItem'

interface ProjectsAccordionProps {
  isCollapsed: boolean
  expandedProjectId: string | null
  onExpandProject: (projectId: string | null) => void
}

export function ProjectsAccordion({
  isCollapsed,
  expandedProjectId,
  onExpandProject,
}: ProjectsAccordionProps) {
  const accordionRef = useRef<HTMLDivElement>(null)
  const { currentProjectId, activeTab, getProjectNavHref } = useProjectNavigation()

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  // Prefetch expanded project data for health indicators
  useQuery({
    queryKey: ['project', expandedProjectId],
    queryFn: () => fetchProject(expandedProjectId!),
    enabled: !!expandedProjectId,
    staleTime: POLL_SLOW,
  })

  if (isCollapsed) {
    // Show mini project icons when collapsed
    return (
      <div className="space-y-2 py-2">
        {projects?.slice(0, 5).map((p) => (
          <Link
            key={p.id}
            href={`/projects/${p.id}`}
            className={clsx(
              'mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border transition-all duration-200',
              p.id === currentProjectId
                ? 'border-outrun-500/30 bg-outrun-500/18 text-outrun-300 shadow-[0_18px_36px_-30px_rgba(255,0,102,0.95)]'
                : 'border-slate-800/60 bg-slate-900/55 text-slate-500 hover:border-slate-700/60 hover:bg-slate-800/70 hover:text-slate-300',
            )}
            title={p.name}
          >
            <span className="text-xs font-bold">
              {p.name.charAt(0).toUpperCase()}
            </span>
          </Link>
        ))}
        {projects && projects.length > 5 && (
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-800/60 bg-slate-900/55 text-xs text-slate-500">
            +{projects.length - 5}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      ref={accordionRef}
      className="space-y-2"
      data-testid="projects-accordion"
    >
      {projects?.map((p) => {
        const isExpanded = expandedProjectId === p.id
        const isActive = currentProjectId === p.id

        return (
          <ProjectAccordionItem
            key={p.id}
            project={p}
            isExpanded={isExpanded}
            isActive={isActive}
            activeTab={activeTab}
            onToggleExpand={() => onExpandProject(isExpanded ? null : p.id)}
            getProjectNavHref={getProjectNavHref}
          />
        )
      })}
    </div>
  )
}
