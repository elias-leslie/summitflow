'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import Link from 'next/link'
import { useRef } from 'react'
import { fetchProject, fetchProjects } from '@/lib/api'
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
    staleTime: 60000,
  })

  if (isCollapsed) {
    // Show mini project icons when collapsed
    return (
      <div className="space-y-1 py-2">
        {projects?.slice(0, 5).map((p) => (
          <Link
            key={p.id}
            href={`/projects/${p.id}`}
            className={clsx(
              'flex items-center justify-center w-10 h-10 mx-auto rounded-lg transition-all duration-200',
              p.id === currentProjectId
                ? 'bg-outrun-500/20 text-outrun-400 shadow-[0_0_12px_rgba(255,0,102,0.2)]'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
            )}
            title={p.name}
          >
            <span className="text-xs font-bold">
              {p.name.charAt(0).toUpperCase()}
            </span>
          </Link>
        ))}
        {projects && projects.length > 5 && (
          <div className="flex items-center justify-center w-10 h-10 mx-auto text-xs text-slate-600">
            +{projects.length - 5}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      ref={accordionRef}
      className="space-y-1"
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
