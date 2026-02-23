'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, ExternalLink, Loader2, Zap } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchProjects } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface AHProjectPermission {
  project_id: string
  permission_tier: 'off' | 'read' | 'write' | 'yolo'
  auto_exec_enabled: boolean
  execution_start_hour: number
  execution_end_hour: number
}

interface ProjectExecStatus {
  projectId: string
  projectName: string
  tier: string
  autoExec: boolean
  status: 'active' | 'restricted' | 'off'
}

const TIER_CONFIG = {
  off: { label: 'Off', dot: 'bg-slate-600', text: 'text-slate-500' },
  read: { label: 'Read', dot: 'bg-blue-400', text: 'text-blue-400' },
  write: { label: 'Write', dot: 'bg-amber-400', text: 'text-amber-400' },
  yolo: { label: 'YOLO', dot: 'bg-emerald-400', text: 'text-emerald-400' },
} as const

// ============================================================================
// API
// ============================================================================

async function fetchAHPermissions(): Promise<AHProjectPermission[]> {
  const res = await fetch('/api/agent-hub/projects/permissions')
  if (!res.ok) return []
  return res.json()
}

// ============================================================================
// Project Status Row
// ============================================================================

function ProjectExecRow({ status }: { status: ProjectExecStatus }) {
  const tierCfg = TIER_CONFIG[status.tier as keyof typeof TIER_CONFIG] ?? TIER_CONFIG.off

  return (
    <div className="group flex items-center gap-3 px-3 py-2 hover:bg-slate-800/50 rounded-lg transition-colors">
      <div className="relative flex-shrink-0">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-slate-800/50 border border-slate-700/50">
          <span className="text-xs font-bold text-slate-400">
            {status.projectName.charAt(0).toUpperCase()}
          </span>
        </div>
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-slate-300 truncate">
          {status.projectName}
        </div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <div className={clsx('w-1.5 h-1.5 rounded-full', tierCfg.dot)} />
          <span className={clsx('text-xs font-medium', tierCfg.text)}>
            {tierCfg.label}
          </span>
          {status.autoExec && (
            <span className="text-[10px] text-phosphor-400 ml-1">+ exec</span>
          )}
        </div>
      </div>

      <span
        className={clsx(
          'text-[10px] font-bold px-1.5 py-0.5 rounded',
          status.status === 'active'
            ? 'bg-phosphor-500/15 text-phosphor-400'
            : status.status === 'restricted'
              ? 'bg-amber-500/15 text-amber-400'
              : 'bg-slate-700/50 text-slate-500',
        )}
      >
        {status.status === 'active'
          ? 'ACTIVE'
          : status.status === 'restricted'
            ? 'LIMITED'
            : 'OFF'}
      </span>
    </div>
  )
}

// ============================================================================
// Global Auto-Exec Dropdown
// ============================================================================

export function GlobalAutoExecDropdown() {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  const { data: permissions, isLoading: permLoading } = useQuery({
    queryKey: ['ah-project-permissions'],
    queryFn: fetchAHPermissions,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })

  const { statuses, globalColor } = useMemo(() => {
    if (!projects || !permissions) {
      return { statuses: [], globalColor: 'red' as const }
    }

    const permMap = new Map(permissions.map((p) => [p.project_id, p]))
    const statusList: ProjectExecStatus[] = projects.map((project) => {
      const perm = permMap.get(project.id)
      const tier = perm?.permission_tier ?? 'off'
      const autoExec = perm?.auto_exec_enabled ?? false
      let status: ProjectExecStatus['status'] = 'off'
      if (tier === 'yolo' && autoExec) status = 'active'
      else if (tier !== 'off') status = 'restricted'

      return {
        projectId: project.id,
        projectName: project.name,
        tier,
        autoExec,
        status,
      }
    })

    const activeCount = statusList.filter((s) => s.status === 'active').length
    const offCount = statusList.filter((s) => s.status === 'off').length

    let color: 'green' | 'yellow' | 'red' = 'red'
    if (activeCount === projects.length) {
      color = 'green'
    } else if (offCount < projects.length) {
      color = 'yellow'
    }

    return { statuses: statusList, globalColor: color }
  }, [projects, permissions])

  // Close on outside click
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

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={clsx(
          'group flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200',
          globalColor === 'green'
            ? 'bg-phosphor-500/15 text-phosphor-400 hover:bg-phosphor-500/20'
            : globalColor === 'yellow'
              ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/20'
              : 'bg-red-500/15 text-red-400 hover:bg-red-500/20',
        )}
      >
        <Zap
          className={clsx(
            'w-4 h-4 transition-colors duration-200',
            globalColor === 'green'
              ? 'text-phosphor-400'
              : globalColor === 'yellow'
                ? 'text-amber-400'
                : 'text-red-400',
          )}
        />
        <span className="hidden xl:inline">Auto-exec</span>
        <ChevronDown
          className={clsx(
            'w-3.5 h-3.5 transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-80 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl shadow-black/50 overflow-hidden z-50">
          <div className="px-3 py-2.5 border-b border-slate-700/50 bg-slate-800/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-semibold text-slate-300">
                  Auto-exec Status
                </span>
              </div>
              <span className="text-[10px] text-slate-500">
                via Agent Hub
              </span>
            </div>
          </div>

          <div className="max-h-96 overflow-y-auto p-2">
            {permLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
              </div>
            ) : statuses.length > 0 ? (
              <div className="space-y-1">
                {statuses.map((status) => (
                  <ProjectExecRow key={status.projectId} status={status} />
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-slate-500">
                <span className="text-sm">No projects found</span>
              </div>
            )}
          </div>

          {/* Link to Agent Hub permissions */}
          <div className="px-3 py-2 border-t border-slate-700/50 bg-slate-800/30">
            <a
              href="/api/agent-hub/projects/permissions"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300 transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              Manage in Agent Hub
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
