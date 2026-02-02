'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  Archive,
  ArrowDownCircle,
  Bug,
  CheckSquare,
  GitBranch,
  Info,
  LayoutGrid,
  Package,
  RefreshCw,
  Search,
} from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { NotificationBell } from '@/components/notifications'
import { fetchTasks, type Task, type TaskType } from '@/lib/api'
import { fetchGitStatus, type RepoStatus } from '@/lib/api/git'
import { GlobalAutoExecDropdown } from './GlobalAutoExecDropdown'
import { useSelectedProject } from './ProjectSelector'

type GitHealthState = 'clean' | 'dirty' | 'behind' | 'loading' | 'error'

function useGitHealth(): GitHealthState {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['git-status-topbar'],
    queryFn: fetchGitStatus,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  if (isLoading) return 'loading'
  if (isError || !data) return 'error'

  const repos = data.repositories
  if (repos.some((r: RepoStatus) => r.state === 'behind')) return 'behind'
  if (repos.some((r: RepoStatus) => r.state === 'dirty' || r.state === 'ahead'))
    return 'dirty'
  return 'clean'
}

function GitStatusIndicator({ state }: { state: GitHealthState }) {
  if (state === 'loading' || state === 'error') return null

  const colorClasses = {
    clean: 'bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.7)]',
    dirty: 'bg-sunset-orange shadow-[0_0_8px_rgba(255,102,0,0.7)]',
    behind: 'bg-outrun-500 shadow-[0_0_8px_rgba(255,0,102,0.7)]',
  }

  const pulseClasses = {
    clean: '',
    dirty: 'animate-pulse',
    behind: 'animate-pulse',
  }

  return (
    <span
      className={clsx(
        'w-2 h-2 rounded-full flex-shrink-0',
        colorClasses[state],
        pulseClasses[state],
      )}
      title={
        state === 'clean'
          ? 'All repos clean'
          : state === 'dirty'
            ? 'Uncommitted changes or ahead of remote'
            : 'Behind remote - pull needed'
      }
    />
  )
}

const SUMMITFLOW_PROJECT_ID = 'summitflow'

const LOGO_WIDE_WIDTH = 200
const LOGO_HEIGHT = 56
const LOGO_SQUARE_SIZE = 56
const LOGO_CONTAINER_WIDTH = 220
const LOGO_SHIFT_COLLAPSED = 72

const typeIcons: Record<TaskType, React.ReactNode> = {
  feature: <Package className="h-3.5 w-3.5 text-purple-400" />,
  bug: <Bug className="h-3.5 w-3.5 text-rose-400" />,
  task: <CheckSquare className="h-3.5 w-3.5 text-blue-400" />,
  refactor: <RefreshCw className="h-3.5 w-3.5 text-cyan-400" />,
  debt: <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />,
  regression: <ArrowDownCircle className="h-3.5 w-3.5 text-orange-400" />,
}

// Navigation items configuration
const navItems = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    href: '/',
    icon: LayoutGrid,
    activeColor: 'outrun',
  },
  {
    id: 'git',
    label: 'Git',
    href: '/git',
    icon: GitBranch,
    activeColor: 'violet',
  },
  {
    id: 'backups',
    label: 'Backups',
    href: '/backups',
    icon: Archive,
    activeColor: 'indigo',
  },
] as const

