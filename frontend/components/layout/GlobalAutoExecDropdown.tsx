'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, Loader2, Settings2, Zap } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchProjects,
  getAutonomousSettings,
  updateAutonomousSettings,
  type Project,
} from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface ProjectAutoExecStatus {
  projectId: string
  projectName: string
  enabled: boolean
  isInTimeWindow: boolean
  status: 'active' | 'paused' | 'off'
}

// ============================================================================
// Helper Functions
// ============================================================================

function calculateTimeWindowStatus(
  enabled: boolean,
  startHour: number,
  endHour: number
): boolean {
  if (!enabled) return false

  const now = new Date()
  const currentHour = now.getHours()

  if (startHour === 0 && endHour === 24) {
    return true
  } else if (startHour < endHour) {
    return currentHour >= startHour && currentHour < endHour
  } else {
    return currentHour >= startHour || currentHour < endHour
  }
}

// ============================================================================
// Project Toggle Component
// ============================================================================

interface ProjectAutoExecToggleProps {
  project: Project
  status: ProjectAutoExecStatus
  onToggle: (projectId: string, newEnabled: boolean) => void
  isUpdating: boolean
}

function ProjectAutoExecToggle({
  project,
  status,
  onToggle,
  isUpdating,
}: ProjectAutoExecToggleProps) {
  const handleToggle = () => {
    onToggle(project.id, !status.enabled)
  }

  return (
    <div className="group flex items-center gap-3 px-3 py-2 hover:bg-slate-800/50 rounded-lg transition-colors">
      {/* Project Icon */}
      <div className="relative flex-shrink-0">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-slate-800/50 border border-slate-700/50">
          <span className="text-xs font-bold text-slate-400">
            {project.name.charAt(0).toUpperCase()}
          </span>
        </div>
      </div>

      {/* Project Info */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-slate-300 truncate">
          {project.name}
        </div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <div
            className={clsx(
              'w-1.5 h-1.5 rounded-full',
              status.status === 'active'
                ? 'bg-phosphor-400 shadow-[0_0_6px_rgba(0,245,255,0.5)]'
                : status.status === 'paused'
                  ? 'bg-amber-400'
                  : 'bg-slate-600'
            )}
          />
          <span
            className={clsx(
              'text-xs font-medium',
              status.status === 'active'
                ? 'text-phosphor-400'
                : status.status === 'paused'
                  ? 'text-amber-400'
                  : 'text-slate-500'
            )}
          >
            {status.status === 'active'
              ? 'Active'
              : status.status === 'paused'
                ? 'Paused'
                : 'Off'}
          </span>
        </div>
      </div>

      {/* Toggle Switch */}
      <button
        onClick={handleToggle}
        disabled={isUpdating}
        className={clsx(
          'relative w-11 h-6 rounded-full transition-all duration-200 disabled:opacity-50',
          status.enabled
            ? 'bg-phosphor-500/30'
            : 'bg-slate-700/50'
        )}
      >
        <div
          className={clsx(
            'absolute top-0.5 w-5 h-5 rounded-full transition-all duration-200 shadow-lg',
            status.enabled
              ? 'left-[22px] bg-phosphor-400'
              : 'left-0.5 bg-slate-500'
          )}
        >
          {isUpdating && (
            <Loader2 className="w-3 h-3 absolute inset-0 m-auto animate-spin text-slate-900" />
          )}
        </div>
      </button>

      {/* Settings Link */}
      <Link
        href={`/projects/${project.id}/settings`}
        className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
        onClick={(e) => e.stopPropagation()}
      >
        <Settings2 className="w-4 h-4" />
      </Link>
    </div>
  )
}

// ============================================================================
// Global Auto-Exec Dropdown
// ============================================================================

export function GlobalAutoExecDropdown() {
  const [isOpen, setIsOpen] = useState(false)
  const [updatingProject, setUpdatingProject] = useState<string | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  // Fetch all projects
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  // Fetch autonomous settings for all projects
  const projectSettings = useQuery({
    queryKey: ['all-autonomous-settings'],
    queryFn: async () => {
      if (!projects) return []
      const settingsPromises = projects.map((p) =>
        getAutonomousSettings(p.id).catch(() => null)
      )
      return Promise.all(settingsPromises)
    },
    enabled: !!projects && projects.length > 0,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  // Calculate global status
  const globalStatus = useMemo(() => {
    if (!projects || !projectSettings.data) {
      return { color: 'red', label: 'Unknown' }
    }

    const statuses: ProjectAutoExecStatus[] = projects.map((project, idx) => {
      const settings = projectSettings.data[idx]
      const enabled = settings?.enabled ?? false
      const isInTimeWindow = settings
        ? calculateTimeWindowStatus(
            settings.enabled,
            settings.start_hour,
            settings.end_hour
          )
        : false

      return {
        projectId: project.id,
        projectName: project.name,
        enabled,
        isInTimeWindow,
        status: !enabled ? 'off' : isInTimeWindow ? 'active' : 'paused',
      }
    })

    const activeCount = statuses.filter((s) => s.status === 'active').length
    const enabledCount = statuses.filter((s) => s.enabled).length

    if (enabledCount === 0) {
      return { color: 'red', label: 'All Off', statuses }
    } else if (activeCount === projects.length) {
      return { color: 'green', label: 'All Active', statuses }
    } else {
      return { color: 'yellow', label: 'Partial', statuses }
    }
  }, [projects, projectSettings.data])

  // Toggle mutation
  const toggleMutation = useMutation({
    mutationFn: async ({
      projectId,
      enabled,
    }: {
      projectId: string
      enabled: boolean
    }) => {
      return updateAutonomousSettings(projectId, { enabled })
    },
    onMutate: ({ projectId }) => {
      setUpdatingProject(projectId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-autonomous-settings'] })
      queryClient.invalidateQueries({ queryKey: ['autonomous-settings'] })
    },
    onSettled: () => {
      setUpdatingProject(null)
    },
  })

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const handleToggle = (projectId: string, newEnabled: boolean) => {
    toggleMutation.mutate({ projectId, enabled: newEnabled })
  }

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={clsx(
          'group flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200',
          globalStatus.color === 'green'
            ? 'bg-phosphor-500/15 text-phosphor-400 hover:bg-phosphor-500/20'
            : globalStatus.color === 'yellow'
              ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/20'
              : 'bg-red-500/15 text-red-400 hover:bg-red-500/20'
        )}
      >
        <Zap
          className={clsx(
            'w-4 h-4 transition-colors duration-200',
            globalStatus.color === 'green'
              ? 'text-phosphor-400'
              : globalStatus.color === 'yellow'
                ? 'text-amber-400'
                : 'text-red-400'
          )}
        />
        <span className="hidden xl:inline">Auto-exec</span>
        <ChevronDown
          className={clsx(
            'w-3.5 h-3.5 transition-transform duration-200',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-80 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl shadow-black/50 overflow-hidden z-50">
          {/* Header */}
          <div className="px-3 py-2.5 border-b border-slate-700/50 bg-slate-800/50">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-semibold text-slate-300">
                Auto-exec Status
              </span>
            </div>
          </div>

          {/* Project List */}
          <div className="max-h-96 overflow-y-auto p-2">
            {projectSettings.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
              </div>
            ) : globalStatus.statuses && globalStatus.statuses.length > 0 ? (
              <div className="space-y-1">
                {projects?.map((project, idx) => {
                  const status = globalStatus.statuses[idx]
                  return (
                    <ProjectAutoExecToggle
                      key={project.id}
                      project={project}
                      status={status}
                      onToggle={handleToggle}
                      isUpdating={updatingProject === project.id}
                    />
                  )
                })}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-slate-500">
                <span className="text-sm">No projects found</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
