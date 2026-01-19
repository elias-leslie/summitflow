'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Archive,
  Camera,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  FileCode,
  FlaskConical,
  FolderKanban,
  GitBranch,
  Globe,
  Kanban,
  LayoutGrid,
  ListTodo,
  Settings2,
  Zap,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { fetchProject, fetchProjects, getAutonomousSettings } from '@/lib/api'

// =============================================================================
// Types & Constants
// =============================================================================

type SidebarMode = 'global' | 'projects'
type NavItemId =
  | 'dashboard'
  | 'git'
  | 'backups'
  | 'prompts'
  | 'settings'
  | 'kanban'
  | 'tasks'
  | 'tests'
  | 'evidence'
  | 'explorer'

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

// Global navigation items (shown in Global mode)
const globalNavItems: NavItemConfig[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    href: '/',
    icon: LayoutGrid,
    activeClasses: 'bg-outrun-500/15 text-outrun-400',
    inactiveClasses: 'text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400',
    iconActiveClasses: 'text-outrun-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-outrun-400',
  },
  {
    id: 'git',
    label: 'Git',
    href: '/git',
    icon: GitBranch,
    activeClasses: 'bg-violet-500/15 text-violet-400',
    inactiveClasses: 'text-slate-400 hover:bg-violet-500/10 hover:text-violet-400',
    iconActiveClasses: 'text-violet-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-violet-400',
  },
  {
    id: 'backups',
    label: 'Backups',
    href: '/backups',
    icon: Archive,
    activeClasses: 'bg-indigo-500/15 text-indigo-400',
    inactiveClasses: 'text-slate-400 hover:bg-indigo-500/10 hover:text-indigo-400',
    iconActiveClasses: 'text-indigo-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-indigo-400',
  },
  {
    id: 'prompts',
    label: 'Prompts',
    href: '/prompts',
    icon: FileCode,
    activeClasses: 'bg-amber-500/15 text-amber-400',
    inactiveClasses: 'text-slate-400 hover:bg-amber-500/10 hover:text-amber-400',
    iconActiveClasses: 'text-amber-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-amber-400',
  },
  {
    id: 'settings',
    label: 'Settings',
    href: '/settings',
    icon: Settings2,
    activeClasses: 'bg-slate-500/15 text-slate-300',
    inactiveClasses: 'text-slate-400 hover:bg-slate-500/10 hover:text-slate-300',
    iconActiveClasses: 'text-slate-300',
    iconInactiveClasses: 'text-slate-500 group-hover:text-slate-300',
  },
]

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
    inactiveClasses: 'text-slate-400 hover:bg-orange-500/10 hover:text-orange-400',
    iconActiveClasses: 'text-orange-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-orange-400',
  },
  {
    id: 'tests',
    label: 'Tests',
    href: '/tests',
    icon: FlaskConical,
    activeClasses: 'bg-phosphor-500/15 text-phosphor-400',
    inactiveClasses: 'text-slate-400 hover:bg-phosphor-500/10 hover:text-phosphor-400',
    iconActiveClasses: 'text-phosphor-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-phosphor-400',
  },
  {
    id: 'evidence',
    label: 'Evidence',
    href: '',
    icon: Camera,
    activeClasses: 'bg-pink-500/15 text-pink-400',
    inactiveClasses: 'text-slate-400 hover:bg-pink-500/10 hover:text-pink-400',
    iconActiveClasses: 'text-pink-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-pink-400',
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
]

const COLLAPSED_KEY = 'summitflow_sidebar_collapsed'
const MODE_KEY = 'summitflow_sidebar_mode'

// =============================================================================
// Segmented Toggle Component
// =============================================================================

interface ModeToggleProps {
  mode: SidebarMode
  onChange: (mode: SidebarMode) => void
  isCollapsed: boolean
}

