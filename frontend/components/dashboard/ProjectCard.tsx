'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  Bug,
  Clock,
  Database,
  ExternalLink,
  ListTodo,
  Settings2,
  Target,
} from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import {
  fetchProjectHealth,
  fetchQualityGateHealth,
  type ProjectWithStats,
} from '@/lib/api'
import { getActiveCheckpoint } from '@/lib/api/checkpoints'
import { POLL_STANDARD, STALE_GIT, STALE_STANDARD } from '@/lib/polling'

interface ProjectCardProps {
  project: ProjectWithStats
}

function getProjectHost(baseUrl: string): string {
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl
  }
}

export function ProjectCard({ project }: ProjectCardProps) {
  const router = useRouter()
  const [hovered, setHovered] = useState(false)

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    staleTime: STALE_STANDARD,
    refetchInterval: hovered ? POLL_STANDARD * 2 : false,
  })

  const { data: qualityGate, isLoading: qualityLoading } = useQuery({
    queryKey: ['quality-gate-health', project.id],
    queryFn: () => fetchQualityGateHealth(project.id),
    staleTime: STALE_STANDARD,
    refetchInterval: hovered ? POLL_STANDARD * 2 : false,
  })

  // Check for active checkpoint (running task)
  const { data: checkpoint } = useQuery({
    queryKey: ['active-checkpoint', project.id],
    queryFn: () => getActiveCheckpoint(project.id),
    staleTime: STALE_GIT,
  })

  // Generate gradient based on first letter (used as fallback if no logo)
  const gradients: Record<string, { from: string; to: string }> = {
    S: { from: '#00c853', to: '#009624' },
    P: { from: '#3b82f6', to: '#2563eb' },
    A: { from: '#8b5cf6', to: '#6d28d9' },
    C: { from: '#f59e0b', to: '#d97706' },
    B: { from: '#ec4899', to: '#be185d' },
    D: { from: '#06b6d4', to: '#0891b2' },
    default: { from: '#64748b', to: '#475569' },
  }
  const firstLetter = project.name.charAt(0).toUpperCase()
  const gradient = gradients[firstLetter] ?? gradients.default

  const { stats } = project
  const projectHost = getProjectHost(project.base_url)
  const metrics = [
    {
      key: 'features' as const,
      label: 'Features',
      title: 'View active features',
      count: stats.features,
      icon: Target,
      activeClass: 'text-blue-400 hover:text-blue-300',
    },
    {
      key: 'tasks' as const,
      label: 'Tasks',
      title: 'View active tasks',
      count: stats.tasks,
      icon: ListTodo,
      activeClass: 'text-purple-400 hover:text-purple-300',
    },
    {
      key: 'bugs' as const,
      label: 'Bugs',
      title: 'View active bugs',
      count: stats.bugs,
      icon: Bug,
      activeClass: 'text-amber-400 hover:text-amber-300',
    },
    {
      key: 'blocked' as const,
      label: 'Blocked',
      title: 'View blocked tasks',
      count: stats.blocked,
      icon: AlertCircle,
      activeClass: 'text-rose-400 hover:text-rose-300',
    },
  ]

  // Handle stat click - navigate to project with appropriate tab/filter
  const handleStatClick = (
    e: React.MouseEvent,
    type: 'features' | 'tasks' | 'bugs' | 'blocked',
  ) => {
    e.preventDefault()
    e.stopPropagation()

    switch (type) {
      case 'features':
        router.push(`/projects/${project.id}?tab=tasks&status=active&taskType=feature`)
        break
      case 'tasks':
        router.push(`/projects/${project.id}?tab=tasks&status=active&taskType=task`)
        break
      case 'bugs':
        router.push(
          `/projects/${project.id}?tab=tasks&status=active&taskType=bug`,
        )
        break
      case 'blocked':
        // Show blocked tasks (have incomplete dependencies)
        router.push(`/projects/${project.id}?tab=tasks&status=blocked`)
        break
    }
  }

  return (
    <article
      className={clsx(
        'card-interactive p-5 group',
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setHovered(true)}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          {project.logo_url ? (
            <div className="w-12 h-12 rounded-xl overflow-hidden bg-slate-800 flex items-center justify-center">
              <Image
                src={project.logo_url}
                alt={project.name}
                width={48}
                height={48}
                className="object-cover w-full h-full"
              />
            </div>
          ) : (
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{
                background: `linear-gradient(135deg, ${gradient.from} 0%, ${gradient.to} 100%)`,
              }}
            >
              <span className="display font-bold text-xl text-slate-100">
                {firstLetter}
              </span>
            </div>
          )}
          <div>
            <Link
              href={`/projects/${project.id}`}
              className="font-medium text-slate-100 transition-colors hover:text-phosphor-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/60 rounded-sm"
            >
              {project.name}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
              <span className="font-mono">{projectHost}</span>
              {project.root_path ? (
                <span
                  className="max-w-[240px] truncate font-mono text-slate-600"
                  title={project.root_path}
                >
                  {project.root_path}
                </span>
              ) : (
                <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-2xs text-amber-300">
                  No root path
                </span>
              )}
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-2xs">
              <Link
                href={`/projects/${project.id}/settings`}
                className="inline-flex items-center gap-1 rounded-md border border-slate-700/60 bg-slate-800/40 px-2.5 py-1 text-slate-400 transition-all hover:border-slate-500 hover:text-slate-200 hover:bg-slate-750/60"
              >
                <Settings2 className="w-3 h-3" />
                Settings
              </Link>
              <a
                href={project.base_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-slate-700/60 bg-slate-800/40 px-2.5 py-1 text-slate-400 transition-all hover:border-slate-500 hover:text-slate-200 hover:bg-slate-750/60"
              >
                <ExternalLink className="w-3 h-3" />
                Open app
              </a>
            </div>
            {checkpoint && (
              <div className="flex items-center gap-1.5 mt-1 text-xs text-phosphor-400">
                <Database className="w-3 h-3" />
                <span>Active checkpoint</span>
                <span className="font-mono">{checkpoint.task_id}</span>
                <span className="text-slate-500">{checkpoint.age}</span>
              </div>
            )}
            {(health || qualityGate) && (
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className={clsx(
                  'text-slate-500',
                  health?.healthy === false && 'text-rose-300',
                )}>
                  Service:{' '}
                  {health
                    ? health.healthy
                      ? health.response_time_ms != null
                        ? `${Math.round(health.response_time_ms)}ms`
                        : 'healthy'
                      : health.error || 'unhealthy'
                    : 'pending'}
                </span>
                <span className={clsx(
                  'text-slate-500',
                  qualityGate && !qualityGate.overall_pass && 'text-amber-300',
                )}>
                  Quality:{' '}
                  {qualityGate
                    ? qualityGate.overall_pass
                      ? 'passing'
                      : `${qualityGate.total_unfixed} open`
                    : 'pending'}
                </span>
                {!project.root_path && (
                  <span className="text-amber-300">
                    Config: root path missing
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {qualityLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-purple-500 rounded-full animate-spin" />
          ) : qualityGate ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full status-dot-pulse',
                qualityGate.overall_pass
                  ? 'bg-purple-500 text-purple-500'
                  : 'bg-amber-500 text-amber-500',
              )}
              title={
                qualityGate.overall_pass
                  ? 'Quality gate passing'
                  : `Quality gate: ${qualityGate.total_unfixed} unfixed issues`
              }
              aria-label={
                qualityGate.overall_pass
                  ? 'Quality gate passing'
                  : `Quality gate has ${qualityGate.total_unfixed} unfixed issues`
              }
              data-testid="quality-gate-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-700"
              aria-label="Quality gate status unavailable"
              data-testid="quality-gate-indicator"
            />
          )}

          {healthLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
          ) : health ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full status-dot-pulse',
                health.healthy
                  ? 'bg-green-500 text-green-500'
                  : 'bg-rose-500 text-rose-500',
              )}
              title={
                health.healthy
                  ? `Service healthy${health.response_time_ms ? ` (${Math.round(health.response_time_ms)}ms)` : ''}`
                  : `Service error: ${health.error || 'Unhealthy'}`
              }
              aria-label={
                health.healthy
                  ? 'Project service healthy'
                  : `Project service unhealthy${health.error ? `: ${health.error}` : ''}`
              }
              data-testid="project-health-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-600"
              aria-label="Project health status unavailable"
              data-testid="project-health-indicator"
            />
          )}
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-700/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-0.5">
            {metrics.map((metric) => {
              const Icon = metric.icon
              return (
                <button
                  type="button"
                  key={metric.key}
                  onClick={(e) => handleStatClick(e, metric.key)}
                  className={clsx(
                    'flex items-center gap-1.5 text-xs px-2 py-1.5 rounded-md transition-all duration-200',
                    metric.count > 0
                      ? `${metric.activeClass} hover:bg-slate-800/60`
                      : 'text-slate-600 hover:text-slate-400 hover:bg-slate-800/40',
                  )}
                  title={metric.title}
                  aria-label={`${metric.label}: ${metric.count}`}
                >
                  <Icon className="w-3 h-3" />
                  <span className="tabular-nums font-semibold">{metric.count}</span>
                </button>
              )
            })}
          </div>

          <span className="text-2xs text-slate-600 flex items-center gap-1 font-mono">
            <Clock className="w-3 h-3" />
            {new Date(project.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
        </div>
      </div>
    </article>
  )
}
