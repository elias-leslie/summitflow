import {
  PROJECT_CATEGORY_ORDER,
  type Project,
  type ProjectCategory,
} from '@/lib/api'

type SidebarProjectLike = Pick<Project, 'id' | 'name' | 'category' | 'sidebar_rank'>

function getCategoryIndex(category: ProjectCategory): number {
  return PROJECT_CATEGORY_ORDER.indexOf(category)
}

export function compareProjectsForSidebar(
  a: SidebarProjectLike,
  b: SidebarProjectLike,
): number {
  const categoryDiff = getCategoryIndex(a.category) - getCategoryIndex(b.category)
  if (categoryDiff !== 0) return categoryDiff

  const aHasRank = a.sidebar_rank != null
  const bHasRank = b.sidebar_rank != null
  if (aHasRank !== bHasRank) return aHasRank ? -1 : 1

  if (a.sidebar_rank != null && b.sidebar_rank != null) {
    const rankDiff = a.sidebar_rank - b.sidebar_rank
    if (rankDiff !== 0) return rankDiff
  }

  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
}

export function sortProjectsForSidebar<T extends SidebarProjectLike>(projects: T[]): T[] {
  return [...projects].sort(compareProjectsForSidebar)
}

export function groupProjectsForSidebar<T extends SidebarProjectLike>(
  projects: T[],
): Record<ProjectCategory, T[]> {
  const grouped: Record<ProjectCategory, T[]> = {
    production: [],
    testing: [],
    dev: [],
  }

  for (const project of sortProjectsForSidebar(projects)) {
    grouped[project.category].push(project)
  }

  return grouped
}

function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  const next = [...items]
  const [item] = next.splice(fromIndex, 1)
  if (item === undefined) return items
  next.splice(toIndex, 0, item)
  return next
}

export function reorderProjectsWithinCategory<T extends SidebarProjectLike>(
  projects: T[],
  category: ProjectCategory,
  activeId: string,
  overId: string,
): { projects: T[]; updates: Array<{ id: string; sidebar_rank: number }> } | null {
  const grouped = groupProjectsForSidebar(projects)
  const categoryProjects = grouped[category]
  const activeIndex = categoryProjects.findIndex((project) => project.id === activeId)
  const overIndex = categoryProjects.findIndex((project) => project.id === overId)

  if (activeIndex < 0 || overIndex < 0 || activeIndex === overIndex) {
    return null
  }

  const reordered = moveItem(categoryProjects, activeIndex, overIndex)
  const updates = reordered.map((project, index) => ({
    id: project.id,
    sidebar_rank: index,
  }))
  const sidebarRankById = new Map(updates.map((update) => [update.id, update.sidebar_rank]))
  const nextProjects = projects.map((project) => {
    const sidebarRank = sidebarRankById.get(project.id)
    return sidebarRank == null
      ? project
      : { ...project, sidebar_rank: sidebarRank }
  })

  return {
    projects: sortProjectsForSidebar(nextProjects),
    updates,
  }
}