function ModeToggle({ mode, onChange, isCollapsed }: ModeToggleProps) {
  if (isCollapsed) {
    // Show stacked icons when collapsed
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        <button
          onClick={() => onChange('global')}
          className={clsx(
            'w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200',
            mode === 'global'
              ? 'bg-gradient-to-br from-phosphor-500/30 to-phosphor-600/20 text-phosphor-400 shadow-[0_0_12px_rgba(0,245,255,0.3)]'
              : 'text-slate-500 hover:text-slate-400 hover:bg-slate-800/50',
          )}
          title="Global"
        >
          <Globe className="w-4 h-4" />
        </button>
        <button
          onClick={() => onChange('projects')}
          className={clsx(
            'w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200',
            mode === 'projects'
              ? 'bg-gradient-to-br from-outrun-500/30 to-outrun-600/20 text-outrun-400 shadow-[0_0_12px_rgba(255,0,102,0.3)]'
              : 'text-slate-500 hover:text-slate-400 hover:bg-slate-800/50',
          )}
          title="Projects"
        >
          <FolderKanban className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <div
      data-testid="sidebar-mode-toggle"
      className="relative flex p-1 rounded-xl bg-slate-900/80 border border-slate-700/50"
    >
      {/* Animated pill background */}
      <div
        className={clsx(
          'absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-lg transition-all duration-250 ease-out',
          mode === 'global'
            ? 'left-1 bg-gradient-to-r from-phosphor-500/25 to-phosphor-600/15 shadow-[0_0_16px_rgba(0,245,255,0.25),inset_0_1px_0_rgba(255,255,255,0.1)]'
            : 'left-[calc(50%+2px)] bg-gradient-to-r from-outrun-500/25 to-outrun-600/15 shadow-[0_0_16px_rgba(255,0,102,0.25),inset_0_1px_0_rgba(255,255,255,0.1)]',
        )}
      />

      {/* Global button */}
      <button
        onClick={() => onChange('global')}
        className={clsx(
          'relative z-10 flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-semibold tracking-wide uppercase transition-colors duration-200',
          mode === 'global'
            ? 'text-phosphor-400'
            : 'text-slate-500 hover:text-slate-400',
        )}
      >
        <Globe className="w-3.5 h-3.5" />
        <span>Global</span>
      </button>

      {/* Projects button */}
      <button
        onClick={() => onChange('projects')}
        className={clsx(
          'relative z-10 flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-semibold tracking-wide uppercase transition-colors duration-200',
          mode === 'projects'
            ? 'text-outrun-400'
            : 'text-slate-500 hover:text-slate-400',
        )}
      >
        <FolderKanban className="w-3.5 h-3.5" />
        <span>Projects</span>
      </button>
    </div>
  )
}

// =============================================================================
// Auto-exec Status Component
// =============================================================================

interface AutoExecStatusProps {
  isCollapsed: boolean
}

