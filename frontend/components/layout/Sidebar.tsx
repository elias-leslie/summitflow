'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Activity,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  FolderKanban,
  Kanban,
  ListTodo,
  Palette,
  Settings2,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useRef, useState } from 'react'
import { fetchProject, fetchProjects } from '@/lib/api'

// =============================================================================
// Types & Constants
// =============================================================================

type NavItemId = 'kanban' | 'tasks' | 'explorer' | 'health' | 'design'

interface NavItemConfig {
  id: NavItemId
  label: string
  href: string
  icon: React.ElementType
  activeClasses: string
  inactiveClasses: string
  iconActiveClasses: string
  iconInactiveClasses: string
}

// Project-specific navigation items (shown when project expanded)
const projectNavItems: NavItemConfig[] = [
  {
    id: 'kanban',
    label: 'Kanban',
    href: '',
    icon: Kanban,
    activeClasses: 'bg-cyan-500/15 text-cyan-400',
    inactiveClasses: 'text-slate-400 hover:bg-cyan-500/10 hover:text-cyan-400',
    iconActiveClasses: 'text-cyan-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-cyan-400',
  },
  {
    id: 'tasks',
    label: 'Tasks',
    href: '',
    icon: ListTodo,
    activeClasses: 'bg-orange-500/15 text-orange-400',
    inactiveClasses:
      'text-slate-400 hover:bg-orange-500/10 hover:text-orange-400',
    iconActiveClasses: 'text-orange-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-orange-400',
  },
  {
    id: 'explorer',
    label: 'Explorer',
    href: '',
    icon: Compass,
    activeClasses: 'bg-teal-500/15 text-teal-400',
    inactiveClasses: 'text-slate-400 hover:bg-teal-500/10 hover:text-teal-400',
    iconActiveClasses: 'text-teal-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-teal-400',
  },
  {
    id: 'health',
    label: 'Health',
    href: '',
    icon: Activity,
    activeClasses: 'bg-purple-500/15 text-purple-400',
    inactiveClasses:
      'text-slate-400 hover:bg-purple-500/10 hover:text-purple-400',
    iconActiveClasses: 'text-purple-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-purple-400',
  },
  {
    id: 'design',
    label: 'Design',
    href: '/design',
    icon: Palette,
    activeClasses: 'bg-fuchsia-500/15 text-fuchsia-400',
    inactiveClasses:
      'text-slate-400 hover:bg-fuchsia-500/10 hover:text-fuchsia-400',
    iconActiveClasses: 'text-fuchsia-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-fuchsia-400',
  },
]

const COLLAPSED_KEY = 'summitflow_sidebar_collapsed'

// =============================================================================
// Sidebar Header Component
// =============================================================================

interface SidebarHeaderProps {
  isCollapsed: boolean
}