export function TopBar() {
  const router = useRouter()
  const pathname = usePathname()
  const [isSearchFocused, setIsSearchFocused] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const selectedProjectId = useSelectedProject()
  const searchRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const gitHealth = useGitHealth()

  const [isExpanded, setIsExpanded] = useState(false)
  const collapseTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Fetch tasks for search (only when we have a project selected)
  const { data: tasksData } = useQuery({
    queryKey: ['tasks', selectedProjectId, 'search'],
    queryFn: () => fetchTasks(selectedProjectId!, { limit: 500 }),
    enabled: !!selectedProjectId && searchValue.length > 0,
    staleTime: 30000,
  })

  // Filter tasks based on search value
  const searchResults = useMemo(() => {
    if (!searchValue.trim() || !tasksData?.tasks) return []
    const query = searchValue.toLowerCase()
    return tasksData.tasks
      .filter(
        (task) =>
          task.title.toLowerCase().includes(query) ||
          task.description?.toLowerCase().includes(query) ||
          task.id.toLowerCase().includes(query),
      )
      .slice(0, 8) // Limit to 8 results
  }, [searchValue, tasksData])

  // Reset selected index when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [])

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!searchResults.length) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.min(prev + 1, searchResults.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter' && searchResults[selectedIndex]) {
      e.preventDefault()
      navigateToTask(searchResults[selectedIndex])
    } else if (e.key === 'Escape') {
      setSearchValue('')
      inputRef.current?.blur()
    }
  }

  const navigateToTask = (task: Task) => {
    router.push(`/projects/${task.project_id}?task=${task.id}`)
    setSearchValue('')
    inputRef.current?.blur()
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setIsSearchFocused(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (isExpanded) {
      collapseTimeoutRef.current = setTimeout(() => {
        setIsExpanded(false)
      }, 3500)
    }

    return () => {
      if (collapseTimeoutRef.current) {
        clearTimeout(collapseTimeoutRef.current)
      }
    }
  }, [isExpanded])

  const handleLogoClick = () => {
    router.push('/')
    if (!isExpanded) {
      setIsExpanded(true)
    }
  }

  return (
    <>
      <header className="h-16 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-4">
        {/* Logo Container */}
        <button
          onClick={handleLogoClick}
          className="flex items-center flex-shrink-0 group focus:outline-none"
          aria-label="Go to dashboard"
          style={{
            width: LOGO_CONTAINER_WIDTH,
            height: LOGO_HEIGHT,
          }}
        >
          <div
            className="flex items-center"
            style={{
              justifyContent: isExpanded ? 'center' : 'flex-start',
              width: '100%',
              transition: 'justify-content 0.3s ease-out',
            }}
          >
            <div
              className="relative flex-shrink-0 overflow-hidden"
              style={{
                width: isExpanded ? LOGO_WIDE_WIDTH : LOGO_SQUARE_SIZE,
                height: LOGO_HEIGHT,
                transition: 'width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
              }}
            >
              <Image
                src="/logo-wide-v4.svg"
                alt="SummitFlow"
                width={LOGO_WIDE_WIDTH}
                height={LOGO_HEIGHT}
                className="h-full"
                style={{
                  width: LOGO_WIDE_WIDTH,
                  minWidth: LOGO_WIDE_WIDTH,
                  transform: isExpanded
                    ? 'translateX(0)'
                    : `translateX(-${LOGO_SHIFT_COLLAPSED}px)`,
                  transition:
                    'transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                  filter: isExpanded
                    ? 'drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.2))'
                    : 'drop-shadow(0 0 12px rgba(255,102,0,0.3)) drop-shadow(0 0 24px rgba(255,0,102,0.15))',
                }}
                priority
              />
            </div>

            <div
              className="overflow-hidden flex-shrink-0"
              style={{
                maxWidth: isExpanded ? 0 : 140,
                marginLeft: isExpanded ? 0 : 12,
                transition:
                  'max-width 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94), margin-left 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
              }}
            >
              <span
                className="font-semibold text-xl tracking-tight whitespace-nowrap block"
                style={{
                  background:
                    'linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                  transform: isExpanded ? 'translateX(-20px)' : 'translateX(0)',
                  transition:
                    'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                }}
              >
                SummitFlow
              </span>
            </div>
          </div>

          <div
            className="absolute inset-0 pointer-events-none rounded-lg opacity-0 group-hover:opacity-100"
            style={{
              boxShadow:
                '0 0 30px rgba(255,102,0,0.08), 0 0 60px rgba(255,0,102,0.05)',
              transition: 'opacity 0.3s ease-out',
            }}
          />
        </button>

        {/* Global Navigation */}
        <nav className="hidden lg:flex items-center gap-1 ml-4">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive =
              pathname === item.href ||
              (item.href !== '/' && pathname.startsWith(item.href))

            return (
              <Link
                key={item.id}
                href={item.href}
                className={clsx(
                  'group flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200',
                  isActive
                    ? item.activeColor === 'outrun'
                      ? 'bg-outrun-500/15 text-outrun-400'
                      : item.activeColor === 'violet'
                        ? 'bg-violet-500/15 text-violet-400'
                        : 'bg-indigo-500/15 text-indigo-400'
                    : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-300',
                )}
              >
                <Icon
                  className={clsx(
                    'w-4 h-4 transition-colors duration-200',
                    isActive
                      ? item.activeColor === 'outrun'
                        ? 'text-outrun-400'
                        : item.activeColor === 'violet'
                          ? 'text-violet-400'
                          : 'text-indigo-400'
                      : 'text-slate-500 group-hover:text-slate-400',
                  )}
                />
                <span>{item.label}</span>
                {item.id === 'git' && <GitStatusIndicator state={gitHealth} />}
              </Link>
            )
          })}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Global Auto-exec Dropdown */}
        <GlobalAutoExecDropdown />

        {/* Search */}
        <div className="hidden md:block" ref={searchRef}>
          <div
            className={`relative transition-all duration-300 ${
              isSearchFocused ? 'scale-[1.02]' : ''
            }`}
          >
            {!isSearchFocused && !searchValue && (
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none z-10" />
            )}
            <input
              ref={inputRef}
              type="text"
              placeholder=""
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              onKeyDown={handleKeyDown}
              className={`input ${!isSearchFocused && !searchValue ? 'pl-12' : 'pl-4'} pr-4 py-2 text-sm bg-slate-800/80 border-slate-700 w-56 focus:w-72 focus:border-outrun-500/50 transition-all duration-300`}
              onFocus={() => setIsSearchFocused(true)}
            />
            {/* Search Results Dropdown */}
            {isSearchFocused && searchValue && searchResults.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl overflow-hidden z-50">
                {searchResults.map((task, index) => (
                  <button
                    key={task.id}
                    onClick={() => navigateToTask(task)}
                    className={`w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-slate-700/50 transition-colors ${
                      index === selectedIndex ? 'bg-slate-700/50' : ''
                    }`}
                  >
                    {typeIcons[task.task_type] || typeIcons.task}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-200 truncate">
                        {task.title}
                      </div>
                      <div className="text-xs text-slate-500 truncate">
                        {task.id}
                      </div>
                    </div>
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded ${
                        task.status === 'completed'
                          ? 'bg-green-500/20 text-green-400'
                          : task.status === 'running'
                            ? 'bg-blue-500/20 text-blue-400'
                            : 'bg-slate-500/20 text-slate-400'
                      }`}
                    >
                      {task.status}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {isSearchFocused && searchValue && searchResults.length === 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 z-50">
                <span className="text-sm text-slate-500">No tasks found</span>
              </div>
            )}
          </div>
        </div>

        {/* Right side actions - About + Notifications */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {/* About */}
          <Link
            href="/about"
            data-testid="topbar-about"
            className="p-2.5 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="About SummitFlow"
          >
            <Info className="w-5 h-5" />
          </Link>

          {/* Notifications */}
          <NotificationBell projectId={SUMMITFLOW_PROJECT_ID} />
        </div>
      </header>

      {/* Chrome accent line under header */}
      <div className="chrome-line" />
    </>
  )
}
