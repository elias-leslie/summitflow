'use client'

import { useQuery } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useIsXl } from '@/hooks/useMediaQuery'
import { fetchTasks, type Task } from '@/lib/api'
import { STALE_GIT } from '@/lib/polling'
import { useSelectedProject } from '../ProjectSelector'
import { typeIcons } from './constants'

interface TaskSearchProps {
  onExpandedChange?: (isExpanded: boolean) => void
}

export function TaskSearch({ onExpandedChange }: TaskSearchProps) {
  const router = useRouter()
  const [isSearchFocused, setIsSearchFocused] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [isOpen, setIsOpen] = useState(false)
  const selectedProjectId = useSelectedProject()
  const searchRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const isXl = useIsXl()

  const { data: tasksData } = useQuery({
    queryKey: ['tasks', selectedProjectId, 'search'],
    queryFn: () => fetchTasks(selectedProjectId!, { limit: 500 }),
    enabled: !!selectedProjectId && searchValue.length > 0,
    staleTime: STALE_GIT,
  })

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
      .slice(0, 8)
  }, [searchValue, tasksData])

  useEffect(() => {
    setSelectedIndex(0)
  }, [searchResults])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setSearchValue('')
      setIsOpen(false)
      inputRef.current?.blur()
      return
    }
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
    }
  }

  const navigateToTask = (task: Task) => {
    router.push(`/projects/${task.project_id}?task=${task.id}`)
    setSearchValue('')
    setIsOpen(false)
    inputRef.current?.blur()
  }

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setIsSearchFocused(false)
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Focus input when popover opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isOpen])

  const showPopover = !isXl
  const isInlineExpanded = !showPopover && (isSearchFocused || !!searchValue)
  const isSearchExpanded = showPopover ? isOpen : isInlineExpanded

  useEffect(() => {
    setIsOpen(false)

    if (showPopover) {
      setIsSearchFocused(false)
      inputRef.current?.blur()
    }
  }, [showPopover])

  useEffect(() => {
    onExpandedChange?.(isSearchExpanded)

    return () => {
      onExpandedChange?.(false)
    }
  }, [isSearchExpanded, onExpandedChange])

  const resultsDropdown = (
    <>
      {isSearchFocused && searchValue && searchResults.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl overflow-hidden z-50">
          {searchResults.map((task, index) => (
            <button
              type="button"
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
                <div className="text-xs text-slate-500 truncate">{task.id}</div>
              </div>
              <span
                className={`text-xs px-1.5 py-0.5 rounded ${
                  task.status === 'completed'
                    ? 'bg-phosphor-500/20 text-phosphor-400'
                    : task.status === 'running'
                      ? 'bg-outrun-500/20 text-outrun-400'
                      : task.status === 'failed'
                        ? 'bg-rose-500/20 text-rose-400'
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
    </>
  )

  // Compact: icon button that opens a popover with the search field
  if (showPopover) {
    return (
      <div className="hidden md:block relative" ref={searchRef}>
        {!isOpen ? (
          <button
            type="button"
            onClick={() => setIsOpen(true)}
            className="p-2.5 rounded-lg text-slate-400 hover:bg-slate-800/50 hover:text-slate-300 transition-all duration-200"
            aria-label="Search tasks"
          >
            <Search className="w-5 h-5" />
          </button>
        ) : (
          <div className="relative z-50">
            <div className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 shadow-xl">
              <Search className="w-4 h-4 text-slate-500 flex-shrink-0" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Search tasks..."
                aria-label="Search tasks"
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setIsSearchFocused(true)}
                className="w-48 bg-transparent text-sm text-slate-200 placeholder-slate-500 outline-none lg:w-56"
              />
              <button
                type="button"
                onClick={() => {
                  setSearchValue('')
                  setIsOpen(false)
                }}
                className="p-0.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {resultsDropdown}
          </div>
        )}
      </div>
    )
  }

  // Wide desktop: inline search field
  return (
    <div ref={searchRef}>
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
          placeholder={isSearchFocused ? 'Search tasks by title or ID...' : ''}
          aria-label="Search tasks"
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          onKeyDown={handleKeyDown}
          className={`input ${!isSearchFocused && !searchValue ? 'pl-12' : 'pl-4'} pr-4 py-2 text-sm bg-slate-800/80 border-slate-700 w-56 focus:w-72 focus:border-outrun-500/50 transition-all duration-300`}
          onFocus={() => setIsSearchFocused(true)}
        />
        {resultsDropdown}
      </div>
    </div>
  )
}
