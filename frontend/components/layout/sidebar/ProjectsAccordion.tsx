'use client'

import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  verticalListSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import Link from 'next/link'
import { useRef } from 'react'
import {
  fetchProject,
  fetchProjects,
  PROJECT_CATEGORY_LABELS,
  PROJECT_CATEGORY_ORDER,
  type Project,
  updateProject,
} from '@/lib/api'
import { POLL_SLOW } from '@/lib/polling'
import { useProjectNavigation } from './hooks/useProjectNavigation'
import { groupProjectsForSidebar, reorderProjectsWithinCategory, sortProjectsForSidebar } from './projectOrdering'
import { SortableProjectAccordionItem } from './SortableProjectAccordionItem'

interface ProjectsAccordionProps {
  isCollapsed: boolean
  expandedProjectId: string | null
  onExpandProject: (projectId: string | null) => void
}

interface ReorderProjectsPayload {
  projects: Project[]
  updates: Array<{ id: string; sidebar_rank: number }>
}

export function ProjectsAccordion({
  isCollapsed,
  expandedProjectId,
  onExpandProject,
}: ProjectsAccordionProps) {
  const accordionRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { currentProjectId, activeTab, getProjectNavHref } = useProjectNavigation()

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })
  const orderedProjects = sortProjectsForSidebar(projects ?? [])
  const groupedProjects = groupProjectsForSidebar(orderedProjects)
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  const reorderMutation = useMutation({
    mutationFn: async ({ updates }: ReorderProjectsPayload) => Promise.all(
      updates.map((update) => updateProject(update.id, { sidebar_rank: update.sidebar_rank })),
    ),
    onMutate: async ({ projects: nextProjects }: ReorderProjectsPayload) => {
      await queryClient.cancelQueries({ queryKey: ['projects'] })
      const previousProjects = queryClient.getQueryData<Project[]>(['projects'])
      queryClient.setQueryData(['projects'], nextProjects)
      return { previousProjects }
    },
    onError: (_error, _variables, context) => {
      if (context?.previousProjects) {
        queryClient.setQueryData(['projects'], context.previousProjects)
      }
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['projects-with-stats'] }),
      ])
    },
  })

  // Prefetch expanded project data for health indicators
  useQuery({
    queryKey: ['project', expandedProjectId],
    queryFn: () => fetchProject(expandedProjectId!),
    enabled: !!expandedProjectId,
    staleTime: POLL_SLOW,
  })

  const handleDragEnd = (event: DragEndEvent) => {
    if (reorderMutation.isPending) return

    const activeId = String(event.active.id)
    const overId = event.over ? String(event.over.id) : null

    if (!overId || activeId === overId) return

    const activeProject = orderedProjects.find((project) => project.id === activeId)
    const overProject = orderedProjects.find((project) => project.id === overId)

    if (!activeProject || !overProject || activeProject.category !== overProject.category) {
      return
    }

    const reorderResult = reorderProjectsWithinCategory(
      orderedProjects,
      activeProject.category,
      activeId,
      overId,
    )

    if (!reorderResult) return

    reorderMutation.mutate(reorderResult)
  }

  if (isCollapsed) {
    return (
      <div className="space-y-2 py-2">
        {orderedProjects.slice(0, 5).map((project) => (
          <Link
            key={project.id}
            href={`/projects/${project.id}`}
            className={clsx(
              'mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border transition-all duration-200',
              project.id === currentProjectId
                ? 'border-outrun-500/30 bg-outrun-500/18 text-outrun-300 shadow-[0_18px_36px_-30px_rgba(255,0,102,0.95)]'
                : 'border-slate-800/60 bg-slate-900/55 text-slate-500 hover:border-slate-700/60 hover:bg-slate-800/70 hover:text-slate-300',
            )}
            title={project.name}
          >
            <span className="text-xs font-bold">
              {project.name.charAt(0).toUpperCase()}
            </span>
          </Link>
        ))}
        {orderedProjects.length > 5 && (
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-800/60 bg-slate-900/55 text-xs text-slate-500">
            +{orderedProjects.length - 5}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      ref={accordionRef}
      className="space-y-4"
      data-testid="projects-accordion"
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        {PROJECT_CATEGORY_ORDER.map((category) => {
          const categoryProjects = groupedProjects[category]
          if (categoryProjects.length === 0) return null

          return (
            <section key={category} className="space-y-2">
              <div className="flex items-center justify-between px-1">
                <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                  {PROJECT_CATEGORY_LABELS[category]}
                </div>
                <div className="flex items-center gap-2">
                  {reorderMutation.isPending ? (
                    <span className="text-[10px] text-slate-500">Saving order...</span>
                  ) : null}
                  <span className="rounded-full border border-slate-800/70 bg-slate-950/60 px-1.5 py-0.5 text-[10px] text-slate-500">
                    {categoryProjects.length}
                  </span>
                </div>
              </div>
              <SortableContext
                items={categoryProjects.map((project) => project.id)}
                strategy={verticalListSortingStrategy}
              >
                <div className="space-y-2">
                  {categoryProjects.map((project) => {
                    const isExpanded = expandedProjectId === project.id
                    const isActive = currentProjectId === project.id

                    return (
                      <SortableProjectAccordionItem
                        key={project.id}
                        project={project}
                        isExpanded={isExpanded}
                        isActive={isActive}
                        activeTab={activeTab}
                        onToggleExpand={() => onExpandProject(isExpanded ? null : project.id)}
                        getProjectNavHref={getProjectNavHref}
                        dragDisabled={reorderMutation.isPending}
                      />
                    )
                  })}
                </div>
              </SortableContext>
            </section>
          )
        })}
      </DndContext>
    </div>
  )
}
