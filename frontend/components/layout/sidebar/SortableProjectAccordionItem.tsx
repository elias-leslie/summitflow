'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import type { Project } from '@/lib/api'
import type { projectNavItems } from './constants'
import { ProjectAccordionItem } from './ProjectAccordionItem'
import type { NavItemId } from './types'

interface SortableProjectAccordionItemProps {
  project: Project
  isExpanded: boolean
  isActive: boolean
  activeTab: NavItemId | null
  onToggleExpand: () => void
  getProjectNavHref: (
    projectId: string,
    item: (typeof projectNavItems)[number],
  ) => string
  dragDisabled?: boolean
}

export function SortableProjectAccordionItem({
  project,
  isExpanded,
  isActive,
  activeTab,
  onToggleExpand,
  getProjectNavHref,
  dragDisabled = false,
}: SortableProjectAccordionItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: project.id,
    disabled: dragDisabled,
  })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }
  const dragHandleProps = dragDisabled
    ? undefined
    : { ...attributes, ...listeners }

  return (
    <div ref={setNodeRef} style={style} className={clsx(isDragging && 'z-10')}>
      <ProjectAccordionItem
        project={project}
        isExpanded={isExpanded}
        isActive={isActive}
        activeTab={activeTab}
        onToggleExpand={onToggleExpand}
        getProjectNavHref={getProjectNavHref}
        dragHandleProps={dragHandleProps}
        isDragging={isDragging}
      />
    </div>
  )
}