function AutoExecStatus({ isCollapsed }: AutoExecStatusProps) {
  const pathname = usePathname()

  // Extract project ID from pathname
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const selectedProjectId = projectMatch ? projectMatch[1] : null

  const { data: autonomousSettings } = useQuery({
    queryKey: ['autonomous-settings', selectedProjectId],
    queryFn: () => getAutonomousSettings(selectedProjectId!),
    enabled: !!selectedProjectId,
    staleTime: 60000,
    refetchInterval: 60000,
  })

  // Calculate if currently in execution window (client-side only to avoid hydration mismatch)
  const [isInTimeWindow, setIsInTimeWindow] = useState(false)
  useEffect(() => {
    if (!autonomousSettings) {
      setIsInTimeWindow(false)
      return
    }
    const now = new Date()
    const currentHour = now.getHours()
    const { start_hour, end_hour } = autonomousSettings
    if (start_hour === 0 && end_hour === 24) {
      setIsInTimeWindow(true)
    } else if (start_hour < end_hour) {
      setIsInTimeWindow(currentHour >= start_hour && currentHour < end_hour)
    } else {
      setIsInTimeWindow(currentHour >= start_hour || currentHour < end_hour)
    }
  }, [autonomousSettings])

  const status = useMemo(() => {
    if (!autonomousSettings) return { label: 'Off', color: 'slate', active: false }
    if (!autonomousSettings.enabled) return { label: 'Off', color: 'slate', active: false }
    if (!isInTimeWindow) return { label: 'Paused', color: 'amber', active: false }
    return { label: 'Active', color: 'phosphor', active: true }
  }, [autonomousSettings, isInTimeWindow])

  const href = selectedProjectId ? `/projects/${selectedProjectId}/settings` : '/settings'

  if (isCollapsed) {
    return (
      <Link
        href={href}
        data-testid="auto-exec-status"
        className={clsx(
          'flex items-center justify-center w-10 h-10 mx-auto rounded-lg transition-all duration-200',
          status.active
            ? 'bg-phosphor-500/15 text-phosphor-400 shadow-[0_0_8px_rgba(0,245,255,0.2)]'
            : status.color === 'amber'
              ? 'bg-amber-500/10 text-amber-400'
              : 'bg-slate-800/50 text-slate-500 hover:text-slate-400',
        )}
        title={`Auto-exec: ${status.label}`}
      >
        <Zap className={clsx('w-4 h-4', status.active && 'animate-pulse')} />
      </Link>
    )
  }

  return (
    <Link
      href={href}
      data-testid="auto-exec-status"
      className={clsx(
        'flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group',
        status.active
          ? 'bg-phosphor-500/10 hover:bg-phosphor-500/15'
          : status.color === 'amber'
            ? 'bg-amber-500/5 hover:bg-amber-500/10'
            : 'hover:bg-slate-800/50',
      )}
    >
      <div
        className={clsx(
          'flex items-center justify-center w-8 h-8 rounded-lg transition-all duration-200',
          status.active
            ? 'bg-phosphor-500/20 shadow-[0_0_12px_rgba(0,245,255,0.25)]'
            : status.color === 'amber'
              ? 'bg-amber-500/15'
              : 'bg-slate-800',
        )}
      >
        <Zap
          className={clsx(
            'w-4 h-4 transition-colors',
            status.active
              ? 'text-phosphor-400'
              : status.color === 'amber'
                ? 'text-amber-400'
                : 'text-slate-500 group-hover:text-slate-400',
            status.active && 'animate-pulse',
          )}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
          Auto-exec
        </div>
        <div
          className={clsx(
            'text-sm font-semibold',
            status.active
              ? 'text-phosphor-400'
              : status.color === 'amber'
                ? 'text-amber-400'
                : 'text-slate-500',
          )}
        >
          {status.label}
        </div>
      </div>
      {status.active && (
        <div className="w-2 h-2 rounded-full bg-phosphor-400 shadow-[0_0_8px_rgba(0,245,255,0.6)] animate-pulse" />
      )}
    </Link>
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
    if (pathname.includes('/tests')) return 'tests'
    if (pathname.includes('/prompts')) return 'prompts'
    if (pathname.includes('/git')) return 'git' as NavItemId
    if (pathname.includes('/backups')) return 'backups' as NavItemId
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
            <span className="text-xs font-bold">{p.name.charAt(0).toUpperCase()}</span>
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
    <div ref={accordionRef} className="space-y-1" data-testid="projects-accordion">
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
                isActive
                  ? 'bg-outrun-500/10'
                  : 'hover:bg-slate-800/50',
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
                      isActive ? 'text-outrun-400' : 'text-slate-400 group-hover:text-slate-300',
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
                    isActive ? 'text-white' : 'text-slate-300 group-hover:text-white',
                  )}
                >
                  {p.name}
                </div>
              </div>

              {/* Expand chevron */}
              <ChevronDown
                className={clsx(
                  'w-4 h-4 transition-all duration-250 flex-shrink-0',
                  isExpanded ? 'rotate-180 text-outrun-400' : 'text-slate-500 group-hover:text-slate-400',
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
                        isItemActive ? item.activeClasses : item.inactiveClasses,
                      )}
                    >
                      <Icon
                        className={clsx(
                          'w-4 h-4 flex-shrink-0 transition-colors duration-200',
                          isItemActive ? item.iconActiveClasses : item.iconInactiveClasses,
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
// Global Nav Component
// =============================================================================

interface GlobalNavProps {
  isCollapsed: boolean
}

function GlobalNav({ isCollapsed }: GlobalNavProps) {
  const pathname = usePathname()

  return (
    <div className="space-y-1" data-testid="global-nav">
      {globalNavItems.map((item) => {
        const isActive = pathname === item.href ||
          (item.href !== '/' && pathname.startsWith(item.href))
        const Icon = item.icon

        return (
          <Link
            key={item.id}
            href={item.href}
            data-testid={`global-nav-${item.id}`}
            className={clsx(
              'group flex items-center rounded-lg text-sm font-medium transition-all duration-200',
              isCollapsed ? 'px-3 py-3 justify-center' : 'px-3 py-2.5 gap-3',
              isActive ? item.activeClasses : item.inactiveClasses,
            )}
            title={isCollapsed ? item.label : undefined}
          >
            <Icon
              className={clsx(
                'w-5 h-5 flex-shrink-0 transition-colors duration-200',
                isActive ? item.iconActiveClasses : item.iconInactiveClasses,
              )}
            />
            {!isCollapsed && <span className="truncate">{item.label}</span>}
          </Link>
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
  const [mode, setMode] = useState<SidebarMode>('global')
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)

  // Extract current project ID from URL
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  const currentProjectId = projectMatch ? projectMatch[1] : null

  // Initialize state from localStorage
  useEffect(() => {
    const storedCollapsed = localStorage.getItem(COLLAPSED_KEY)
    const storedMode = localStorage.getItem(MODE_KEY) as SidebarMode | null

    if (storedCollapsed !== null) {
      setIsCollapsed(storedCollapsed === 'true')
    }
    if (storedMode && (storedMode === 'global' || storedMode === 'projects')) {
      setMode(storedMode)
    }
    setMounted(true)
  }, [])

  // Auto-switch mode based on URL (subtask 1.5)
  useEffect(() => {
    if (!mounted) return

    if (currentProjectId) {
      // On project page - switch to projects mode and expand current project
      setMode('projects')
      setExpandedProjectId(currentProjectId)
    }
  }, [currentProjectId, mounted])

  const toggleCollapsed = () => {
    const newValue = !isCollapsed
    setIsCollapsed(newValue)
    localStorage.setItem(COLLAPSED_KEY, String(newValue))
  }

  const handleModeChange = (newMode: SidebarMode) => {
    setMode(newMode)
    localStorage.setItem(MODE_KEY, newMode)
    // Reset expanded project when switching to global
    if (newMode === 'global') {
      setExpandedProjectId(null)
    }
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
      {/* Mode Toggle */}
      <div className={clsx('p-2 border-b border-slate-700/50', isCollapsed && 'px-1')}>
        <ModeToggle mode={mode} onChange={handleModeChange} isCollapsed={isCollapsed} />
      </div>

      {/* Navigation Content */}
      <div className="flex-1 overflow-y-auto py-3 px-2">
        <div
          className={clsx(
            'transition-all duration-250 ease-out',
            mode === 'global' ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden',
          )}
        >
          <GlobalNav isCollapsed={isCollapsed} />
        </div>
        <div
          className={clsx(
            'transition-all duration-250 ease-out',
            mode === 'projects' ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden',
          )}
        >
          <ProjectsAccordion
            isCollapsed={isCollapsed}
            expandedProjectId={expandedProjectId}
            onExpandProject={setExpandedProjectId}
          />
        </div>
      </div>

      {/* Auto-exec Status - Always visible */}
      <div className="p-2 border-t border-slate-700/50">
        <AutoExecStatus isCollapsed={isCollapsed} />
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