function SidebarHeader({ isCollapsed }: SidebarHeaderProps) {
  if (isCollapsed) {
    return (
      <div className="flex items-center justify-center py-3">
        <FolderKanban className="w-5 h-5 text-outrun-400" />
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 px-3 py-3">
      <FolderKanban className="w-5 h-5 text-outrun-400" />
      <span className="text-sm font-semibold tracking-wide uppercase text-slate-300">
        Projects
      </span>
    </div>
  )
}

// =============================================================================
// Projects Accordion Component
// =============================================================================

interface ProjectsAccordionProps {
  isCollapsed: boolean
  expandedProjectId: string | null
  onExpandProject: (projectId: string | null) => void
}

function ProjectsAccordion({
  isCollapsed,
  expandedProjectId,
  onExpandProject,
}: ProjectsAccordionProps) {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const accordionRef = useRef<HTMLDivElement>(null)

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

  // Detect current project from URL
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const currentProjectId = projectMatch ? projectMatch[1] : null

  // Get active tab for current project
  const getActiveTab = (): NavItemId | null => {
    if (!currentProjectId) return null
    if (pathname.includes('/settings')) return 'settings' as NavItemId
    if (pathname.includes('/git')) return 'git' as NavItemId
    if (pathname.includes('/backups')) return 'backups' as NavItemId
    if (pathname.includes('/design')) return 'design'
    const tab = searchParams.get('tab') as NavItemId | null
    return tab || 'kanban'
  }

  const activeTab = getActiveTab()

  // Build href for project nav item
  const getProjectNavHref = (projectId: string, item: NavItemConfig) => {
    if (item.href) {
      return `/projects/${projectId}${item.href}`
    }
    return `/projects/${projectId}?tab=${item.id}`
  }

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
          <div
            key={p.id}
            className="rounded-lg overflow-hidden"
            data-testid="project-accordion-item"
            data-expanded={isExpanded}
          >
            {/* Project header */}
            <button
              onClick={() => onExpandProject(isExpanded ? null : p.id)}
              data-testid={`project-accordion-${p.id}`}
              className={clsx(
                'w-full flex items-center gap-2.5 px-3 py-2.5 transition-all duration-200 group',
                isActive ? 'bg-outrun-500/10' : 'hover:bg-slate-800/50',
              )}
            >
              {/* Project icon with health indicator */}
              <div className="relative flex-shrink-0">
                <div
                  className={clsx(
                    'w-8 h-8 rounded-lg flex items-center justify-center border transition-all duration-200',
                    isActive
                      ? 'bg-gradient-to-br from-outrun-500/20 to-pink-500/10 border-outrun-500/40'
                      : 'bg-slate-800/50 border-slate-700/50 group-hover:border-slate-600',
                  )}
                >
                  <span
                    className={clsx(
                      'text-xs font-bold transition-colors',
                      isActive
                        ? 'text-outrun-400'
                        : 'text-slate-400 group-hover:text-slate-300',
                    )}
                  >
                    {p.name.charAt(0).toUpperCase()}
                  </span>
                </div>
                {/* Health dot */}
                <div
                  className={clsx(
                    'absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-slate-900',
                    p.health_status === 'healthy'
                      ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]'
                      : 'bg-slate-500',
                  )}
                />
              </div>

              {/* Project name */}
              <div className="flex-1 min-w-0 text-left">
                <div
                  className={clsx(
                    'text-sm font-medium truncate transition-colors',
                    isActive
                      ? 'text-white'
                      : 'text-slate-300 group-hover:text-white',
                  )}
                >
                  {p.name}
                </div>
              </div>

              {/* Expand chevron */}
              <ChevronDown
                className={clsx(
                  'w-4 h-4 transition-all duration-250 flex-shrink-0',
                  isExpanded
                    ? 'rotate-180 text-outrun-400'
                    : 'text-slate-500 group-hover:text-slate-400',
                )}
              />
            </button>

            {/* Expanded project nav */}
            <div
              className={clsx(
                'overflow-hidden transition-all duration-250 ease-out',
                isExpanded ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0',
              )}
            >
              <div className="pl-4 pr-2 pb-2 space-y-0.5">
                {projectNavItems.map((item) => {
                  const isItemActive = isActive && activeTab === item.id
                  const Icon = item.icon
                  const href = getProjectNavHref(p.id, item)

                  return (
                    <Link
                      key={item.id}
                      href={href}
                      className={clsx(
                        'group flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200',
                        isItemActive
                          ? item.activeClasses
                          : item.inactiveClasses,
                      )}
                    >
                      <Icon
                        className={clsx(
                          'w-4 h-4 flex-shrink-0 transition-colors duration-200',
                          isItemActive
                            ? item.iconActiveClasses
                            : item.iconInactiveClasses,
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  )
                })}

                {/* Settings link */}
                <Link
                  href={`/projects/${p.id}/settings`}
                  className={clsx(
                    'group flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200',
                    isActive && pathname.includes('/settings')
                      ? 'bg-slate-500/15 text-slate-300'
                      : 'text-slate-400 hover:bg-slate-500/10 hover:text-slate-300',
                  )}
                >
                  <Settings2
                    className={clsx(
                      'w-4 h-4 flex-shrink-0 transition-colors duration-200',
                      isActive && pathname.includes('/settings')
                        ? 'text-slate-300'
                        : 'text-slate-500 group-hover:text-slate-300',
                    )}
                  />
                  <span className="truncate">Settings</span>
                </Link>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// =============================================================================
// Main Sidebar Component
// =============================================================================

function SidebarContent() {
  const pathname = usePathname()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(
    null,
  )
  const [mounted, setMounted] = useState(false)

  // Extract current project ID from URL
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const currentProjectId = projectMatch ? projectMatch[1] : null

  // Initialize state from localStorage
  useEffect(() => {
    const storedCollapsed = localStorage.getItem(COLLAPSED_KEY)

    if (storedCollapsed !== null) {
      setIsCollapsed(storedCollapsed === 'true')
    }
    setMounted(true)
  }, [])

  // Auto-expand current project
  useEffect(() => {
    if (!mounted) return

    if (currentProjectId) {
      setExpandedProjectId(currentProjectId)
    }
  }, [currentProjectId, mounted])

  const toggleCollapsed = () => {
    const newValue = !isCollapsed
    setIsCollapsed(newValue)
    localStorage.setItem(COLLAPSED_KEY, String(newValue))
  }

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
          onClick={toggleCollapsed}
          className="w-full flex items-center justify-center p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors"
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
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

export function Sidebar() {
  return (
    <Suspense
      fallback={
        <nav className="w-16 h-full bg-slate-900/50 border-r border-slate-700/50 flex-col hidden md:flex" />
      }
    >
      <SidebarContent />
    </Suspense>
  )
}
