'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertCircle, Bug, Clock, Database, ListTodo, Target } from 'lucide-react'
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
  const [showHealth, setShowHealth] = useState(false)

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  })

  const { data: qualityGate, isLoading: qualityLoading } = useQuery({
    queryKey: ['quality-gate-health', project.id],
    queryFn: () => fetchQualityGateHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  })

  // Check for active checkpoint (running task)
  const { data: checkpoint } = useQuery({
    queryKey: ['active-checkpoint', project.id],
    queryFn: () => getActiveCheckpoint(project.id),
    enabled: showHealth,
    staleTime: 30000,
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
        'card-elevated p-5 group transition-all duration-300',
        'hover:border-phosphor-500/50 hover:translate-y-[-2px]',
      )}
      onMouseEnter={() => setShowHealth(true)}
      onFocusCapture={() => setShowHealth(true)}
      onTouchStart={() => setShowHealth(true)}
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
              <span className="display font-bold text-xl text-white">
                {firstLetter}
              </span>
            </div>
          )}
          <div>
            <Link
              href={`/projects/${project.id}`}
              className="font-medium text-white transition-colors hover:text-phosphor-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/60 rounded-sm"
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
              ) : null}
            </div>
            {checkpoint && (
              <div className="flex items-center gap-1.5 mt-1 text-xs text-cyan-400">
                <Database className="w-3 h-3" />
                <span>Active checkpoint</span>
                <span className="font-mono">{checkpoint.task_id}</span>
                <span className="text-slate-500">{checkpoint.age}</span>
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
                'w-3 h-3 rounded-full',
                qualityGate.overall_pass
                  ? 'bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.6)]'
                  : 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
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
                'w-3 h-3 rounded-full',
                health.healthy
                  ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]'
                  : 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]',
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

      <div className="mt-4 pt-3 border-t border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {metrics.map((metric) => {
              const Icon = metric.icon
              return (
                <button
                  key={metric.key}
                  onClick={(e) => handleStatClick(e, metric.key)}
                  className={clsx(
                    'flex items-center gap-1 text-xs transition-colors',
                    metric.count > 0
                      ? metric.activeClass
                      : 'text-slate-500 hover:text-slate-400',
                  )}
                  title={metric.title}
                  aria-label={`${metric.label}: ${metric.count}`}
                >
                  <Icon className="w-3 h-3" />
                  <span className="tabular-nums">{metric.count}</span>
                </button>
              )
            })}
          </div>

          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(project.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </article>
  )
}
